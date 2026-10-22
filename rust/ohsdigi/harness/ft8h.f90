! ohsdigi verification harness: runs WSJT-X 2.7.0's own FT8/FT4 routines
! (compiled from its source by build.sh) on a WAV and dumps what each
! stage produces, for compare.py to hold ohsdigi's Rust port against.
!
!   ft8h stages   <wav> <ndepth> <out>   sync8 candidates + sbase, then per
!                                         candidate ft8b's refined sync, LLRs,
!                                         isolated LDPC results and decode
!   ft8h subtract <wav> <list> <out.f32>  subtractft8 each "f0 dt refine
!                                         t1..t79" line in turn; residual
!   ft8h pack     <msgs> <out>            pack77 each line: 77 bits + text
!   ft8h ft4      <wav> <ndepth> <out>    WSJT-X's ft4_decode, with its
!                                         candidates, bit metrics and decodes
!
! GPL-3.0-or-later, like the WSJT-X code it links.

module ft4cb
  use ft4_decode
  type, extends(ft4_decoder) :: h4_decoder
  end type h4_decoder
contains
  subroutine ft4_cb(this,sync,snr,dt,freq,decoded,nap,qual)
    use hdump
    use packjt77
    class(ft4_decoder), intent(inout) :: this
    real, intent(in) :: sync
    integer, intent(in) :: snr
    real, intent(in) :: dt
    real, intent(in) :: freq
    character(len=37), intent(in) :: decoded
    integer, intent(in) :: nap
    real, intent(in) :: qual
    character*77 c77
    character*37 msg
    msg=decoded
    i3=-1
    n3=-1
    call pack77(msg,i3,n3,c77)
    write(hunit,'(a,i4,f6.2,f9.2,i3,f8.3,1x,a77,1x,a37)') 'FT4DEC ',snr,dt,freq,nap,sync,c77,decoded
  end subroutine ft4_cb
end module ft4cb

program ft8h
  use hdump
  use packjt77
  use ft4cb
  include 'ft8/ft8_params.f90'
  parameter (MAXCAND=600)
  character*256 mode,fwav,arg,fout,flist
  character*37 msg37,msgout
  character*77 c77
  character*12 mycall12,hiscall12
  character*512 line
  integer*2 iwave(NMAX)
  integer*2 iwave4(21*3456)
  real dd(NMAX)
  real sbase(NH1)
  real candidate(3,MAXCAND)
  integer itone(NN)
  integer apsym2(58),aph10(10)
  logical newdat,lrefine,unpk77_success
  type(h4_decoder) :: d4

  call getarg(1,mode)
  mycall12='            '
  hiscall12='            '

  if(mode.eq.'pack') then
     call getarg(2,flist)
     call getarg(3,fout)
     open(10,file=flist,status='old')
     open(hunit,file=fout,status='unknown')
     do
        read(10,'(a)',end=5) line
        msg37=line(1:37)
        i3=-1
        n3=-1
        call pack77(msg37,i3,n3,c77)
        call unpack77(c77,0,msgout,unpk77_success)
        write(hunit,'(a77,1x,a37)') c77,msgout
     enddo
5    close(10)
     close(hunit)
     stop
  endif

  call getarg(2,fwav)
  open(10,file=fwav,access='stream',status='old')
  iwave=0
  read(10,pos=45,end=1) iwave
1 close(10)

  if(mode.eq.'stages') then
     call getarg(3,arg)
     read(arg,*) ndepth
     call getarg(4,fout)
     open(hunit,file=fout,status='unknown')
     dd=iwave
     syncmin=1.3
     if(ndepth.le.2) syncmin=1.6
     maxc=MAXCAND
     call sync8(dd,NMAX,200,4000,syncmin,1500,maxc,candidate,ncand,sbase)
     write(hunit,'(a,i5)') 'NCAND ',ncand
     do i=1,ncand
        write(hunit,'(a,i5,3e16.8)') 'CAND ',i,candidate(1:3,i)
     enddo
     write(hunit,'(a,1920e16.8)') 'SBASE ',sbase
     call ft8apset(mycall12,hiscall12,0,apsym2,aph10)
     newdat=.true.
     hon=.true.
     do icand=1,ncand
        hcand=icand
        f1=candidate(1,icand)
        xdt=candidate(2,icand)
        xbase=10.0**(0.1*(sbase(nint(f1/3.125))-40.0))
        call ft8b(dd,newdat,0,1500,0,ndepth,50,.false.,.false.,75,.false., &
             .false.,0,iaptype,mycall12,hiscall12,f1,xdt,xbase,apsym2,aph10,   &
             nharderrors,dmin,nbadcrc,iappass,msg37,xsnr,itone)
        write(hunit,'(a,i5,i3,i4,f10.4,f10.3,2f12.5,1x,a37)') 'RES ',icand,nbadcrc, &
             nharderrors,dmin,xsnr,f1,xdt,msg37
     enddo
     close(hunit)
     stop
  endif

  if(mode.eq.'subtract') then
     call getarg(3,flist)
     call getarg(4,fout)
     dd=iwave
     open(11,file=flist,status='old')
     do
        read(11,*,end=7) f0,dt,nref,itone
        lrefine=nref.ne.0
        call subtractft8(dd,itone,f0,dt,lrefine)
     enddo
7    close(11)
     open(12,file=fout,access='stream',status='replace')
     write(12) dd
     close(12)
     stop
  endif

  if(mode.eq.'ft4') then
     call getarg(3,arg)
     read(arg,*) ndepth
     call getarg(4,fout)
     open(hunit,file=fout,status='unknown')
     open(10,file=fwav,access='stream',status='old')
     iwave4=0
     read(10,pos=45,end=2) iwave4
2    close(10)
     hon=.true.
     call d4%decode(ft4_cb,iwave4,0,1500,200,4000,ndepth,.false.,0,mycall12,hiscall12)
     close(hunit)
     stop
  endif

  print*,'unknown mode ',trim(mode)
end program ft8h
