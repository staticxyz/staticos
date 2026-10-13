import numpy as np, random, math
from PIL import Image
W,H=480,270
B=np.array([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]])/16.0
def hexc(h): return np.array([int(h[i:i+2],16) for i in (1,3,5)],float)
def ramp(stops,t):
    t=np.clip(t,0,1)*(len(stops)-1); i=np.minimum(t.astype(int),len(stops)-2); f=(t-i)[...,None]
    s=np.array([hexc(x) for x in stops]); return s[i]*(1-f)+s[i+1]*f
def quant(img,levels):
    # палитра из уровней + bayer
    return img
def sky(stops,levels=7,h=H):
    y=np.linspace(0,1,h)[:,None].repeat(W,1)
    d=B[np.arange(h)[:,None]%4,np.arange(W)[None,:]%4]
    t=y*(levels-1); t=np.floor(t+d)/(levels-1)
    return ramp(stops,t)
def stars(img,n,seed,ymax,cols):
    r=random.Random(seed)
    for _ in range(n):
        x,y=r.randrange(W),r.randrange(ymax); img[y,x]=hexc(r.choice(cols))
        if r.random()<0.07:
            for dx,dy in((1,0),(-1,0),(0,1),(0,-1)):
                if 0<=x+dx<W and 0<=y+dy<H: img[y+dy,x+dx]=hexc(cols[0])*0.45+img[y+dy,x+dx]*0.55
def disc(img,cx,cy,r,shade,light=(-0.6,-0.6)):
    for y in range(int(cy-r-1),int(cy+r+2)):
        for x in range(int(cx-r-1),int(cx+r+2)):
            dx,dy=x-cx,y-cy
            if dx*dx+dy*dy<=r*r and 0<=x<W and 0<=y<H:
                nz=math.sqrt(max(0,1-(dx*dx+dy*dy)/(r*r)))
                l=(dx/r*light[0]+dy/r*light[1])*-1*0.6+nz*0.5+0.1
                l+=B[y%4,x%4]*0.18-0.09
                k=min(len(shade)-1,max(0,int(l*len(shade))))
                img[y,x]=hexc(shade[k])
def ridge(img,base,amp,seed,col,hi=None,rough=3):
    r=np.random.RandomState(seed); n=W
    a=np.zeros(n)
    for o in range(rough):
        k=2**(o+2); pts=r.rand(k+2); xs=np.linspace(0,k,n)
        a+=np.interp(xs,np.arange(k+2),pts)/(2**o)
    a=a/a.max()
    for x in range(W):
        top=int(base-a[x]*amp)
        img[top:,x]=hexc(col)
        if hi: img[top,x]=hexc(hi)
def wall1():
    img=sky(['#070b1a','#0d1630','#1b2850','#37426e','#7a6a8c','#d58a6a','#f2b78a'],9)
    stars(img,160,1,150,['#cfd8ff','#8fa0d8','#ffffff'])
    # луна
    disc(img,340,70,26,['#2a3358','#4a4f7c','#8e86a8','#d9c7c0','#f6e8d0'],(-0.7,-0.5))
    # гало
    for y in range(H):
        for x in range(W):
            d=math.hypot(x-340,y-70)
            if 26<d<44 and B[y%4,x%4]<(1-(d-26)/18)*0.5: img[y,x]=img[y,x]*0.75+hexc('#7a6a8c')*0.25
    ridge(img,185,60,3,'#2a2f55','#4c4f7e'); ridge(img,215,55,7,'#161b3a','#2c3160'); ridge(img,250,45,11,'#080c1c','#151a38')
    return img
def wall2():
    img=sky(['#050810','#0a1226','#14233f','#1f3a57','#2f5a6c','#4f8a86','#a8c7a0'],9,h=170)
    full=np.zeros((H,W,3)); full[:170]=img
    # море
    for y in range(170,H):
        t=(y-170)/(H-170)
        row=ramp(['#1c4a5e','#10304a','#08182c','#040a16'],np.full(W,t))
        full[y]=row
    stars(full,130,5,120,['#cfe6ff','#8ab8d8','#ffffff'])
    # планета с кольцом
    cx,cy,r=300,85,38
    disc(full,cx,cy,r,['#2a0d1a','#5a1a2a','#8f2f3a','#c65a4a','#eb8f6a','#ffd0a0'],(-0.7,-0.4))
    tilt=-0.18
    for ang in np.linspace(0,2*math.pi,1400):
        for rr,c in ((62,'#b9c8dc'),(58,'#7e92b0'),(54,'#4a5c7e')):
            x=int(cx+rr*math.cos(ang)); y=int(cy+rr*0.28*math.sin(ang)+(x-cx)*tilt)
            behind=math.sin(ang)<0
            inside=(x-cx)**2+(y-cy)**2<r*r
            if behind and inside: continue
            if 0<=x<W and 0<=y<H and B[y%4,x%4]<0.9: full[y,x]=hexc(c)
    # отражение: ровные полосы, тающие вниз
    rng=random.Random(4)
    for y in range(172,H,2):
        t=(y-170)/(H-170); w=int(30*(1-t*0.6)); j=rng.randint(-3,3)
        for x in range(cx-w+j,cx+w+j):
            if rng.random()<(1-t)*0.9 and 0<=x<W: full[y,x]=full[y,x]*0.45+hexc('#e07a5a')*0.55
    # горизонт-линия и островок
    full[170,:]=hexc('#7fb0a8')
    for x in range(60,130):
        h=int(14*math.exp(-((x-95)/22)**2)); 
        full[170-h:170,x]=hexc('#050810')
    return full
for n,f in (('dusk-moon',wall1),('planet-sea',wall2)):
    a=np.clip(f(),0,255).astype(np.uint8)
    Image.fromarray(a).resize((W*4,H*4),Image.NEAREST).save(f'pixelart-{n}.png')
print('ok')
