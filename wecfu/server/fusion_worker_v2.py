"""Public offline image-feature / frozen-classifier stages. No fitting or network."""
from pathlib import Path
import hashlib,json,os,socket,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'fusion_dino'))
from dino_contract import read_json,identity,output_json,require
from dino_numeric import safe_raster
import fusion_math_v2 as fusion_math


def deny(*a,**k):raise RuntimeError('Fusion worker is offline and cannot start other processes')


def main(folder,stage):
    folder=folder.resolve(strict=True)
    socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny
    def guard(name,args):
        if name in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):deny()
        if name=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0]));parts={v.lower() for v in path.parts}
            if parts & {'references','human-review-archive','review-archives','evaluation-only'}:deny()
    sys.addaudithook(guard)
    request=read_json(folder/'fusion-request.json');image=request['image']
    if stage=='features':
        import PIL,numpy as np
        from PIL import Image
        require(PIL.__version__=='13.0.0','fixed Pillow13 raster')
        raw=(folder/'source.image').read_bytes();require(hashlib.sha256(raw).hexdigest()==image['sha256'],'same source bytes')
        picture,_=safe_raster(Image,raw,image)
        try:rgb=np.asarray(picture,dtype=np.uint8)
        finally:picture.close()
        dino=read_json(folder/'dino/prediction.json',request['dino_prediction_sha256'])
        features=fusion_math.feature_rows(image,dino,request['baseline'],rgb)
        output_json(folder/'features.json',features)
    elif stage=='classify':
        artifact=read_json(folder/'filter.json',request['filter_artifact_sha256'])
        features=read_json(folder/'features.json')
        decisions=fusion_math.predict_frozen(features,artifact['model'])
        circles=fusion_math.preview_annotations(image,request['baseline_circles'],features,decisions)
        original=request['baseline_circles'];require(circles[:len(original)]==original,'D0 exact prefix')
        marks=list(original)
        for ring in circles[len(original):]:
            marks.append({'id':len(marks)+1,'cx':ring['cx'],'cy':ring['cy'],'r':ring['r'],
                          'score':ring['probability'],'accepted':True,'source':'cv'})
        output_json(folder/'fusion-result.json',{'status':'ok','image_sha256':image['sha256'],'detections':marks,
                    'd0_count':len(original),'supplemental_count':len(marks)-len(original),
                    'filter_artifact_sha256':request['filter_artifact_sha256'],
                    'annotation_kind':'SAM_D0_plus_box_derived_center_rings'})
    else:raise ValueError('unknown fixed fusion stage')


if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2])
