#!/bin/sh
# Build `js8gen` (JS8Call 2.2.0's genjs8 behind a stdin loop) and
# `varicodeh` (its message layer, likewise) from JS8Call's own source, for
# the references in tests/js8_golden.rs.
#
#   harness/js8/build.sh <js8call source dir> <workdir>
#
# <js8call source dir> is the unpacked js8call_2.2.0+ds.orig.tar.xz. The
# Fortran is compiled unchanged (genjs8, encode174 and its LDPC tables,
# crc.f90's binding, and packjt for genjs8's `use`), with JS8Call's own
# crc12.cpp for the CRC, in the same throwaway gfortran container as
# ../build.sh (image ohsdigi-harness:1, built there if missing). The binary
# lands at <workdir>/js8gen and runs in that image:
#
#   podman run --rm -i -v <workdir>:/w ohsdigi-harness:1 /w/js8gen < lines
#
# varicodeh is varicode.cpp, jsc*.cpp and decodedtext.cpp compiled
# unchanged against Qt 5 (image ohsdigi-harness-qt:1, the same plus
# qtbase5-dev, built if missing) and runs in that image the same way.
set -eu
SRC=$(cd "${1:?usage: build.sh <js8call dir> <workdir>}" && pwd)
WORK=${2:?usage: build.sh <js8call dir> <workdir>}
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=${HARNESS_IMAGE:-ohsdigi-harness:1}
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
if ! podman image exists "$IMAGE"; then
    printf 'FROM docker.io/library/rust:1-bookworm\nRUN apt-get update && apt-get install -y --no-install-recommends gfortran libfftw3-dev libboost-dev && rm -rf /var/lib/apt/lists/*\n' |
        podman build -t "$IMAGE" -f - "$WORK"
fi
B="$WORK/js8build"
rm -rf "$B"
mkdir -p "$B"
L="$SRC/lib"
cp "$HERE/js8gen.f90" "$L/crc.f90" "$L/packjt.f90" "$L/js8/genjs8.f90" "$L/ft8/encode174.f90" \
   "$L/ft8/ldpc_174_87_params.f90" "$L/js8/js8_params.f90" "$L/crc12.cpp" \
   "$L/deg2grid.f90" "$L/grid2deg.f90" "$L/fmtmsg.f90" "$L/pfx.f90" "$B/"
podman run --rm -v "$B:/b" -w /b "$IMAGE" sh -c '
  g++ -O2 -c crc12.cpp &&
  gfortran -O2 -fno-range-check -c crc.f90 packjt.f90 &&
  gfortran -O2 -fno-range-check -o js8gen js8gen.f90 genjs8.f90 encode174.f90 deg2grid.f90 grid2deg.f90 fmtmsg.f90 packjt.o crc.o crc12.o -lstdc++'
mv "$B/js8gen" "$WORK/js8gen"
QIMAGE=${HARNESS_QT_IMAGE:-ohsdigi-harness-qt:1}
if ! podman image exists "$QIMAGE"; then
    printf 'FROM %s\nRUN apt-get update && apt-get install -y --no-install-recommends qtbase5-dev && rm -rf /var/lib/apt/lists/*\n' "$IMAGE" |
        podman build -t "$QIMAGE" -f - "$WORK"
fi
cp "$HERE/varicodeh.cpp" "$SRC"/varicode.cpp "$SRC"/varicode.h "$SRC"/jsc.cpp "$SRC"/jsc.h "$SRC"/jsc_map.cpp \
   "$SRC"/jsc_list.cpp "$SRC"/decodedtext.cpp "$SRC"/decodedtext.h "$SRC"/crc.h "$B/"
podman run --rm -v "$B:/b" -w /b "$QIMAGE" sh -c '
  moc varicode.h -o moc_varicode.cpp &&
  g++ -O1 -fPIC -std=c++14 -Dfortran_charlen_t=size_t -I. $(pkg-config --cflags Qt5Core) -o varicodeh varicodeh.cpp varicode.cpp jsc.cpp \
      jsc_map.cpp jsc_list.cpp decodedtext.cpp moc_varicode.cpp $(pkg-config --libs Qt5Core)'
mv "$B/varicodeh" "$WORK/varicodeh"
echo "$WORK/js8gen $WORK/varicodeh"
