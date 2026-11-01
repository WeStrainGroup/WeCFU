"""Versioned raw10 frozen classifier; no fit, labels or I/O.

Raw twelve-feature machine rows stay unchanged. Only classifier input is projected.
No fit, files, labels, providers or model loading. The integrating caller must first
validate the prediction-only artifact against the public product manifest.
The provider binds the approved parameter bytes and fixed recipe.
"""
import copy
import math


KEEP = (0, 1, 2, 5, 6, 7, 8, 9, 10, 11)
FEATURES12 = (
    'DINO_max_token_sigmoid_score', 'DINO_log_normalized_box_area',
    'DINO_log_box_aspect', 'nearest_D0_distance_shortside', 'has_D0_center',
    'automatic_plate_radial_ratio', 'local_Y_median_difference',
    'local_Y_absolute_median_difference', 'local_chroma_median_difference_norm',
    'local_Y_IQR_difference', 'local_core_valid_fraction', 'local_ring_valid_fraction')
FEATURES10 = tuple(FEATURES12[i] for i in KEEP)
MISSING12 = (3, 6, 7, 8, 9)
MISSING10 = (4, 5, 6, 7)
THRESHOLD = .75


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def project12(values):
    require(type(values) is list and len(values) == 12, 'raw twelve-feature list')
    require(all((v is None and i in MISSING12) or finite(v)
                for i, v in enumerate(values)), 'raw finite/declared-missing values')
    require(type(values[4]) in (int, float) and values[4] in (0, 1)
            and (values[3] is None) == (values[4] == 0), 'raw D0 presence consistency')
    result = [values[i] for i in KEEP]
    require(all((v is None and i in MISSING10) or finite(v)
                for i, v in enumerate(result)), 'projected missing-column mapping')
    return result


def validate_model10(model):
    # Numerical schema; the provider separately verifies exact parameter bytes.
    require(model['feature_names'] == list(FEATURES10)
            and model['feature_projection'] == list(KEEP), 'fixed ordered projection')
    require(model['threshold'] == THRESHOLD and model['dtype'] == 'float64'
            and model['L2_coefficient'] == 1 and model['success'] is True,
            'fixed numeric recipe')
    require(len(model['coefficients']) == 10
            and all(finite(v) for v in model['coefficients'] + [model['intercept']]),
            'ten finite frozen coefficients')
    prep = model['preprocessing']
    require(set(prep) == {'medians', 'all_missing', 'means', 'scales', 'ddof'}
            and prep['ddof'] == 0, 'frozen preprocessing')
    require(all(len(prep[k]) == 10 for k in ('medians', 'all_missing', 'means', 'scales'))
            and all(finite(v) for k in ('medians', 'means', 'scales') for v in prep[k])
            and all(type(v) is bool for v in prep['all_missing'])
            and all(v > 0 for v in prep['scales']), 'ten-column preprocessing')


def predict_numeric10(rows12, model):
    """Same frozen float64 transform/logit; preserves row and raw-center identity."""
    import numpy as np
    from scipy.special import expit
    validate_product_model(model)
    # Validate every raw row, but never redo geometry/dedup or move coordinates.
    projected = [project12(row['features']) for row in rows12]
    eligible = [(row, values) for row, values in zip(rows12, projected) if row['eligible']]
    prep = model['preprocessing']
    x = np.asarray([[np.nan if v is None else v for v in values]
                    for _, values in eligible], dtype=np.float64).reshape((-1, 10))
    x = (np.where(np.isnan(x), np.asarray(prep['medians']), x)
         - np.asarray(prep['means'])) / np.asarray(prep['scales'])
    logits = x @ np.asarray(model['coefficients']) + model['intercept']
    probabilities = expit(logits)
    require(np.isfinite(logits).all() and np.isfinite(probabilities).all(), 'finite prediction')
    return [{k: copy.deepcopy(row[k]) for k in
             ('occurrence_id', 'path', 'sha256', 'group', 'query_index', 'selection_rank', 'original_center')}
            | {'logit': float(z), 'probability': float(p), 'accepted': bool(p >= THRESHOLD)}
            for (row, _), z, p in zip(eligible, logits, probabilities)]


def validate_product_model(model):
    require(model.get('recipe_id') == 'sam_dino_raw10_threshold075_auto095_v2',
            'approved Fusion v2 recipe only')
    require(model.get('D0_exclusion_fraction') == .025
            and model.get('DINO_dedup_fraction') == .005
            and model.get('ROI_max_radial') == .95
            and model.get('coordinate_method') == 'raw_DINO_unchanged', 'fixed raw geometry recipe')
    validate_model10(model)


# The v1 feature/appearance and output-ring implementations stay byte-identical.
try:
    from . import fusion_math as original
except ImportError:
    import fusion_math as original
FEATURES = original.FEATURES
STRICT = .025
DEDUP = .005
RADIAL = .95
points = original.points
group_of = original.group_of
preview_annotations = original.preview_annotations


def machine_candidates(image, dino, baseline):
    """All original kept DINO query occurrences; filter and score-ordered dedup separate.
    No centers, scores or box coordinates are rounded/reestimated.
    Eligibility is applied before dedup so an ineligible point cannot suppress one.
    Equal-score ties are broken by original query index. Distance bounds are inclusive
    for dedup and radial admission, strict greater-than for D0 separation.
    """
    group=group_of(image); short=min(image['width'],image['height'])
    require(short>0 and dino['path']==baseline['path']==image['path'] and dino['sha256']==baseline['sha256']==image['sha256'], 'source identity')
    dp=points(dino['points']); bp=points(baseline['points']); qs=dino['kept_query_indices']
    require(len(dp)==len(qs) and len(set(qs))==len(qs) and dino['count']==len(dp), 'all original DINO occurrences')
    plate=image['automatic_plate']; require(all(finite(plate[k]) for k in ('cx','cy','r')) and plate['r']>0, 'automatic plate only')
    rows=[]
    for index,(point,q) in enumerate(zip(dp,qs)):
        require(type(q) is int and 0<=q<len(dino['raw_queries']['boxes']), 'original query index')
        box=copy.deepcopy(dino['raw_queries']['boxes'][q]); score=dino['raw_queries']['scores'][q]
        require(len(box)==4 and all(finite(x) for x in box) and box[2]>=0 and box[3]>=0 and finite(score) and 0<=score<=1, 'original finite machine score/box')
        distance=min((math.hypot(point[0]-p[0],point[1]-p[1])/short for p in bp), default=None)
        radial=math.hypot(point[0]-plate['cx'],point[1]-plate['cy'])/plate['r']
        base=[score, math.log(max(box[2]*box[3],1e-12)), math.log(max(box[2],1e-12)/max(box[3],1e-12)), distance, int(bool(bp)), radial]
        reasons=[]
        if distance is not None and distance<=STRICT: reasons.append('within_D0_wide_radius')
        if radial>RADIAL: reasons.append('outside_automatic_095_roi')
        rows.append({'occurrence_id':image['path']+'#dino-query-'+str(q), 'path':image['path'], 'sha256':image['sha256'], 'group':group,
                     'query_index':q, 'detection_index':index, 'original_center':point, 'box':box, 'features':base,
                     'geometry_eligible':not reasons, 'exclusion_reasons':reasons, 'eligible':False,
                     'dedup_kept_occurrence_id':None, 'selection_rank':None})
    kept=[]
    for row in sorted((r for r in rows if r['geometry_eligible']), key=lambda r:(-r['features'][0],r['query_index'])):
        duplicate=next((r for r in kept if math.hypot(row['original_center'][0]-r['original_center'][0],row['original_center'][1]-r['original_center'][1])<=DEDUP*short),None)
        if duplicate is not None:
            row['exclusion_reasons'].append('duplicate_DINO_center'); row['dedup_kept_occurrence_id']=duplicate['occurrence_id']
        else:
            row['eligible']=True; row['selection_rank']=len(kept); kept.append(row)
    return rows


def feature_rows(image, dino, baseline, rgb):
    try:
        from .appearance_runtime import local_features
    except ImportError:
        from appearance_runtime import local_features
    # Always starts from every raw kept query, never v1 eligible/dedup output.
    rows = machine_candidates(image, dino, baseline)
    require(rgb.shape[:2] == (image['height'], image['width']), 'original RGB dimensions')
    appearance = []
    for row in rows:
        values, sampling = local_features(rgb, row['original_center'], row['box'])
        appearance.append({k: copy.deepcopy(row[k]) for k in ('occurrence_id', 'original_center', 'sha256')}
                          | {'features': values, 'sampling': sampling})
    return original.attach_appearance(rows, appearance)


def predict_frozen(features, model):
    return predict_numeric10(features, model)
