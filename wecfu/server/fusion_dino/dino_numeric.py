"""Exact pure045 output/coordinate/raster contract; no runner import."""
import hashlib,io,json,math,struct

def require(ok,message):
    if not ok:raise ValueError(message)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]

def point(box,h,w):return [f32(box[0]*w),f32(box[1]*h)]

def corners(box,h,w):
    cx,cy,bw,bh=box
    return [f32(f32(cx-f32(.5*bw))*w),f32(f32(cy-f32(.5*bh))*h),f32(f32(cx+f32(.5*bw))*w),f32(f32(cy+f32(.5*bh))*h)]

def safe_raster(Image,raw,row):
    with Image.open(io.BytesIO(raw)) as im:
        orientation=im.getexif().get(274)
        require(orientation is None or type(orientation)is int and orientation==1,'nontrivial/invalid EXIF orientation')
        require(im.size==(row['width'],row['height']),'original raster dimensions')
        return im.convert('RGB'),orientation

def tensor_sha(t):return sha(t.detach().contiguous().view(-1).view(__import__('torch').uint8).numpy().tobytes())

def infer_output(torch,processor,outputs,inputs,h,w):
    logits=outputs.logits;boxes=outputs.pred_boxes
    require(logits.shape==(1,900,256) and boxes.shape==(1,900,4) and logits.dtype==boxes.dtype==torch.float32,'model output layout')
    require(inputs['input_ids'].tolist()==[[101,5701,1012,102]] and inputs['attention_mask'].tolist()==[[1]*4],'fixed tokenization')
    require(bool(torch.isfinite(logits[:,:,:4]).all()) and bool(torch.isneginf(logits[:,:,4:]).all()),'only expected padding -inf')
    require(bool(torch.isfinite(boxes).all()) and bool(((boxes>=0)&(boxes<=1)).all()),'finite normalized boxes')
    scores=logits.sigmoid().max(-1).values[0];keep=(scores>.25).nonzero().flatten()
    result=processor.post_process_grounded_object_detection(outputs,input_ids=inputs['input_ids'],threshold=.25,text_threshold=.25,target_sizes=[(h,w)])[0]
    require(torch.equal(result['scores'],scores[keep]),'official scores/query order')
    raw=boxes[0].tolist();ks=keep.tolist();xy=result['boxes'].tolist()
    require(xy==[corners(raw[i],h,w) for i in ks],'official coordinate parity')
    return {'raw_queries':{'boxes':raw,'scores':scores.tolist()},'kept_query_indices':ks,'points':[point(raw[i],h,w) for i in ks],'count':len(ks),'predicted_count':len(ks),'official_boxes_xyxy':xy,'text_labels':result['text_labels'],'input_ids':[101,5701,1012,102],'no_NMS_ROI_or_label_filter':True,'postprocessor_exact':True,'logits_summary':{'shape':list(logits.shape),'dtype':str(logits.dtype),'sha256':tensor_sha(logits),'active_finite':True,'padded_negative_infinity':900*252}}
