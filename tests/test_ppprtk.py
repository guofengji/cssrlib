# -*- coding: utf-8 -*-
"""
Created on Sun Aug 22 21:01:49 2021

@author: ruihi
"""

import matplotlib.pyplot as plt
import numpy as np
import cssrlib.gnss as gn
from cssrlib.cssrlib import cssr
from cssrlib.gnss import ecef2pos,Nav,time2gpst,timediff,uGNSS,sat2prn
from cssrlib.ppprtk import rtkinit,relpos
from cssrlib.rinex import rnxdec

bdir='./data/'
l6file=bdir+'2021078M.l6'
griddef=bdir+'clas_grid.def'
navfile=bdir+'SEPT078M.21P'
obsfile=bdir+'SEPT078M.21O'

# based on GSI F5 solution
xyz_ref=[-3962108.673,   3381309.574,   3668678.638]
pos_ref=ecef2pos(xyz_ref)

cs=cssr()
cs.monlevel=2
cs.week=2149
cs.read_griddef(griddef)

dec = rnxdec()
nav = Nav()
nav=dec.decode_nav(navfile,nav)
#nep=3600//30
nep=300
t=np.zeros(nep)
tc=np.zeros(nep)
enu=np.ones((nep,3))*np.nan
sol=np.zeros((nep,4))
dop=np.zeros((nep,4))
smode=np.zeros(nep,dtype=int)
if dec.decode_obsh(obsfile)>=0:
    rr=dec.pos
    rtkinit(nav,dec.pos)
    pos=ecef2pos(rr)
    inet=cs.find_grid_index(pos)
    
    fc=open(l6file,'rb')
    if not fc:
        print("L6 messsage file cannot open."); exit(-1)
    for ne in range(nep):
        obs=dec.decode_obs()
        week,tow=time2gpst(obs.t)
        
        cs.decode_l6msg(fc.read(250),0)
        if cs.fcnt==5: # end of sub-frame
            cs.week=week
            cs.decode_cssr(cs.buff,0)            

        if ne==0:
            t0=obs.t
            t0.time=t0.time//30*30
            cs.time=obs.t
            nav.time_p=t0
        t[ne]=timediff(obs.t,t0)
        tc[ne] = timediff(cs.time,t0)
        
        week,tow=time2gpst(obs.t)

        cstat=cs.chk_stat()
        
        if tow>=475413:
            tow

        if cstat or tow>=475220:        
            relpos(nav,obs,cs)
        
        sol=nav.x[0:3]
        enu[ne,:]=gn.ecef2enu(pos_ref,sol-xyz_ref)
        smode[ne]=nav.smode
        
    fc.close()
    dec.fobs.close()

fig_type=1
ylim=0.2

if fig_type==1:    
    plt.plot(t,enu,'.')
    plt.xticks(np.arange(0,nep+1, step=30))
    plt.ylabel('position error [m]')
    plt.xlabel('time[s]')
    plt.legend(['east','north','up'])
    plt.grid()
    plt.axis([0,ne,-ylim,ylim])    
elif fig_type==2:
    plt.plot(enu[:,0],enu[:,1],'.')
    plt.xlabel('easting [m]')
    plt.ylabel('northing [m]')
    plt.grid()
    plt.axis([-ylim,ylim,-ylim,ylim])   

plt.show()

if nav.fout is not None:
    nav.fout.close()