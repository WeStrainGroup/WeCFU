"""Frozen prediction-only feature/transform primitives; no fit/labels/eval."""
import copy,math

FEATURES = ('DINO_max_token_sigmoid_score', 'DINO_log_normalized_box_area',
            'DINO_log_box_aspect', 'nearest_D0_distance_shortside', 'has_D0_center',
            'automatic_plate_radial_ratio', 'local_Y_median_difference',
            'local_Y_absolute_median_difference', 'local_chroma_median_difference_norm',
            'local_Y_IQR_difference', 'local_core_valid_fraction', 'local_ring_valid_fraction')

DIM = 12

MISSING = (3, 6, 7, 8, 9)

THRESHOLD = .75

STRICT = .01

DEDUP = .005

RADIAL = .95

def require(ok, message):
    if not ok:
        raise ValueError(message)

def finite(x):
    return type(x) in (int, float) and math.isfinite(x)

def points(value):
    require(type(value) is list and all(type(p) is list and len(p)==2 and all(finite(v) for v in p) for p in value), 'ordered finite point occurrences')
    return copy.deepcopy(value)

def validate_values(values):
    require(len(values)==DIM and all(v is None and i in MISSING or finite(v) for i,v in enumerate(values)), 'twelve finite or declared-missing features')
    require(values[4] in (0,1) and (values[3] is None)==(values[4]==0), 'D0 absence is missing distance plus indicator')

def transform(rows, prep):
    import numpy as np
    require(set(prep)=={'medians','all_missing','means','scales','ddof'} and prep['ddof']==0, 'train-only preprocessing contract')
    require(all(len(prep[k])==DIM for k in ('medians','all_missing','means','scales')) and all(finite(v) for k in ('medians','means','scales') for v in prep[k]) and all(v>0 for v in prep['scales']), 'finite frozen preprocessing')
    for r in rows: validate_values(r['features'])
    x=np.asarray([[np.nan if v is None else v for v in r['features']] for r in rows],dtype=np.float64).reshape((-1,DIM))
    return (np.where(np.isnan(x),np.asarray(prep['medians']),x)-np.asarray(prep['means']))/np.asarray(prep['scales'])


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
        if distance is not None and distance<=STRICT: reasons.append('within_D0_strict_radius')
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


def attach_appearance(rows, appearance):
    require(len(rows)==len(appearance), 'all candidate appearance rows')
    output=[]
    for row,local in zip(rows,appearance):
        require(row['occurrence_id']==local['occurrence_id'] and row['original_center']==local['original_center'] and row['sha256']==local['sha256'], 'appearance identity/order')
        values=row['features']+local['features']; validate_values(values)
        output.append(copy.deepcopy(row)|{'features':values,'sampling':copy.deepcopy(local['sampling'])})
    return output


def eligible_for_image(features, path):
    return sorted((r for r in features if r['path']==path and r['eligible']), key=lambda r:r['selection_rank'])


def group_of(image):
    # Metadata-only identifier. It is never a model feature or routing input.
    require(image['view'] in ('main','blank'), 'front/blank only; no back branch')
    return 'runtime-image'


def feature_rows(image, dino, baseline, rgb):
    from appearance_runtime import local_features
    rows=machine_candidates(image,dino,baseline)
    require(rgb.shape[:2]==(image['height'],image['width']), 'original RGB dimensions')
    appearance=[]
    for row in rows:
        values,sampling=local_features(rgb,row['original_center'],row['box'])
        appearance.append({k:copy.deepcopy(row[k]) for k in ('occurrence_id','original_center','sha256')}|{'features':values,'sampling':sampling})
    return attach_appearance(rows,appearance)


def predict_frozen(features, model):
    """Inference only. Artifact SHA/provenance/full-fit eligibility is caller-bound.
    No training, imputation refit, thresholds search, person routing, or labels.
    """
    import numpy as np
    from scipy.special import expit
    require(model.get('method')=='D0_DINO_full88_residual_12_L2_1_threshold075_v1' and model.get('fitted_once_on_all88_scope_images') is True and model.get('prospective_images_used') is False and model.get('model_role')=='single_fullfit_candidate' and model.get('training_scope_images')==88 and model.get('training_scope')=='historical_valid_count_and_centers_only' and not ({'held_group','held_out_group'}&set(model)),'approved full-fit artifact only; no LOGO fold model')
    require(model['feature_names']==list(FEATURES) and model['threshold']==THRESHOLD and model['dtype']=='float64' and model['success'] is True, 'fixed fitted model recipe')
    require(len(model['coefficients'])==DIM and all(finite(v) for v in model['coefficients']+[model['intercept']]), 'finite frozen model')
    eligible=[r for r in features if r['eligible']]
    x=transform(eligible,model['preprocessing']); logits=x@np.asarray(model['coefficients'])+model['intercept']; probabilities=expit(logits)
    require(np.isfinite(logits).all() and np.isfinite(probabilities).all(), 'finite prediction')
    return [{k:copy.deepcopy(r[k]) for k in ('occurrence_id','path','sha256','group','query_index','selection_rank','original_center')}|
            {'logit':float(z),'probability':float(p),'accepted':bool(p>=THRESHOLD)} for r,z,p in zip(eligible,logits,probabilities)]


def preview_annotations(image, baseline_circles, features, decisions):
    """Append box-derived display rings; they are not SAM masks or measured colony radii.
    Source D0 circles/order are copied exactly. Display radius cannot affect scores.
    """
    require(type(baseline_circles)is list, 'D0 circles')
    by={d['occurrence_id']:d for d in decisions}; require(len(by)==len(decisions), 'unique decisions')
    eligible=eligible_for_image(features,image['path'])
    require(set(by)=={r['occurrence_id'] for r in eligible}, 'one decision for every eligible candidate')
    output=copy.deepcopy(baseline_circles)
    for row in eligible:
        d=by[row['occurrence_id']]
        require(all(d[k]==row[k] for k in ('path','sha256','query_index','selection_rank','original_center')) and d['accepted']==(d['probability']>=THRESHOLD), 'same frozen decision')
        if d['accepted']:
            bw=row['box'][2]*image['width'];bh=row['box'][3]*image['height']
            output.append({'cx':row['original_center'][0],'cy':row['original_center'][1],
                           'r':max(1.,math.hypot(bw,bh)/2.),'origin':'DINO_filtered_supplement',
                           'radius_kind':'display_box_enclosing_circle_not_mask',
                           'query_index':row['query_index'],'probability':d['probability']})
    return output
