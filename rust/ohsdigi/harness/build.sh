#!/bin/sh
# Build the verification harness `ft8h` from WSJT-X 2.7.0's own source.
#
#   harness/build.sh <workdir>
#
# Extracts the WSJT-X source from the tarball the shared source site holds for NB's Windows build
# (override with WSJTX_TGZ) into <workdir>, copies ft8b.f90 and
# ft4_decode.f90 with dump calls patched in (nothing else of WSJT-X is
# changed), and compiles with gfortran inside a throwaway container,
# because the development machine has no gfortran: the image is rust:1-bookworm plus
# gfortran, FFTW and Boost (Boost for WSJT-X's crc14.cpp, so the CRC is
# its own too). The binary lands at <workdir>/ft8h and runs in the same
# image (see compare.py, which does that for you).
set -eu
WORK=${1:?usage: build.sh <workdir>}
HERE=$(cd "$(dirname "$0")" && pwd)
TGZ=${WSJTX_TGZ:-/srv/source-site/files/wsjtx-2.7.0.tgz}
IMAGE=${HARNESS_IMAGE:-ohsdigi-harness:1}

mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
if [ ! -d "$WORK/wsjtx/lib" ]; then
    # The release tarball is a superbuild: the source is a tarball inside it.
    tar -xzf "$TGZ" -C "$WORK" wsjtx-2.7.0/src/wsjtx.tgz
    tar -xzf "$WORK/wsjtx-2.7.0/src/wsjtx.tgz" -C "$WORK"
    rm -rf "$WORK/wsjtx-2.7.0"
fi
if ! podman image exists "$IMAGE"; then
    printf 'FROM docker.io/library/rust:1-bookworm\nRUN apt-get update && apt-get install -y --no-install-recommends gfortran libfftw3-dev libboost-dev && rm -rf /var/lib/apt/lists/*\n' |
        podman build -t "$IMAGE" -f - "$WORK"
fi

B="$WORK/build"
rm -rf "$B"
mkdir -p "$B"
L="$WORK/wsjtx/lib"
cp "$HERE/hdump.f90" "$HERE/ft8h.f90" "$B/"

# ft8b: dump the refined sync and the four LLR sets once they exist, the
# sync bail-out, and each decode that passes unpack77.
sed -e 's/^  llrd=scalefac\*bmetd$/&\n  call hdump_llr(f1,xdt,ibest,delfbest,sync,nsync,llra,llrb,llrc,llrd)/' \
    -e 's/^  if(nsync .le. 6) then ! bail out$/&\n    call hdump_bail(f1,xdt,nsync)/' \
    -e 's/^     nbadcrc=0  ! If we get this far.*$/&\n     call hdump_dec(c77,ipass,nharderrors,dmin,iaptype)/' \
    "$L/ft8/ft8b.f90" > "$B/ft8b.f90"
# ft4_decode: candidates per subtraction pass, bit metrics per candidate.
sed -e 's/^ *call getcandidates4(dd,fa,fb,syncmin,nfqso,MAXCAND,savg,candidate,   &$/&/' \
    -e 's/^ *ncand,sbase)$/&\n         call h4_cands(candidate,ncand,isp)/' \
    -e 's/^ *call get_ft4_bitmetrics(cd,bitmetrics,badsync)$/&\n               call h4_bm(icand,iseg,f1,ibest,idfbest,smax,bitmetrics,badsync)/' \
    "$L/ft4_decode.f90" > "$B/ft4_decode.f90"
# ft8apset needs stdcall, which lives in a Q65 file with unrelated
# dependencies: take just that subroutine.
sed -n '/^subroutine stdcall/,/^end subroutine stdcall/p' "$L/qra/q65/q65_set_list.f90" > "$B/stdcall.f90"
for hook in hdump_llr hdump_bail hdump_dec; do
    grep -q "call $hook" "$B/ft8b.f90" || { echo "patch failed: $hook" >&2; exit 1; }
done
for hook in h4_cands h4_bm; do
    grep -q "call $hook" "$B/ft4_decode.f90" || { echo "patch failed: $hook" >&2; exit 1; }
done

cat > "$B/make.sh" <<'EOF'
set -eu
cd /w/build
L=/w/wsjtx/lib
FF="gfortran -O2 -fno-second-underscore -ffree-line-length-none -fallow-argument-mismatch -w -I$L -I$L/ft8 -I$L/ft4 -J."
g++ -O2 -c $L/crc14.cpp -o crc14.o
for f in $L/fftw3mod.f90 $L/timer_module.f90 $L/crc.f90 $L/packjt.f90 $L/77bit/packjt77.f90 hdump.f90; do
    $FF -c $f
done
SRC="$L/four2a.f90 $L/indexx.f90 $L/pctile.f90 $L/shell.f90 $L/polyfit.f90 $L/determ.f90
     $L/nuttal_window.f90 $L/platanh.f90 $L/peakup.f90 $L/ft2/gfsk_pulse.f90
     $L/fmtmsg.f90 $L/grid2deg.f90 $L/deg2grid.f90 $L/chkcall.f90 stdcall.f90
     $L/ft8/sync8.f90 $L/ft8/get_spectrum_baseline.f90 $L/ft8/baseline.f90
     $L/ft8/ft8_downsample.f90 $L/ft8/sync8d.f90 $L/ft8/twkfreq1.f90
     $L/ft8/decode174_91.f90 $L/ft8/osd174_91.f90 $L/ft8/encode174_91.f90
     $L/ft8/encode174_91_nocrc.f90 $L/ft8/get_crc14.f90 $L/ft8/genft8.f90
     $L/ft8/subtractft8.f90 $L/ft8/gen_ft8wave.f90 $L/ft8/ft8apset.f90 ft8b.f90
     $L/ft4/getcandidates4.f90 $L/ft4/ft4_baseline.f90 $L/ft4/ft4_downsample.f90
     $L/ft4/sync4d.f90 $L/ft4/get_ft4_bitmetrics.f90 $L/ft4/subtractft4.f90
     $L/ft4/gen_ft4wave.f90 $L/ft4/genft4.f90 ft4_decode.f90"
for f in $SRC; do $FF -c $f; done
$FF -c ft8h.f90
$FF -o ../ft8h *.o -lfftw3f -lfftw3f_threads -lstdc++
EOF
podman run --rm -v "$WORK:/w:Z" "$IMAGE" sh /w/build/make.sh
echo "built $WORK/ft8h"
