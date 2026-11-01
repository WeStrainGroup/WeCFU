"""Exact frozen six appearance features; no training, I/O or labels."""
import copy,math

NAMES=('local_Y_median_difference','local_Y_absolute_median_difference','local_chroma_median_difference_norm','local_Y_IQR_difference','local_core_valid_fraction','local_ring_valid_fraction')

CORE=tuple((i,j) for j in range(-16,17) for i in range(-16,17) if i*i+j*j<=64)

RING=tuple((i,j) for j in range(-16,17) for i in range(-16,17) if 144<=i*i+j*j<=256)

def require(ok,msg):
    if not ok:raise ValueError(msg)

def quantile(values,p):
    require(len(values)>0 and p in (.25,.5,.75),'fixed nonempty quantile')
    a=sorted(float(v) for v in values);h=(len(a)-1)*p;lo=math.floor(h);hi=math.ceil(h)
    return a[lo]+(a[hi]-a[lo])*(h-lo)

def local_features(rgb,center,box):
    """Return six scalars + sampling audit. rgb uint8 H/W/3, original033 xy."""
    import numpy as np
    require(isinstance(rgb,np.ndarray) and rgb.dtype==np.uint8 and rgb.ndim==3 and rgb.shape[2]==3,'original uint8 RGB raster')
    h,w=rgb.shape[:2];require(h>0 and w>0 and len(center)==2 and len(box)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in [*center,*box]) and box[2]>=0 and box[3]>=0,'finite original machine geometry')
    x,y=map(float,center);a=max(2.,float(box[2])*w/4.);b=max(2.,float(box[3])*h/4.)
    def sample(grid):
        values=[]
        for i,j in grid:
            sx=x+a*(i/8.);sy=y+b*(j/8.)
            if not(0<=sx<=w-1 and 0<=sy<=h-1):continue
            x0=math.floor(sx);y0=math.floor(sy);x1=min(x0+1,w-1);y1=min(y0+1,h-1);dx=sx-x0;dy=sy-y0
            q00=rgb[y0,x0].astype(np.float64)/255.;q10=rgb[y0,x1].astype(np.float64)/255.
            q01=rgb[y1,x0].astype(np.float64)/255.;q11=rgb[y1,x1].astype(np.float64)/255.
            r,g,bl=((1-dy)*((1-dx)*q00+dx*q10)+dy*((1-dx)*q01+dx*q11)).tolist()
            values.append((.2126*r+.7152*g+.0722*bl,r-g,bl-g))
        return values
    inner,outer=sample(CORE),sample(RING)
    result=[None]*4
    if inner and outer:
        yi=[v[0] for v in inner];yo=[v[0] for v in outer];delta=quantile(yi,.5)-quantile(yo,.5)
        color=math.hypot(*(quantile([v[k] for v in inner],.5)-quantile([v[k] for v in outer],.5) for k in (1,2)))
        texture=(quantile(yi,.75)-quantile(yi,.25))-(quantile(yo,.75)-quantile(yo,.25))
        result=[delta,abs(delta),color,texture]
    result += [len(inner)/197.,len(outer)/360.]
    require(all(v is None or math.isfinite(v) for v in result),'finite local statistics')
    return result,{'center_original033':copy.deepcopy(center),'box_original033':copy.deepcopy(box),'axes_px':[a,b],'core_nominal':197,'ring_nominal':360,'core_valid':len(inner),'ring_valid':len(outer),'interpolation':'bilinear_float64_encoded_RGB','outside_samples_clipped':False}
