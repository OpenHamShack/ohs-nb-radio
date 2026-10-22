! js8gen: JS8Call 2.2.0's own JS8 encoder (genjs8), driven from stdin, so
! ohsdigi's tones can be compared with it bit for bit (tests/js8_golden.rs).
!
! Each input line is "<icos> <i3bit> <frame>": icos 1 for Normal's Costas
! arrays, 2 for the other speeds; i3bit 0..7; frame 12 characters. Each
! output line is the frame, i3bit, icos and the 79 tones as digits.
program js8gen
  character*22 msg, msgsent
  character*6 mygrid
  character*200 line
  integer*1 msgbits(87)
  integer itone(79), icos, i3bit, ios
  logical bcontest
  mygrid = '      '
  bcontest = .false.
  do
     read(*, '(a)', iostat=ios) line
     if (ios /= 0) exit
     if (len_trim(line) == 0) cycle
     read(line, *) icos, i3bit
     msg = adjustl(line(index(line, ' ', back=.true.)+1:))
     msg = '                      '
     msg(1:12) = line(len_trim(line)-11:len_trim(line))
     call genjs8(msg, icos, mygrid, bcontest, i3bit, msgsent, msgbits, itone)
     write(*, '(a12,1x,i1,1x,i1,1x,79i1)') msg(1:12), i3bit, icos, itone
  end do
end program js8gen
