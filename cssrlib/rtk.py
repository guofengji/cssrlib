# -*- coding: utf-8 -*-
"""
Created on Sun Nov 15 20:03:45 2020

@author: ruihi
"""

import numpy as np
import gnss as gn
import rinex as rn
from pntpos import pntpos
from ephemeris import findeph,eph2pos,satposs
from ppp import tidedisp
from mlambda import mlambda

VAR_HOLDAMB=0.001

def zdres(nav,obs,rs,dts,rr):
    """ non-differencial residual """
    _c=gn.rCST.CLIGHT
    nf=nav.nf
    n=len(obs.P)
    y=np.zeros((n,nf*2))
    el=np.zeros(n)
    e=np.zeros((n,3))
    rr_=rr.copy()
    if nav.tidecorr:
        pos=gn.ecef2pos(rr_)
        disp=tidedisp(gn.gpst2utc(obs.t),pos)
        rr_+=disp
    pos=gn.ecef2pos(rr_)   
    for i in range(n):
        sys,prn=gn.sat2prn(obs.sat[i])
        if sys not in nav.gnss_t or obs.sat[i] in nav.excl_sat:
            continue
        r,e[i,:]=gn.geodist(rs[i,:],rr_)
        az,el[i]=gn.satazel(pos,e[i,:])
        if el[i]<nav.elmin:
            continue
        r+=-_c*dts[i]
        zhd=gn.tropmodel(obs.t,pos,np.deg2rad(90.0),0.0)
        mapfh,mapfw=gn.tropmapf(obs.t,pos,el[i])
        r+=mapfh*zhd
        
        j=2 if sys==gn.uGNSS.GAL else 1
        y[i,0]=obs.L[i,0]*_c/nav.freq[0]-r
        y[i,1]=obs.L[i,j]*_c/nav.freq[j]-r
        y[i,2]=obs.P[i,0]-r
        y[i,3]=obs.P[i,j]-r
    return y,e,el

def ddcov(nb,n,Ri,Rj,nv):
    """ DD measurement error covariance """
    R=np.zeros((nv,nv))
    k=0
    for b in range(n):
        for i in range(nb[b]):
            for j in range(nb[b]):
                R[k+i,k+j]=Ri[k+i]
                if i==j:
                    R[k+i,k+j]+=Rj[k+i]
        k+=nb[b] 
    return R

def sysidx(satlist,sys_ref):
    idx=[]
    for k,sat in enumerate(satlist):
        sys,prn=gn.sat2prn(sat)
        if sys==sys_ref:
            idx.append(k)
    return idx

def IB(s,f,na=3):
    idx=na+gn.uGNSS.MAXSAT*f+s-1
    return idx

def varerr(nav,sat,sys,el,f):
    s_el=np.sin(el)
    if s_el<=0.0:
        return 0.0
    fact= nav.eratio[f-nav.nf] if f>=nav.nf else 1
    a=fact*nav.err[1]
    b=fact*nav.err[2]
    return 2.0*(a**2+(b/s_el)**2)
    
def ddres(nav,x,y,e,sat,el):
    """ DD phase/code residual """
    _c=gn.rCST.CLIGHT
    nf=nav.nf
    ns=len(el)
    mode=1 if len(y)==ns else 0 # 0:DD,1:SD
#    posu=gn.ecef2pos(x)
#    posr=gn.ecef2pos(nav.rb)
    nb=np.zeros(2*4*2+2,dtype=int)
    Ri=np.zeros(ns*nf*2+2)
    Rj=np.zeros(ns*nf*2+2)
#    im=np.zeros(ns)
    nv=0;b=0
    H=np.zeros((ns*nf*2,nav.nx))
    v=np.zeros(ns*nf*2)
    idx_f=[0,1]
    for m,sys in enumerate(nav.gnss_t):
        for f in range(nf):
            idx_f[f]=nav.obs_idx[f][sys]
        for f in range(0,nf*2):
            if f<nf:
                freq=nav.freq[idx_f[f]]
            # reference satellite
            idx=sysidx(sat,sys)
            i=idx[np.argmax(el[idx])]
            for j in idx:
                if i==j:
                    continue
                ## DD residual
                if mode==0:
                    v[nv]=(y[i,f]-y[i+ns,f])-(y[j,f]-y[j+ns,f])
                else:
                    v[nv]=y[i,f]-y[j,f]                    
                H[nv,0:3]=-e[i,:]+e[j,:]
                if f<nf: # carrier
                    idx_i=IB(sat[i],f)
                    idx_j=IB(sat[j],f)
                    lami=_c/freq
                    v[nv]-=lami*(x[idx_i]-x[idx_j])
                    H[nv,idx_i]=lami
                    H[nv,idx_j]=-lami
                Ri[nv]=varerr(nav,sat[i],sys,el[i],f)
                Rj[nv]=varerr(nav,sat[j],sys,el[j],f)
                
                nb[b]+=1
                nv+=1
            b+=1
    v=np.resize(v,nv)
    H=np.resize(H,(nv,nav.nx))
    R=ddcov(nb,b,Ri,Rj,nv)

    return v,H,R

def valpos(nav,v,R,thres=4.0):
    """ post-file residual test """
    nv=len(v)
    fact=thres**2
    for i in range(nv):
        if v[i]**2 <= fact*R[i,i]:
            continue
        print("%i is large : %f"%(i,v[i]))
    return True

def ddidx(nav):
    """ index for SD to DD transformation matrix D """
    nb=0
    n=gn.uGNSS.MAXSAT
    na=nav.na
    ix=np.zeros((n,2),dtype=int)
    nav.fix=np.zeros((n,nav.nf))
    for m in range(gn.uGNSS.GNSSMAX):
        k=na
        for f in range(nav.nf):
            for i in range(k,k+n):
                sys,prn=gn.sat2prn(i-k+1)
                if (sys!=m) or sys not in nav.gnss_t:
                    continue
                if nav.x[i]==0.0:
                    continue
                nav.fix[i-k,f]=2
                break
            for j in range(k,k+n):
                sys,prn=gn.sat2prn(j-k+1)
                if (sys!=m) or sys not in nav.gnss_t:
                    continue
                if i==j or nav.x[j]==0.0:
                    continue
                ix[nb,:]=[i,j]
                nb+=1
                nav.fix[j-k,f]=2
            k+=n
    ix=np.resize(ix,(nb,2))
    return ix

def restamb(nav,bias,nb):
    """ restore SD ambiguity """
    nv=0 
    xa=nav.x
    xa[0:nav.na]=nav.xa[0:nav.na]
    
    for m in range(5):
        for f in range(nav.nf):
            n=0
            index=[]
            for i in range(gn.uGNSS.MAXSAT):
                sys,prn=gn.sat2prn(i+1)
                if sys!=m or nav.fix[i,f]!=2:
                    continue
                index.append(IB(i+1,f))
                n+=1
            if n<2:
                continue
            xa[index[0]] = nav.x[index[0]]
            for i in range(1,n):
                xa[index[i]]=xa[index[0]]-bias[nv]
                nv+=1
    return xa

def resamb_lambda(nav):
    nx=nav.nx;na=nav.na
    ix=ddidx(nav)
    nb=len(ix)
    if nb<=0:
        print("no valid DD")
        return -1

    # y=D*xc, Qb=D*Qc*D', Qab=Qac*D'
    y=nav.x[ix[:,0]]-nav.x[ix[:,1]]
    DP=nav.P[ix[:,0],na:nx]-nav.P[ix[:,1],na:nx]
    Qb=DP[:,ix[:,0]-na]-DP[:,ix[:,1]-na]
    Qab=nav.P[0:na,ix[:,0]]-nav.P[0:na,ix[:,1]]
    
    # MLAMBDA ILS
    b,s=mlambda(y,Qb)
    if s[0]<=0.0 or s[1]/s[0]>=nav.thresar[0]:
        nav.xa=nav.x[0:na]
        nav.Pa=nav.P[0:na,0:na]
        bias=b[:,0]   
        y-=b[:,0]
        Qb=np.linalg.inv(Qb)
        nav.xa-=Qab@Qb@y
        nav.Pa-=Qab@Qb@Qab.T
        
        # restore SD ambiguity
        xa=restamb(nav,bias,nb)
    else:
        nb=0

    return nb,xa

def kfupdate(x,P,H,v,R):
    n=len(x)
    ix=[]
    k=0
    for i in range(n):
        if x[i]!=0.0 and P[i,i]>0.0:
            ix.append(i);k+=1
    x_=x[ix]
    P_=P[ix,:][:,ix]
    H_=H[:,ix]
    PHt=P_@H_.T
    S=H_@PHt+R
    K=PHt@np.linalg.inv(S)
    x_+=K@v
    P_-=K@H_@P_
    x[ix]=x_
    
    for k1,i in enumerate(ix):
       for k2,j in enumerate(ix):
           P[i,j] = P_[k1,k2]
       
    return x,P

def rtkinit(nav,pos0=np.zeros(3)):
    nav.nf=2
    nav.pmode=0 # 0:static, 1:kinematic

    nav.na=3 if nav.pmode==0 else 6
    nav.ratio=0
    nav.thresar=[2]
    nav.nx=nav.na+gn.uGNSS.MAXSAT*nav.nf
    nav.x=np.zeros(nav.nx)
    nav.P=np.zeros((nav.nx,nav.nx))
    nav.xa=np.zeros(nav.na)
    nav.Pa=np.zeros((nav.na,nav.na))
    nav.nfix=nav.neb=0
    nav.eratio=[100,100]
    nav.err=[0,0.003,0.003]
    nav.sig_p0 = 30.0
    nav.sig_v0 = 10.0
    nav.sig_n0 = 30.0
    nav.sig_qp=0.1
    nav.sig_qv=0.01
    #
    nav.x[0:3]=pos0
    di = np.diag_indices(6)
    nav.P[di[0:3]]=nav.sig_p0**2
    nav.q=np.zeros(nav.nx)
    nav.q[0:3]=nav.sig_qp**2    
    if nav.pmode>=1:
        nav.P[di[3:6]]=nav.sig_v0**2
        nav.q[3:6]=nav.sig_qv**2 
    # obs index
    i0={gn.uGNSS.GPS:0,gn.uGNSS.GAL:0,gn.uGNSS.QZS:0}
    i1={gn.uGNSS.GPS:1,gn.uGNSS.GAL:2,gn.uGNSS.QZS:1}
    freq0={gn.uGNSS.GPS:nav.freq[0],gn.uGNSS.GAL:nav.freq[0],gn.uGNSS.QZS:nav.freq[0]}
    freq1={gn.uGNSS.GPS:nav.freq[1],gn.uGNSS.GAL:nav.freq[2],gn.uGNSS.QZS:nav.freq[1]}
    nav.obs_idx=[i0,i1]
    nav.obs_freq=[freq0,freq1]
        
def udstate(nav,obs,obsb,iu,ir):
    tt=1.0

    ns=len(iu)
    sys=[]
    sat=obs.sat[iu]
    for sat_i in obs.sat[iu]:
        sys_i,prn=gn.sat2prn(sat_i)
        sys.append(sys_i)

    # pos,vel
    na=nav.na
    if nav.pmode>=1:
        F=np.eye(na)
        F[0:3,3:6]=np.eye(3)*tt
        nav.x[0:3]+=tt*nav.x[3:6]
        Px=nav.P[0:na,0:na]
        Px=F.T@Px@F
        Px[np.diag_indices(nav.na)]+=nav.q[0:nav.na]*tt
        nav.P[0:na,0:na]=Px
    # bias
    for f in range(nav.nf):
        bias=np.zeros(ns)
        offset=0
        na=0
        for i in range(ns):
            if sys[i] not in nav.gnss_t:
                continue
            j=nav.obs_idx[f][sys[i]]
            freq=nav.obs_freq[f][sys[i]]
            cp=obs.L[iu[i],j]-obsb.L[ir[i],j]
            pr=obs.P[iu[i],j]-obsb.P[ir[i],j]
            bias[i]=cp-pr*freq/gn.rCST.CLIGHT   
            amb=nav.x[IB(sat[i],f,nav.na)]
            if amb!=0.0:
                offset+=bias[i]-amb
                na+=1
        # adjust phase-code coherency
        if na>0:
            db=offset/na
            for i in range(gn.uGNSS.MAXSAT):
                if nav.x[IB(i+1,f,nav.na)]!=0.0:
                    nav.x[IB(i+1,f,nav.na)]+=db
        # initialize ambiguity
        for i in range(ns):
            j=IB(sat[i],f,nav.na)
            if bias[i]==0.0 or nav.x[j]!=0.0:
                continue
            nav.x[j]=bias[i]
            nav.P[j,j]=nav.sig_n0**2
    return 0
                

def selsat(nav,obs,obsb,elb):
    idx0=np.where(elb>=nav.elmin)
    idx=np.intersect1d(obs.sat,obsb.sat[idx0],return_indices=True)
    k=len(idx[0])
    iu=idx[1]
    ir=idx0[0][idx[2]]
    return k,iu,ir

def holdamb(nav,xa):
    """ hold integer ambiguity """
    nb=nav.nx-nav.na
    v=np.zeros(nb)
    H=np.zeros((nb,nav.nx))
    index=[]
    nv=0

    for m in range(gn.uGNSS.GNSSMAX):
        for f in range(nav.nf):
            n=0
            for i in range(gn.uGNSS.MAXSAT):
                sys,prn=gn.sat2prn(i+1)
                if sys!=m or nav.fix[i,f]!=2:
                    continue
                index.append(IB(i+1,f))
                n+=1
                nav.fix[i,f]==3 # hold
            # constraint to fixed ambiguity
            for i in range(1,n):
                v[nv]=(xa[index[0]]-xa[index[i]])-(nav.x[index[0]]-nav.x[index[i]])
                H[nv,index[0]]=1
                H[nv,index[i]]=-1
                nv+=1
    if nv>0:
        R=np.eye(nv)*VAR_HOLDAMB
        # update states with constraints
        nav.x,nav.P=kfupdate(nav.x,nav.P,H[0:nv,:],v[0:nv],R)
    return 0

def relpos(nav,obs,obsb):
    nf=nav.nf
    if gn.timediff(obs.t,obsb.t)!=0:
        return -1

    rs,vs,dts,svh=satposs(obs,nav)
    rsb,vsb,dtsb,svhb=satposs(obsb,nav)
    
    # non-differencial residual for base 
    yr,er,el=zdres(nav,obsb,rsb,dtsb,nav.rb)
    
    ns,iu,ir=selsat(nav,obs,obsb,el)
    
    y = np.zeros((ns*2,nf*2))
    e = np.zeros((ns*2,3))
    
    y[ns:,:]=yr[ir,:]
    e[ns:,]=er[ir,:]
    
    # Kalman filter time propagation
    udstate(nav,obs,obsb,iu,ir)
    
    xa=np.zeros(nav.nx)
    xp=nav.x.copy()

    # non-differencial residual for rover 
    yu,eu,el=zdres(nav,obs,rs,dts,xp[0:3])
    
    y[:ns,:]=yu[iu,:]
    e[:ns,:]=eu[iu,:]
    el = el[iu]
    sat=obs.sat[iu]
    # DD residual
    v,H,R=ddres(nav,xp,y,e,sat,el)
    Pp=nav.P.copy()
    
    # Kalman filter measurement update
    xp,Pp=kfupdate(xp,Pp,H,v,R)
    
    if True:
        # non-differencial residual for rover after measurement update
        yu,eu,elr=zdres(nav,obs,rs,dts,xp[0:3])
        y[:ns,:]=yu[iu,:]
        e[:ns,:]=eu[iu,:]
        # reisdual for float solution
        v,H,R=ddres(nav,xp,y,e,sat,el)
        if valpos(nav,v,R):
            nav.x=xp
            nav.P=Pp
    
    nb,xa=resamb_lambda(nav)
    if nb>0:
        yu,eu,elr=zdres(nav,obs,rs,dts,xa[0:3])
        y[:ns,:]=yu[iu,:]
        e[:ns,:]=eu[iu,:]
        v,H,R=ddres(nav,xa,y,e,sat,el)
        if valpos(nav,v,R):
            holdamb(nav,xa)
    
    return 0
    
    

            
if __name__ == '__main__':
    import matplotlib.pyplot as plt
    
    bdir='../data/'
    navfile=bdir+'SEPT078M.21P'
    obsfile=bdir+'SEPT078M.21O'
    basefile=bdir+'3034078M.21O'
        
    xyz_ref=[-3962108.673,   3381309.574,   3668678.638]
    pos_ref=gn.ecef2pos(xyz_ref)
    
    # rover
    dec = rn.rnxdec()
    nav = gn.Nav()
    dec.decode_nav(navfile,nav)
    
    # base
    decb=rn.rnxdec()
    decb.decode_obsh(basefile)
    dec.decode_obsh(obsfile)
 
    nep=60
    #nep=10
    # GSI 3034 fujisawa
    nav.rb=[-3959400.631,3385704.533,3667523.111]
    t=np.zeros(nep)
    enu=np.zeros((nep,3))
    if True:
        rtkinit(nav,dec.pos)
        rr=dec.pos  
        for ne in range(nep):
            obs=dec.decode_obs()
            obsb=decb.decode_obs()
            
            #sol,az,el=pntpos(obs,nav,rr)
            if ne==0:
                nav.x[0:3]=dec.pos # initial estimation
                t0=obs.t
            t[ne]=gn.timediff(obs.t,t0)
            relpos(nav,obs,obsb)
            sol=nav.x[0:3]
            enu[ne,:]=gn.ecef2enu(pos_ref,sol-xyz_ref)

        
        dec.fobs.close()
        decb.fobs.close()
    
    plt.plot(t,enu)
    plt.ylabel('pos err[m]')
    plt.xlabel('time[s]')
    plt.legend(['east','north','up'])
    plt.grid()
    plt.axis([0,ne,-0.1,0.1])    
    
    
    