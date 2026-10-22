#!/bin/sh
# Build `hsh` and `hsh_ams`, the HSmodem verification harness, from
# AMSAT-DL's own HSmodem source (docs/hsmodem-research.md).
#
#   harness/hsmodem/build.sh <workdir>
#
# Fetches github.com/amsat-dl/QO-100-Modem at the commit below (the tree
# the multimedia beacon is built from: its Makefile_ams builds the beacon)
# into <workdir>, unless it is already there, and compiles HSmodem's own
# frame_packer, constellation, scrambler, crc16, fec, symboltracker and
# liquid_if files - unchanged - with hsh.cpp, inside a throwaway
# rust:1-bookworm container with g++ and FFTW added. They link against the
# liquid-dsp the tree ships prebuilt (hsmodem/SharedLibs/x86_64/libliquid.so,
# version string "1.3.2"), so the DSP is the binary HSmodem users run, not
# a liquid-dsp we built. `hsh_ams` is the same with -DAMS_TESTMODE, the
# beacon's build: modulator() hands each symbol to ams_testTX() instead of
# filtering it to audio. Both binaries land in <workdir> and run in the
# same image (compare.py does that).
set -eu
WORK=${1:?usage: build.sh <workdir>}
HERE=$(cd "$(dirname "$0")" && pwd)
COMMIT=cbd30059c18607654c1530b7606c18e375b7f74c
IMAGE=${HSH_IMAGE:-ohsdigi-hsh:1}

mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
if [ ! -f "$WORK/QO-100-Modem/hsmodem/frame_packer.cpp" ]; then
    curl -fsSL "https://codeload.github.com/amsat-dl/QO-100-Modem/tar.gz/$COMMIT" -o "$WORK/qo100modem.tgz"
    mkdir -p "$WORK/QO-100-Modem"
    tar -xzf "$WORK/qo100modem.tgz" -C "$WORK/QO-100-Modem" --strip-components=1
fi
if ! podman image exists "$IMAGE"; then
    printf 'FROM docker.io/library/rust:1-bookworm\nRUN apt-get update && apt-get install -y --no-install-recommends g++ libfftw3-dev && rm -rf /var/lib/apt/lists/*\n' |
        podman build -t "$IMAGE" -f - "$WORK"
fi
mkdir -p "$WORK/build"
cp "$HERE/hsh.cpp" "$WORK/build/"
cat > "$WORK/build/make.sh" <<'EOF'
set -eu
cd /w/build
H=/w/QO-100-Modem/hsmodem
CXX="g++ -O2 -std=c++11 -w -I$H"
for f in frame_packer constellation scrambler crc16 fec symboltracker; do $CXX -c $H/$f.cpp -o $f.o; done
$CXX -c $H/liquid_if.cpp -o liquid_if.o
$CXX -DAMS_TESTMODE -c $H/liquid_if.cpp -o liquid_if_ams.o
$CXX -c hsh.cpp -o hsh.o
$CXX -DAMS_TESTMODE -c hsh.cpp -o hsh_ams.o
cp $H/SharedLibs/x86_64/libliquid.so /w/libliquid.so
COMMON="frame_packer.o constellation.o scrambler.o crc16.o fec.o symboltracker.o"
g++ -o /w/hsh hsh.o liquid_if.o $COMMON -L/w -lliquid -lfftw3f -lm -Wl,-rpath,'$ORIGIN'
g++ -o /w/hsh_ams hsh_ams.o liquid_if_ams.o $COMMON -L/w -lliquid -lfftw3f -lm -Wl,-rpath,'$ORIGIN'
EOF
podman run --rm -v "$WORK:/w:Z" "$IMAGE" sh /w/build/make.sh
echo "built $WORK/hsh and $WORK/hsh_ams"
