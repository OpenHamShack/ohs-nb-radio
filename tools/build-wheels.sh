#!/usr/bin/env bash
# Build the ohs-ohsdigi wheels - ohsdigi (rust/ohsdigi) packaged for pip, the
# one FT8/FT4 decoder every OpenHamShack app installs (docs/OHSDIGI-PYTHON.md).
#
#   tools/build-wheels.sh [--no-test] [TARGET...]
#
# TARGET is linux-amd64, linux-arm64, windows-amd64 or macos (all four when
# none is named). Wheels land in rust/dist/wheels/ with a SHA256SUMS over
# every wheel there. One wheel per platform: the module is abi3-py311, so
# it serves CPython 3.11 and every later one.
#
# - Linux and Windows build in the same bookworm container as the bare
#   module (rust/build.Containerfile, which carries a pinned maturin), with
#   the same paths, toolchain and flags as tools/build-ohsdigi.sh. Linux
#   wheels are tagged manylinux_2_35: maturin checks the symbols the module
#   actually uses, and glibc 2.35 is the newest it needs (Ubuntu 22.04, and
#   every system built on Debian 12 / Pi OS bookworm or later). An older tag
#   would need a zig or manylinux-image build; nothing we ship to needs it.
#   Windows is cross-built with mingw, as the bare .pyd is.
# - macOS builds natively on the Mac mini (`ssh mac`) as one universal2
#   wheel (arm64 + x86_64), with a pinned rustup and maturin of its own
#   under /Volumes/OpenHamShackBuild/ohs-ohsdigi-wheel - nothing in the Mac's
#   home, no brew, no sudo. The tree is sent as a tarball of the working
#   copy (tracked files plus uncommitted edits), so what is built is what
#   is here, and the wheel is copied back.
#
# Each wheel built is then installed into a fresh venv and round-tripped
# (tests/test_ohsdigi_wheel.py) where it can run: linux-amd64 in the build
# container's Python 3.11 (the oldest the wheel promises) and in this
# host's Python, macos in the Mac's Python 3.13 (arm64, and x86_64 under
# Rosetta 2).
# linux-arm64 and windows-amd64 are built but not run here. --no-test
# skips the round trips.
#
# The bare modules for the NB/HAM bundles are still tools/build-ohsdigi.sh;
# this script does not touch rust/dist/<target>/.
set -euo pipefail

here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)
rust="$here/rust"
out="$rust/dist/wheels"
test=1
mac_local=0
targets=()
while (($#)); do
    case $1 in
        --no-test) test=0 ;;
        --mac-local) mac_local=1 ;;   # internal: the half that runs on the Mac
        linux-amd64|linux-arm64|windows-amd64|macos) targets+=("$1") ;;
        *) echo "usage: $0 [--no-test] [linux-amd64|linux-arm64|windows-amd64|macos]..." >&2; exit 2 ;;
    esac
    shift
done
((${#targets[@]})) || targets=(linux-amd64 linux-arm64 windows-amd64 macos)

# Zip entries carry this time (1980-01-01, the earliest a zip can say), so
# the same commit makes the same wheel bytes.
EPOCH=315532800
MATURIN_VERSION=1.15.0           # as rust/ohsdigi/wheel-requirements.txt

# ------------------------------------------------------------ on the Mac
# Run from the tarball the Linux side unpacked, in $MACWORK/src.
if ((mac_local)); then
    MACWORK=$(cd "$here/.." && pwd)
    TOOLS=$MACWORK/tools CACHE=$MACWORK/cache
    mkdir -p "$TOOLS" "$CACHE"
    RUST_TOOLCHAIN=1.98.1        # as rust/build.Containerfile
    # The same pins as tools/build-macos.sh.
    RUSTUP=(rustup-init-1.29.1 ec1b9233e7f72990ecd8e62063fa7f6c3dfc2bec8e97f88bff165f9100ac696a
            https://static.rust-lang.org/rustup/archive/1.29.1/aarch64-apple-darwin/rustup-init)
    PYSA=(cpython-3.13.16+20261003-aarch64-apple-darwin-install_only.tar.gz
          d8975d7df4f08f7b1c7aafcdfacbddcec3d366415f2c1a72b2466b6850815933
          https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.13.16%2B20261003-aarch64-apple-darwin-install_only.tar.gz)
    # The x86_64 build of the same Python (sha256 from the release's
    # SHA256SUMS), run under Rosetta 2 to test the wheel's other half.
    PYSA_X86=(cpython-3.13.16+20261003-x86_64-apple-darwin-install_only.tar.gz
              8e9cb087305bfb8969f68a905f79f41469d4aa5220c1aa71ada7fc9953bdba0f
              https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.13.16%2B20261003-x86_64-apple-darwin-install_only.tar.gz)
    fetch() {   # fetch FILE SHA URL -> prints the cached path
        local dest=$CACHE/$1
        if [[ ! -f $dest ]] || [[ $(shasum -a 256 "$dest" | cut -d' ' -f1) != "$2" ]]; then
            curl -fsSL -o "$dest.part" "$3"
            [[ $(shasum -a 256 "$dest.part" | cut -d' ' -f1) == "$2" ]] || { echo "bad sha256: $3" >&2; exit 1; }
            mv "$dest.part" "$dest"
        fi
        echo "$dest"
    }
    export RUSTUP_HOME=$TOOLS/rustup CARGO_HOME=$TOOLS/cargo
    if [[ ! -x $CARGO_HOME/bin/cargo ]]; then
        r=$(fetch "${RUSTUP[@]}"); chmod +x "$r"
        "$r" -y -q --no-modify-path --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
    fi
    "$CARGO_HOME/bin/rustup" target add --toolchain "$RUST_TOOLCHAIN" aarch64-apple-darwin x86_64-apple-darwin >/dev/null
    PYHOME=$TOOLS/python-3.13.16
    if [[ ! -x $PYHOME/bin/python3.13 ]]; then
        mkdir -p "$PYHOME" && tar -xzf "$(fetch "${PYSA[@]}")" -C "$PYHOME" --strip-components 1
    fi
    if [[ ! -x $TOOLS/maturin-$MATURIN_VERSION/bin/maturin ]]; then
        "$PYHOME/bin/python3.13" -m venv "$TOOLS/maturin-$MATURIN_VERSION"
        "$TOOLS/maturin-$MATURIN_VERSION/bin/pip" install -q --disable-pip-version-check --require-hashes \
            --only-binary=:all: -r "$rust/ohsdigi/wheel-requirements.txt"
    fi
    rm -rf "$out"; mkdir -p "$out"
    # 11.0: the first macOS on Apple silicon, and so the oldest a universal2
    # wheel can promise for both halves. maturin links the module with
    # -undefined dynamic_lookup itself (tools/build-macos.sh, which drives
    # cargo directly, has to say so).
    (cd "$rust/ohsdigi" && env PATH="$CARGO_HOME/bin:$PATH" RUSTUP_TOOLCHAIN=$RUST_TOOLCHAIN \
        MACOSX_DEPLOYMENT_TARGET=11.0 PYO3_NO_PYTHON=1 PYO3_BUILD_EXTENSION_MODULE=1 \
        CARGO_TARGET_DIR="$MACWORK/target" SOURCE_DATE_EPOCH=$EPOCH \
        RUSTFLAGS="--remap-path-prefix=$rust=/src --remap-path-prefix=$CARGO_HOME/registry=/cargo" \
        "$TOOLS/maturin-$MATURIN_VERSION/bin/maturin" build --release --target universal2-apple-darwin --out "$out")
    if ((test)); then
        echo "== macos wheel round trip, arm64"
        (cd "$here" && OHSDIGI_WHEEL_WORK=$MACWORK/test "$PYHOME/bin/python3.13" -m unittest discover -s tests -p test_ohsdigi_wheel.py)
        # A universal2 wheel whose x86_64 half was never loaded is half
        # tested; Rosetta runs it here (an Intel Mac would load that half).
        if arch -x86_64 /usr/bin/true 2>/dev/null; then
            PYX=$TOOLS/python-3.13.16-x86_64
            if [[ ! -x $PYX/bin/python3.13 ]]; then
                mkdir -p "$PYX" && tar -xzf "$(fetch "${PYSA_X86[@]}")" -C "$PYX" --strip-components 1
            fi
            echo "== macos wheel round trip, x86_64 (Rosetta 2)"
            (cd "$here" && OHSDIGI_WHEEL_WORK=$MACWORK/test arch -x86_64 "$PYX/bin/python3.13" -m unittest discover -s tests -p test_ohsdigi_wheel.py)
        else
            echo "   (no Rosetta 2 here: the x86_64 half is not tested)"
        fi
    fi
    exit 0
fi

# ------------------------------------------------------------ Linux side
IMAGE=localhost/ohsdigi-build:1.98.1-2   # as tools/build-ohsdigi.sh
if [[ " ${targets[*]} " != " macos " ]] && ! podman image exists "$IMAGE"; then
    echo "== building $IMAGE (once)"
    podman build -t "$IMAGE" -f "$rust/build.Containerfile" "$rust"
fi
mkdir -p "$out"

# The crate is mounted at /src as tools/build-ohsdigi.sh mounts it, so the
# module inside each wheel is built from the same paths with the same
# flags; the repository's LICENSE (rust/ohsdigi/LICENSE links to it, and
# the wheel's metadata carries it) is mounted where that link points.
container() {
    podman run --rm -v "$rust:/src" -v "$here/LICENSE:/LICENSE:ro" \
        -v ohsdigi-cargo-registry:/usr/local/cargo/registry -w /src/ohsdigi \
        -e PYO3_NO_PYTHON=1 -e PYO3_BUILD_EXTENSION_MODULE=1 -e CARGO_TARGET_DIR=/src/target \
        -e RUSTFLAGS="--remap-path-prefix=/usr/local/cargo/registry=/cargo" -e SOURCE_DATE_EPOCH=$EPOCH \
        "$IMAGE" "$@"
}

# One target's wheel into $out, replacing an older build of the same
# platform (a stale wheel beside a new one would be packaged by whoever
# globs the folder).
build_in_container() {
    local t=$1 args=()
    case $t in
        linux-amd64) args=(--target x86_64-unknown-linux-gnu --compatibility manylinux_2_35); rm -f "$out"/*_x86_64.whl ;;
        linux-arm64) args=(--target aarch64-unknown-linux-gnu --compatibility manylinux_2_35); rm -f "$out"/*_aarch64.whl ;;
        windows-amd64) args=(--target x86_64-pc-windows-gnu); rm -f "$out"/*-win_amd64.whl ;;
    esac
    echo "== $t wheel in $IMAGE"
    container /opt/maturin/bin/maturin build --release "${args[@]}" --out /src/dist/wheels
}

build_on_mac() {
    local w=/Volumes/OpenHamShackBuild/ohs-ohsdigi-wheel
    echo "== macos wheel on the Mac mini"
    ssh mac "test -d /Volumes/OpenHamShackBuild" || { echo "/Volumes/OpenHamShackBuild is not mounted on the Mac" >&2; exit 1; }
    # The working copy as it stands: tracked and new files (not ignored),
    # deleted ones left out, symlinks kept.
    (cd "$here" && git ls-files -z -co --exclude-standard -- LICENSE rust/ohsdigi tests tools/build-wheels.sh \
        | xargs -0 sh -c 'for f; do [ -e "$f" ] || [ -L "$f" ] && printf "%s\0" "$f"; done' sh \
        | tar --null -T - -czf - ) \
        | ssh mac "rm -rf $w/src && mkdir -p $w/src && tar -xzf - -C $w/src && bash $w/src/tools/build-wheels.sh --mac-local $( ((test)) || echo --no-test)"
    rm -f "$out"/*-macosx_*.whl
    scp -q "mac:$w/src/rust/dist/wheels/*.whl" "$out/"
}

for t in "${targets[@]}"; do
    case $t in
        macos) build_on_mac ;;
        *) build_in_container "$t" ;;
    esac
done

if ((test)) && [[ " ${targets[*]} " == *" linux-amd64 "* ]]; then
    echo "== linux-amd64 wheel round trip, Python 3.11 (the build container)"
    podman run --rm -v "$here:/repo:ro" -v "$HOME/build:/work" -e OHSDIGI_WHEEL_WORK=/work/ohsdigi-wheel-test -w /repo \
        "$IMAGE" python3 -m unittest discover -s tests -p test_ohsdigi_wheel.py
    echo "== linux-amd64 wheel round trip, Python $(python3 -c 'import sys; print(sys.version.split()[0])') (this host)"
    (cd "$here" && OHSDIGI_WHEEL_WORK=$HOME/build/ohsdigi-wheel-test python3 -m unittest discover -s tests -p test_ohsdigi_wheel.py)
    rmdir "$HOME/build/ohsdigi-wheel-test" 2>/dev/null || true
fi

(cd "$out" && sha256sum ohs_ohsdigi-*.whl > SHA256SUMS && cat SHA256SUMS)
ls -l "$out"
