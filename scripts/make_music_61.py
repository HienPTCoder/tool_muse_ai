"""Procedural melancholic ambient bed (no downloads): slow pad chords + soft pluck arpeggio, minor -> major at 'the choice'."""
import numpy as np, soundfile as sf, sys
SR=44100; TOTAL=float(sys.argv[1]); TURN=float(sys.argv[2]); out=sys.argv[3]
rng=np.random.default_rng(7)
def hz(m): return 440*2**((m-69)/12)
def tone(f,dur,att,rel,amp,harm=(1,.45,.2)):
    n=int(dur*SR); t=np.arange(n)/SR
    w=sum(a*np.sin(2*np.pi*f*(i+1)*t+rng.uniform(0,6.28)) for i,a in enumerate(harm))
    env=np.minimum(1,t/att)*np.minimum(1,(dur-t)/rel); return w*env*amp
MIN=[(57,[45,52,57,60,64]),(53,[41,48,53,57,60]),(48,[36,48,55,60,64]),(55,[43,50,55,59,62])]   # Am F C G
MAJ=[(48,[36,48,55,60,64]),(55,[43,50,55,59,62]),(57,[45,52,57,60,64]),(53,[41,48,53,57,60])]   # C G Am F
L=np.zeros((int(TOTAL*SR)+SR*12,),dtype=np.float32); R=L.copy()
BAR=8.0; t0=0.0; k=0
while t0<TOTAL:
    prog=MIN if t0<TURN else MAJ
    root,notes=prog[k%4]; k+=1
    for j,m in enumerate(notes):
        s=tone(hz(m),BAR+3,2.5,3.5,0.045*(1 if m<50 else .8)); i=int(t0*SR)
        pan=0.3+0.4*(j/len(notes)); L[i:i+len(s)]+=s*(1-pan); R[i:i+len(s)]+=s*pan
    # soft plucks
    scale=[n+12 for n in notes[2:]]+[n+24 for n in notes[2:4]]
    steps=6 if t0<TURN else 8
    for q in range(steps):
        if rng.random()<0.25: continue
        m=scale[rng.integers(len(scale))]; at=t0+q*BAR/steps+rng.uniform(0,.15)
        s=tone(hz(m),3.5,0.01,3.0,0.05*(0.6 if t0<TURN else 0.9),(1,.3,.1))
        s*=np.exp(-np.arange(len(s))/SR*1.1); i=int(at*SR); pan=rng.uniform(.25,.75)
        L[i:i+len(s)]+=s*(1-pan); R[i:i+len(s)]+=s*pan
    t0+=BAR
y=np.stack([L[:int(TOTAL*SR)],R[:int(TOTAL*SR)]],1)
fade=np.minimum(1,np.arange(len(y))/(SR*4))*np.minimum(1,(len(y)-np.arange(len(y)))/(SR*8)); y*=fade[:,None]
y=y/np.max(np.abs(y))*0.8
sf.write(out,y,SR)
