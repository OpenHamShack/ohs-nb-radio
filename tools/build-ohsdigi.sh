#!/usr/bin/env bash
# Build ohsdigi, the Rust extension module FT8/FT4 encode with
# (rust/ohsdigi; docs/digimodes-rust.md), for the platforms we ship.
#
#   tools/build-ohsdigi.sh [--host] [--install] [--out DIR] [TARGET...]
#
# TARGET is linux-amd64, linux-arm64 or windows-amd64 (all three when none
# is named). Each lands in <out>/<target>/ - ohsdigi.abi3.so on Linux,
# ohsdigi.pyd on Windows - with a SHA256SUMS beside them. <out> defaults to
# rust/dist/ (not tracked: binaries are never committed; they are made from
# the tree, here, at release time).
#
# By default the build runs in a container (rust/build.Containerfile):
# Debian bookworm, so the Linux binaries need nothing newer than the
# oldest system we ship to (Pi OS bookworm, glibc 2.36), and a Rust
# toolchain pinned by image digest. With the lockfile, fixed paths inside
# the container and the release profile's single codegen unit, the same
# commit builds the same bytes; SHA256SUMS lets that be checked.
#
# --host builds linux-amd64 with the host's own cargo instead (quicker, for
# development; the result needs the host's glibc). --install then copies
# the linux-amd64 module into ohscore/, where a run from the source tree
# imports it (ohscore/ohsdigi.abi3.so, ignored by git).
#
# All cargo output goes to rust/target (one target dir for everything, so a
# build never leaves a copy of the dependency tree elsewhere on the disk);
# `cargo clean` there, or delete it, when done.
set -euo pipefail

here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)
rust="$here/rust"
out="$rust/dist"
host=0
install=0
targets=()
while (($#)); do
    case $1 in
        --host) host=1 ;;
        --install) install=1 ;;
        --out) out=$(readlink -f "$2"); shift ;;
        linux-amd64|linux-arm64|windows-amd64) targets+=("$1") ;;
        *) echo "usage: $0 [--host] [--install] [--out DIR] [linux-amd64|linux-arm64|windows-amd64]..." >&2; exit 2 ;;
    esac
    shift
done
if ((!${#targets[@]})); then
    if ((host)); then targets=(linux-amd64); else targets=(linux-amd64 linux-arm64 windows-amd64); fi
fi
if ((host)); then
    for t in "${targets[@]}"; do
        [[ $t == linux-amd64 ]] || { echo "--host builds linux-amd64 only" >&2; exit 2; }
    done
fi

triple() {
    case $1 in
        linux-amd64) echo x86_64-unknown-linux-gnu ;;
        linux-arm64) echo aarch64-unknown-linux-gnu ;;
        windows-amd64) echo x86_64-pc-windows-gnu ;;
    esac
}

# The module's file name: PyInit_ohsdigi is found in ohsdigi.<suffix>, and
# ".abi3.so" is the suffix every CPython 3.x on Linux accepts for a
# stable-ABI module; Windows accepts plain ".pyd".
artefact() {
    case $1 in
        windows-amd64) echo "ohsdigi.dll ohsdigi.pyd" ;;
        *) echo "libohsdigi.so ohsdigi.abi3.so" ;;
    esac
}

# PYO3_NO_PYTHON: an abi3 build needs no interpreter to configure it, and
# not asking one keeps the build from depending on whichever Python the
# build machine has. PYO3_BUILD_EXTENSION_MODULE: do not link libpython (an
# extension module finds the interpreter's symbols at load time).
common_env=(PYO3_NO_PYTHON=1 PYO3_BUILD_EXTENSION_MODULE=1 CARGO_TARGET_DIR=/src/target)
# Paths baked into the binary (panic messages) name the source as /src and
# the crates as /cargo, wherever they really were.
rustflags="--remap-path-prefix=/usr/local/cargo/registry=/cargo"

# -2: the image gained maturin for the wheels (tools/build-wheels.sh).
IMAGE=localhost/ohsdigi-build:1.98.1-2

build_container() {
    local t=$1 tr
    tr=$(triple "$t")
    if ! podman image exists "$IMAGE"; then
        echo "== building $IMAGE (once)"
        podman build -t "$IMAGE" -f "$rust/build.Containerfile" "$rust"
    fi
    echo "== $t ($tr) in $IMAGE"
    # The crate registry persists in a named volume, so a rebuild does not
    # download the dependencies again.
    podman run --rm -v "$rust:/src" -v ohsdigi-cargo-registry:/usr/local/cargo/registry -w /src/ohsdigi \
        "${common_env[@]/#/--env=}" -e RUSTFLAGS="$rustflags" -e SOURCE_DATE_EPOCH=0 \
        "$IMAGE" cargo build --release --locked --features python --target "$tr"
}

build_host() {
    local tr
    tr=$(triple linux-amd64)
    echo "== linux-amd64 ($tr) with the host's cargo"
    local cargo=${CARGO:-$(command -v cargo || echo "$HOME/.cargo/bin/cargo")}
    (cd "$rust/ohsdigi" && env PYO3_NO_PYTHON=1 PYO3_BUILD_EXTENSION_MODULE=1 CARGO_TARGET_DIR="$rust/target" \
        RUSTFLAGS="--remap-path-prefix=$rust=/src --remap-path-prefix=$HOME/.cargo/registry=/cargo" \
        "$cargo" build --release --locked --features python --target "$tr")
}

for t in "${targets[@]}"; do
    if ((host)); then build_host; else build_container "$t"; fi
    read -r from to <<<"$(artefact "$t")"
    # A host build is not a release build (the host's glibc, the host's
    # toolchain): it goes to a folder of its own so it can never be
    # packaged by mistake.
    d="$out/$t"
    ((host)) && d="$out/$t-host"
    mkdir -p "$d"
    cp "$rust/target/$(triple "$t")/release/$from" "$d/$to"
    (cd "$d" && sha256sum "$to" > SHA256SUMS)
    echo "built $d/$to ($(stat -c %s "$d/$to") bytes)"
done

# The Linux amd64 module must load in bookworm's Python 3.11 - the oldest
# the abi3 build promises - and encode FT8 and FT4 there exactly as WSJT-X
# does; checked in the build container, which has that Python.
if [[ " ${targets[*]} " == *" linux-amd64 "* ]] && ((!host)); then
    podman run --rm -v "$out/linux-amd64:/m:ro" "$IMAGE" python3 -c '
import sys; sys.path.insert(0, "/m")
import ohsdigi
e = ohsdigi.encode("ft8", "CQ G4XYZ IO91")
assert bytes(e.tones) == bytes(int(c) for c in "3140652000000001005530366107405420673140652245646370472303643735537714373140652"), e.tones
e = ohsdigi.encode("ft4", "CQ G4XYZ IO91")
assert len(e.waveform()) == 105 * 576 * 4
print("   loads and encodes in Python", sys.version.split()[0])'
fi

if ((install)); then
    src="$out/linux-amd64"
    ((host)) && src="$out/linux-amd64-host"
    cp "$src/ohsdigi.abi3.so" "$here/ohscore/ohsdigi.abi3.so"
    echo "installed $here/ohscore/ohsdigi.abi3.so"
fi
