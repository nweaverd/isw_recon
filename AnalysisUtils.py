#This file contains functions to be used for analyzing how various systematics
# affect our ability to reconstruct ISW maps from galaxy maps

import numpy as np
import healpy as hp
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import matplotlib
import itertools

from MapParams import * #Classes w info about map properties
from CosmParams import Cosmology #class w/info about cosm params P(k), etc
from ClRunUtils import * #classes which keep track of k, lvals, etc
from genCrossCor import * #classes which compute C_l for sets of maps
from genMapsfromCor import * #functions which gen g_lm and maps from C_l


#================================================
#-------------------------------------------------------------------------
# get_Dl_matrix
#  input: cldat -ClData instance
#         includelist- list of either tags, binmaps, or maptypes to include
#                in estimator construction. if none given, use all
#         zerotag- tag for map we want to construct an estimator for
#                if not in include list, will be added, will be kept index 0
#  output: D: NellxNxN matrix, where Nell=number of l values, N=number of maps
#       where indices go like [ell,maptype,maptype]
#-------------------------------------------------------------------------
def get_Dl_matrix(cldat,includelist=[],zerotag='isw_bin0'):
    if not includelist:
        includelist=cldat.bintaglist
    #print 'getting D, includelist=',includelist
    dtags=[] #tags for maps included in D_l
    dtags.append(zerotag)
    # get the list of tags set up, corresponding to row/col indices in D
    for x in includelist:
        if isinstance(x,str):
            if x in cldat.bintaglist:
                if x not in dtags: dtags.append(x)
            else:
                print x," not in C_l data; disregarding."
        elif isinstance(x,MapType): #this part has not been tested
            for b in x.bintags:
                if b in cldat.bintaglist:
                    if bintag not in dtags: dtags.append(b)
                else: print b," not in C_l data; disregarding."
        elif isinstance(x,BinMap):#this part has not been tested
            if x.tag in cldat.bintaglist:
                if x.tag not in dtags: dtags.append(x.tag)
            else: print x.tag," not in C_l data; disregarding."

    Nmap=len(dtags)
    #translate between map indices in D and in C
    clind=-1*np.ones(Nmap,int)
    for t in xrange(Nmap):
        clind[t]=cldat.tagdict[dtags[t]]

    #set up D matrix
    Nell=cldat.Nell
    D=np.zeros((Nell,Nmap,Nmap))
    for i in xrange(Nmap):
        for j in xrange(i,Nmap): #i<=j
            ci=clind[i] #mapind of i in cl basis
            cj=clind[j] #mapind of j in cl basis
            cxij = cldat.crossinds[ci,cj] #crossind of ij pair in clbasis
            D[:,i,j]=cldat.cl[cxij,:]
            if i!=j: D[:,j,i]=cldat.cl[cxij,:] #matrix is symmetric

    #print 'det(D)=',np.linalg.det(D)
    return D,dtags

#-------------------------------------------------------------------------
# invert_Dl: givem Dl matrix, with dim NellxNmapsxNmaps
#            invert each 2d D[lind,:,:] matrix
def invert_Dl(D):
    #Dinv=np.zeros_like(D)
    Nell=D.shape[0]
    Nmap=D.shape[1]
    Dinv=np.zeros((Nell,Nmap,Nmap))

    #check whether any map has all zeros in their column/row: 
    #   these are prolematic: will result in singular matrix
    zerorows=[[]]#for each ell, holds list of indices for rows that are all zero [lind][i]
    Dtoinvert=[np.array([])]
    for lind in xrange(1,Nell):
        zerorows.append([])
        #Dtoinvert.append([])
        tempD=D[lind,:,:]
        tempDind = 0 #if rows/cols deleted from D, keep track of index
        for i in xrange(Nmap):
            if np.all(D[lind,i,:]==0):
                zerorows[lind].append(i)
                tempD=np.delete(tempD,tempDind,0) #delete this row
                tempD=np.delete(tempD,tempDind,1) #delete this col
            else:
                tempDind+=1
        Dtoinvert.append(tempD)
    #print 'zerorows',zerorows

    #for each l, invert with all-zero-rows/cols removed
    #could also just use np.linalg.inv, but found a forum saying this is quicker
    identity=np.identity(Nmap,dtype=D.dtype)
    for l in xrange(1,Nell): #leave ell=0 as all zeros

        #print 'ELL=',l
        #print Dtoinvert[l]
        if identity.size!=Dtoinvert[l].size:
            identity=np.identity(Dtoinvert[l].shape[0])
        thisDinv=np.linalg.solve(Dtoinvert[l],identity) #just for this ell value
        #print thisDinv
        #put values into Dinv, skipping rows with indices in zerorows
        #  so: zerorows in D will also be zero in Dinv so they don't contribute
        #      to the ISW estimator
        tempi=0
        for i in xrange(Nmap):
            if i not in zerorows[l]:
                tempj=i
                for j in xrange(i,Nmap):
                    #print 'j=',j
                    if j not in zerorows[l]: 
                        Dinv[l,i,j]=thisDinv[tempi,tempj]
                        Dinv[l,j,i]=thisDinv[tempj,tempi]
                        tempj+=1
                tempi+=1
    return Dinv
            
#-------------------------------------------------------------------------
# get glm_array_forrec
# given glmData object, get glm for appropriate maps, get indices to match D
#   includelist is list of tuples of (map,mod,mask) to get
#     if len=1, mod+mask are defaults, if len=2, mask='fullsky'
# returns: outglm = array with dim [Nreal,len(includelist),Nlm]
# NOTE includelist should NOT contain map to be reconstructed 
#-------------------------------------------------------------------------
def get_glm_array_forrec(glmdat,includelist=[],zerotag='isw_bin0'):
    #print glmdat.maptaglist
    #loop through tags in includelist, check that they're in glmdat
    # and map between indices appropriately
    if not includelist: #if no includelist, use all unmod maps
        includelist=glmdat.maptaglist
        if zerotag in includelist:
            includelist.remove(zerotag)

    dinds=[]#d[n]=i: n=index for rec data glm, i = index in input
    # if type(zerotag)==str: #string, or just one entry; just maptag
    #     zerotagstr=zerotag
    #     zeroind=glmdat.get_mapind_fromtags(zerotag)
    # elif type(zerotag)==tuple:
    #     zerotagstr=zerotag[0]
    #     if len(zerotag)==1:
    #         zeroind=glmdat.get_mapind_fromtags(zerotag[0])
    #     elif len(zerotag)==2:
    #         zeroind=glmdat.get_mapind_fromtags(zerotag[0],zerotag[1])
    #     else:
    #         zeroind=glmdat.get_mapind_fromtags(zerotag[0],zerotag[1],zerotag[2])

    indexforD=0 #index of data glm to be used in rec
    for x in includelist:
        if type(x)==str:
            x=(x,'unmod','fullsky')
        elif type(x)==tuple:
            if len(x)==1:
                x=(x[0],'unmod','fullsky')
            elif len(x)==2:
                x=(x[0],x[1],'fullsky')
        xind=glmdat.get_mapind_fromtags(x[0],x[1],x[2])
        if xind not in dinds:
            dinds.append(xind)
            indexforD+=1
    #collect appropriate glm info
    outglm=np.zeros((glmdat.Nreal,len(dinds),glmdat.Nlm),dtype=np.complex)
    for d in xrange(len(dinds)):
        outglm[:,d,:]=glmdat.glm[:,dinds[d],:]
    return outglm,dinds

#-------------------------------------------------------------------------
# calc_isw_est -  given clData and glmData objects, plus list of maps to use
#        get the appropriate D matrix and construct isw estimator ala M&D
#        but with no CMB temperature info
# input:
#   cldat, glmdat - ClData and glmData objects containing maps
#                   to be used in reconstructing it (Cl must have isw too)
#   includeglm is list of tuples of (map,mod,mask) to use glm from
#     if len=1, mod+mask are defaults, if len=2, mask='fullsky'
#   includecl is list map tags (strings) for which we'll use Cl from 
#     for rec, if it is empty, use same set as in includeglm;
#     if not empty, must be the same length as includeglm
#     -> ISW tag will be added to front automatically
#   maptag - string which becomes part of maptag for output glmData
#            should describe simulated maps used for reconstruction
#   rectag - string which becomes modtag for output glmData
#   zerotag - string or tuple identifying map to be reconstructed
#             needs to be present in cldat, but not necessarily glmdat
#   writetofile- if True, writes glm to file with glmfiletag rectag_recnote
#   getmaps - if True, generates fits files of maps corresponding to glms
#   makeplots - if getmaps==makeplots==True, also generate png plot images
#   lmin_forrec - integer identifying the lowest ell value of to be used in 
#                 reconstruction. default is to neglect monopole and dipole
# output: 
#   iswrecglm - glmData object containing just ISW reconstructed
#                also saves to file
#-------------------------------------------------------------------------
def calc_isw_est(cldat,glmdat,includeglm=[],includecl=[],maptag='testmap',rectag='nonfid',zerotag='isw_bin0',lmin_forrec=2,writetofile=True,getmaps=True,makeplots=False,NSIDE=32):
    maptag='iswREC.'+maptag

    print "Computing ISW estimator maptag,rectag:",maptag,rectag

    if type(zerotag)==str: #string, or just one entry; just maptag
        zerotagstr=zerotag
    else:
        zerotagstr=zerotag[0]#if it is a tuple
    if not includeglm:
        includeglm=cldat.bintaglist
        #shouldn't have the map to be reconstructed in it
        includeglm.remove(zerotagstr)
    Nmap=len(includeglm)

    if not includecl: #if list of tags not given, maps from includeglm
        rectag='fid' 
        includecl.append(zerotagstr)
        for x in includeglm:
            if type(x)==str and x!=zerotag:# and x not in bintags:
                includecl.append(x)
            elif type(x)==tuple and x[0]!=zerotag:# and x[0] not in bintags:
                includecl.append(x[0])
    else: #if includecl is given, 
        if len(includecl)!=len(includeglm):
            print "WARNING: includeglm and includecl are not the same lenght!"
        includecl=[zerotagstr]+includecl #now len is +1 vs incglm
    
    #get D matrix dim Nellx(NLSS+1)x(NLSS+1) 
    #   where NLSS is number of LSS maps being used for rec, 
    #       where +1 is from ISW
    Dl,dtags=get_Dl_matrix(cldat,includecl,zerotagstr)
    Dinv=invert_Dl(Dl)
    #print 'Dinv',Dinv
    #get glmdata with right indices, dim realzxNLSSxNlm
    glmgrid,dinds=get_glm_array_forrec(glmdat,includeglm,zerotag)

    #compute estimator; will have same number of realizations as glmdat
    almest=np.zeros((glmgrid.shape[0],1,glmgrid.shape[2]),dtype=np.complex)
    ellvals,emmvals=glmdat.get_hp_landm()
    for lmind in xrange(glmdat.Nlm):
        ell=ellvals[lmind]
        if ell<lmin_forrec: 
            #print 'continuing since ell is too small'
            continue
        Nl=1./Dinv[ell,0,0]
        for i in xrange(0,len(dinds)): #loop through non-isw maps
            almest[:,0,lmind]-=Dinv[ell,0,i+1]*glmgrid[:,i,lmind]
            #print 'just added',-1*Dinv[ell,0,i]*glmgrid[:,i,lmind]
        almest[:,0,lmind]*=Nl

    outmaptags=[maptag]
    outmodtags=[rectag]
    outmasktags=['fullsky']
    almdat=glmData(almest,glmdat.lmax,outmaptags,glmdat.runtag,glmdat.rundir,rlzns=glmdat.rlzns,filetags=[maptag+'.'+rectag],modtaglist=outmodtags,masktaglist=outmasktags)

    if writetofile: #might set as false if we want to do several recons
        write_glm_to_files(almdat)
    if getmaps:
        get_maps_from_glm(almdat,redofits=True,makeplots=makeplots,NSIDE=NSIDE)

    return almdat
#-------------------------------------------------------------------------
# domany_isw_recs- run several sets of isw rec, bundle results into one output file
# input: #WORKING HERE, NEED TO TEST
#    list of cldata objects - if len=1, use same cl for all
#           otherwise should be same length as recinfo
#    list of glmdata objects - like list of cl for length
#    'recinfo' list: should provide for each rec
#        includeglm - list of tags or tuples describing input sim maps
#        includecl - list tags describing input rec cl
#        maptag - string describing input sim maps
#        rectag - string describing input rec cl
#    outfiletag, outruntag - to be used in output glm filename 
#       (runtag will also show up in maps made from glmdat)
#    writetofile - if True, writes output to file
#    getmaps - if True, get fits files for maps that go with recs
#    makeplots - if getmapes and True, also make png files
#    NSIDE - if maps are made, use this NSIDE value
#  Assumes all recs have same Nlm and Nreal
def domany_isw_recs(cldatlist,glmdatlist,reclist,outfiletag='iswREC',outruntag='',writetofile=True,getmaps=True,makeplots=False,NSIDE=32):
    SameCl=False
    Sameglm=False
    if len(cldatlist)==1:
        SameCl=True
    if len(glmdatlist)==1:
        Sameglm=True
    i=0

    for rec in reclist:
        includeglm=rec[0]
        includecl=rec[1]
        maptag=rec[2]
        rectag=rec[3]
        if SameCl:
            cldat=cldatlist[0]
        else:
            cldat=cldatlist[i]
        if Sameglm:
            glmdat=glmdatlist[0]
        else:
            glmdat=glmdatlist[i]
        almdat=calc_isw_est(cldat,glmdat,includeglm=includeglm,includecl=includecl,maptag=maptag,rectag=rectag,zerotag='isw_bin0',writetofile=False,getmaps=getmaps,makeplots=makeplots,NSIDE=NSIDE)
        if i==0:
            outalmdat=almdat
        else:
            outalmdat=outalmdat+almdat
        i+=1



    #assign consistent runtag and filetag
    outalmdat.filetag=[outfiletag]
    outalmdat.runtag=outruntag
    if writetofile:
        write_glm_to_files(outalmdat,setnewfiletag=True,newfiletag=outfiletag)

#-------------------------------------------------------------------------
# rho_mapcorr: compute rho (cross corr) between pixels of two maps
#   #input: two heapy map arrays with equal NSIDE
#   #output: rho = <map1*map2>/(variance(map1)*variance(map2))
#                 where <> means average over all pixels
def rho_onereal(map1,map2):
    if map1.size!=map2.size:
        print "Can't compute correlation between maps with different NSIDE.***"
        return 0
    product=map1*map2
    avgprod=np.mean(product)
    sig1=np.sqrt(np.var(map1))
    sig2=np.sqrt(np.var(map2))
    #print 'avgprod=',avgprod
    #print 'sig1=',sig1
    #print 'sig2=',sig2
    rho= avgprod/(sig1*sig2)
    #print 'rho=',rho
    return rho
#-------------------------------------------------------------------------
# rho_manyreal -  find correlations between pairs of maps for many realizations
#  input: mapdir -  directory where the maps are 
#        filebase1/2 - filename of maps, up to but not including '.rXXXXX.fits'
#        rlzns, Nreal - if rlzns is empty, rlzns=np.arange(Nreal), otherwise
#                       Nreal=rlzns.size
# NEED TO TEST
def rho_manyreal(mapdir,filebase1,filebase2,Nreal=1,rlzns=np.array([])):
    if rlzns.size:
        Nreal=rlzns.siz
    else:
        rlzns=np.arange(Nreal)
    rhovals=np.zeros(Nreal)
    #read in the maps
    for r in xrange(Nreal):
        f1=''.join([mapdir,filebase1,'.r{0:05d}.fits'.format(rlzns[r])])
        f2=''.join([mapdir,filebase2,'.r{0:05d}.fits'.format(rlzns[r])])
        map1=hp.read_map(f1,verbose=False)
        map2=hp.read_map(f2,verbose=False)
        #compute cross correlations and store the value
        rhovals[r]=rho_onereal(map1,map2)
    return rhovals

#------------------------------------------------------------------------------
# save_rhodat - save rho data to file
#   #should keep track of what maps went into this, probably do a row per realization

#------------------------------------------------------------------------------
#plot_Tin_Trec  - make scatter plot comparing true to reconstructed isw
def plot_Tin_Trec(iswmapfiles,recmapfiles,reclabels):
    colors=['#404040','#c51b8a','#0571b0','#66a61e','#ffa319','#d7191c']
    Nmap=len(recmapfiles)
    recmaps=[]
    iswmaps=[]
    for f in recmapfiles:
        mrec=hp.read_map(f)*1.e5
        recmaps.append(mrec)
    for f in iswmapfiles:
        misw=hp.read_map(f)*1.e5
        iswmaps.append(misw)
    rhovals=[rho_onereal(iswmaps[n],recmaps[n]) for n in xrange(Nmap)]
    print rhovals
    plt.figure(1,figsize=(10,8))
    plt.rcParams['axes.linewidth'] =2
    ax=plt.subplot()
    plt.xlabel(r'$\rm{T}^{\rm ISW}_{\rm input}$  $(10^{-5}\rm{K})$',fontsize=20)
    plt.ylabel(r'$\rm{T}^{\rm ISW}_{\rm rec}$  $(10^{-5}\rm{K})$',fontsize=20)
    #plt.ticklabel_format(style='sci', axis='both', scilimits=(1,0))
    ax.yaxis.set_major_formatter(mtick.FormatStrFormatter('%.0f'))
    ax.xaxis.set_major_formatter(mtick.FormatStrFormatter('%.0f'))
    ax.tick_params(axis='both', labelsize=18)
    ax.set_aspect('equal')#make it square

    xmax=np.max(np.fabs(iswmaps))
    plt.xlim(-1.0*xmax,1.8*xmax) 
    plt.ylim(-1.2*xmax,1.2*xmax)
    for i in xrange(len(recmaps)):
        rhoi=rhovals[i]
        coli=colors[i]
        labeli=reclabels[i]+'\n$\\rho={0:0.2f}$'.format(rhoi)
        mrec=recmaps[i]
        misw=iswmaps[i]
        plt.plot(misw,mrec,linestyle='None',marker='o',alpha=1,label=labeli,markersize=4.,color=coli,markeredgecolor='None')#markerfacecolor='None',markeredgecolor=coli
    plt.plot(10*np.array([-xmax,xmax]),10*np.array([-xmax,xmax]),linestyle='--',linewidth=4.,color='grey')

    #plt.subplots_adjust(right=.8)
    #plt.legend(loc='lower right',ncol=1,bbox_to_anchor=(1.,.5),numpoints=1,prop={'size':10})
    #leg=plt.legend(loc='lower right',ncol=1,numpoints=1,prop={'size':16},fancybox=True, framealpha=0.)
    #leg.draw_frame(False)
    # try doing text boxes instead of legends?
    startboxes=.7
    totlines=19
    fperline=1/25. #estimate by eye
    startheight=startboxes
    for i in range(Nmap)[::-1]:
        li=reclabels[i]+'\n$\\rho={0:0.3f}$'.format(rhovals[i])
        Nline=li.count('\n')+1
        leftside=.975#.69
        textbox=ax.text(leftside, startheight, li, transform=ax.transAxes, fontsize=15,verticalalignment='top', ha='right',multialignment      = 'left',bbox={'boxstyle':'round,pad=.3','alpha':1.,'facecolor':'none','edgecolor':colors[i],'linewidth':4})
        #bb=textbox.get_bbox_patch()
        #bb.set_edgewidth(4.)
        startheight-=Nline*fperline+.03
    
    #plt.show()
    plotdir='output/plots_forposter/'
    plotname='TrecTisw_scatter_variousRECs'
    print 'saving',plotdir+plotname
    plt.savefig(plotdir+plotname+'small.png',dpi=300)
    plt.savefig(plotdir+plotname+'.png',dpi=900)
    #plt.savefig(plotdir+plotname+'.svg', format='svg',dpi=1200)
