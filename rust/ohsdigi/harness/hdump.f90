! Dump hooks for the ohsdigi verification harness. build.sh patches calls to
! these into a copy of WSJT-X's own ft8b.f90 (and nothing else), so the
! numbers dumped are WSJT-X's, computed by its code.

module hdump
  integer :: hunit = 61
  logical :: hon = .false.
  integer :: hcand = 0
end module hdump

subroutine hdump_bail(f1,xdt,nsync)
  use hdump
  if(.not.hon) return
  write(hunit,'(a,i5,2f12.5,i4)') 'BAIL ',hcand,f1,xdt,nsync
end subroutine hdump_bail

subroutine hdump_llr(f1,xdt,ibest,delfbest,sync,nsync,llra,llrb,llrc,llrd)
  use hdump
  real llra(174),llrb(174),llrc(174),llrd(174),llrz(174)
  integer*1 apmask(174),message91(91),cw(174)
  integer maxosds(3)
  data maxosds/-1,0,2/
  if(.not.hon) return
  write(hunit,'(a,i5,2f12.5,i6,f8.3,e16.8,i4)') 'MET ',hcand,f1,xdt,ibest,delfbest,sync,nsync
  write(hunit,'(a,174e16.8)') 'LLRA ',llra
  write(hunit,'(a,174e16.8)') 'LLRB ',llrb
  write(hunit,'(a,174e16.8)') 'LLRC ',llrc
  write(hunit,'(a,174e16.8)') 'LLRD ',llrd
! The LDPC stage on its own: each LLR set through decode174_91 at the
! three settings ft8b uses (BP only; BP + OSD on the channel LLRs; BP + OSD
! on two BP outputs), with no AP. ohsdigi feeds these same LLRs to its own
! decoder and must get the same answers.
  apmask=0
  do iset=1,4
     if(iset.eq.1) llrz=llra
     if(iset.eq.2) llrz=llrb
     if(iset.eq.3) llrz=llrc
     if(iset.eq.4) llrz=llrd
     do im=1,3
        message91=0
        cw=0
        dmin=0.
        call decode174_91(llrz,91,maxosds(im),2,apmask,message91,cw,ntype,nharderror,dmin)
        if(nharderror.lt.0) message91=0
        write(hunit,'(a,i2,i3,i4,i3,f12.5,1x,91i1)') 'LDPC ',iset,maxosds(im),nharderror,ntype,dmin,message91
     enddo
  enddo
end subroutine hdump_llr

subroutine hdump_dec(c77,ipass,nharderrors,dmin,iaptype)
  use hdump
  character*77 c77
  if(.not.hon) return
  write(hunit,'(a,i5,i3,i4,f12.5,i3,1x,a77)') 'DEC ',hcand,ipass,nharderrors,dmin,iaptype,c77
end subroutine hdump_dec

subroutine h4_cands(candidate,ncand,isp)
  use hdump
  real candidate(2,100)
  if(.not.hon) return
  write(hunit,'(a,i3,i5)') 'FT4NCAND ',isp,ncand
  do i=1,ncand
     write(hunit,'(a,i5,2e16.8)') 'FT4CAND ',i,candidate(1:2,i)
  enddo
end subroutine h4_cands

subroutine h4_bm(icand,iseg,f1,ibest,idfbest,smax,bitmetrics,badsync)
  use hdump
  real bitmetrics(206,3)
  logical badsync
  if(.not.hon) return
  write(hunit,'(a,i5,i3,f12.5,i6,i4,e16.8,l2)') 'FT4BM ',icand,iseg,f1,ibest,idfbest,smax,badsync
  if(badsync) return
  write(hunit,'(a,618e16.8)') 'FT4BITS ',bitmetrics
end subroutine h4_bm
