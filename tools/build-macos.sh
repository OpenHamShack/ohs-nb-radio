#!/bin/bash
# Build "OpenHamShack QO-100 NB.app" and "OpenHamShack Radio.app", and a .dmg of each, on an
# Apple Silicon Mac.
#
#   tools/build-macos.sh [--app nb|ham|all] [--work DIR] [--no-tests] [--preview LABEL]
#
# Run on the Mac, from a checkout (or a `git archive`) of the repository.
# --app picks the program (all, the default, builds both: one work folder
# serves both, as on Windows). Everything it downloads or builds goes under
# --work (default ~/openhamshack-mac): a pinned Python, uv, a Rust toolchain,
# cmake, the libraries built from source, a download cache, PyInstaller's
# folders, and out/ with the .dmg files. Nothing is installed outside that
# folder, nothing needs an administrator, and no shell profile or system
# setting is touched: delete the folder and it is gone. Apple's Command
# Line Tools (clang, codesign, hdiutil, iconutil) are the one thing the Mac
# must already have. (Rosetta 2 was too, for WSJT-X's Intel tools, until
# they were dropped on 17/10/2026: see below.)
#
# --preview LABEL makes a build that is not a release - the first was
# --preview mac-preview.1 (07/10/2026), from main after 0.1.9 - and says so
# everywhere it shows: About and the update check read "0.1.9+mac-preview.1"
# (ohscore/update.py orders that as 0.1.9, so 0.1.10 is offered to it and
# 0.1.9 is not), and the disk image is openhamshack-nb-0.1.9-mac-preview.1-arm64.dmg
# ("-", not "+", in a file name that goes into URLs). Done here, at build
# time, in a VERSION file of the build's own (the spec's OHSMAC_VERSION_FILE):
# ohsnb/VERSION and ohsradio/VERSION keep naming the release the other
# platforms ship, and the source tree is not touched. The name also keeps
# it out of the update feed, which only ever looks for
# <package>-<release>-arm64.dmg (tools/update-feed.py).
#
# The Mac build is UNSIGNED: ad-hoc signed only (codesign -s -), which an
# arm64 Mac needs before it will run anything at all, and which proves
# nothing about who built it. docs/macos.md says what a Developer ID and
# notarisation will need, and docs/INSTALL.md how a user opens an unsigned
# app. The steps, and why each part comes from where it does:
#
#  - Python 3.13.16 from python-build-standalone (the build uv itself
#    installs; the same CPython version as the Windows build), unpacked by
#    this script from a pinned tarball, and a virtualenv made by uv with
#    packaging/macos/requirements.txt - the Windows build's pins.
#  - PortAudio v19.7.0 built from source and linked statically into PyAudio
#    0.2.14, built from its sdist: PyPI has Windows wheels of PyAudio only.
#  - libiio 0.26 (the series these bindings speak, as on Windows) and
#    libad9361-iio v0.3 built from source, network and XML backends only:
#    the Pluto and LibreSDR are reached as ip:, and a Pluto on USB is a
#    network interface to macOS. libxml2 is the system's own.
#  - codec2 1.2.0 built from source (FreeDV), as cheap as it is.
#  - ohsdigi (rust/ohsdigi) built natively with a pinned Rust (rustup, its
#    own folders under --work, --no-modify-path).
#  - No WSJT-X (Brian, 17/10/2026). Up to then jt9, ft8code, q65code and
#    their libraries came from WSJT-X 2.7.0's .dmg, as ohsdigi's fallback
#    and shadow. They were x86_64 only, so they ran under Rosetta 2, which
#    Apple is retiring (macOS warned "Support Ending for Intel-Based Apps"),
#    and in the notarised app jt9 never decoded at all: signed with the
#    hardened runtime it aborts in libgcc's __enable_execute_stack, as
#    gfortran's trampolines need an executable stack. ohsdigi decodes and
#    encodes every slot mode; a WSJT-X the operator installs is still used
#    (ohscore/host.py find_tool). The build now refuses any Mach-O without
#    an arm64 slice. (The FT8 Country column's cty.dat is ohscore's own,
#    ohscore/data, put in by the spec.)
#  - PyInstaller makes the .app (packaging/macos/<package>.spec); the
#    libraries above are then put into Contents/Frameworks, the whole
#    bundle is signed ad hoc from the inside out, and the frozen program is
#    started headless on the simulator, as build-windows.ps1 does, before
#    the .dmg is made.
#
# Every download is pinned by SHA-256, and a changed upstream file stops
# the build instead of shipping.
set -euo pipefail

APPS=(nb ham)
WORK="$HOME/openhamshack-mac"
TESTS=1
PREVIEW=
SIGN=0
NOTARIZE=1
while (($#)); do
    case $1 in
        --app) case $2 in nb|ham) APPS=("$2") ;; all) APPS=(nb ham) ;; *) echo "--app nb|ham|all" >&2; exit 2 ;; esac; shift ;;
        --work) WORK=$2; shift ;;
        --no-tests) TESTS=0 ;;
        --preview) PREVIEW=$2; shift ;;
        --sign) SIGN=1 ;;
        --no-notarize) NOTARIZE=0 ;;
        *) echo "usage: $0 [--app nb|ham|all] [--work DIR] [--no-tests] [--preview LABEL] [--sign [--no-notarize]]" >&2; exit 2 ;;
    esac
    shift
done
# The same shape ohscore/update.py's installed_version accepts.
# --sign: the OpenHamShack beta's macOS builds are signed with the
# Developer ID and notarised (docs/research/PACKAGING.md in ~/openhamshack:
# "Beta: macOS .app/.dmg are signed AND notarised"). The identity is in the
# Mac mini's ohs-signing keychain, unlocked with its password file, which
# goes to `security` and nowhere else; notarytool uses the ohs-notary
# keychain profile (the API key never leaves the Mac). The same names as
# ohs-libs packaging/macos/build-dmg.sh, so one keychain serves both.
IDENTITY="Developer ID Application: Brian Henderson (GTVYVL6ZY7)"
KEYCHAIN="$HOME/Library/Keychains/ohs-signing.keychain-db"
PASSFILE="$HOME/.config/ohs-signing/keychain-pass"
PROFILE="ohs-notary"
if ((SIGN)); then
    [[ -f $KEYCHAIN ]] || { echo "--sign: no signing keychain at $KEYCHAIN (this is the Mac mini's)" >&2; exit 2; }
    [[ -r $PASSFILE ]] || { echo "--sign: no keychain password file at $PASSFILE" >&2; exit 2; }
fi
unlock() { security unlock-keychain -p "$(cat "$PASSFILE")" "$KEYCHAIN"; }

label_re='^[0-9A-Za-z]+([.-][0-9A-Za-z]+)*$'
if [[ -n $PREVIEW ]] && ! [[ $PREVIEW =~ $label_re ]]; then
    echo "--preview: letters, digits, dots and hyphens, such as mac-preview.1" >&2; exit 2
fi
[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || { echo "build-macos.sh runs on an Apple Silicon Mac" >&2; exit 2; }
for t in clang codesign hdiutil iconutil install_name_tool otool shasum; do
    command -v $t >/dev/null || { echo "$t is missing: install Apple's Command Line Tools (xcode-select --install)" >&2; exit 2; }
done

REPO=$(cd "$(dirname "$0")/.." && pwd)
CACHE=$WORK/cache
VENDOR=$WORK/vendor
BUILD=$WORK/build
OUT=$WORK/out
TOOLS=$WORK/tools
mkdir -p "$CACHE" "$VENDOR" "$BUILD" "$OUT" "$TOOLS"
# What we compile ourselves targets 12.0, but that is not the app's
# minimum: the wheels set it, and NumPy 2.5's arm64 wheels are built for
# macOS 14 (Accelerate), PyQt6 6.11's Qt for 13. The specs'
# LSMinimumSystemVersion says 14.0, and the check after signing below
# fails the build if any binary in the bundle wants a later macOS than
# that - so a Mac too old for it is told so by Finder, rather than the
# program dying at "import numpy".
export MACOSX_DEPLOYMENT_TARGET=12.0
# uv keeps everything it caches here, reads no config of the user's, and
# never puts a python shim in ~/.local/bin.
export UV_CACHE_DIR=$CACHE/uv UV_NO_CONFIG=1 UV_PYTHON_DOWNLOADS=never

step() { printf '\n== %s\n' "$*"; }

# shack_sdr (RTTY in both apps, the codec loader, the RTL-SDR and SDRplay
# sources) is native, one wheel per platform, and no macOS universal2
# wheel is pinned in tools/vendor/shack-sdr.lock yet. The specs would stop
# on that after an hour of building; say so now instead.
step "shack_sdr for macOS"
python3 "$REPO/packaging/shack_vendor.py" "$BUILD/shack-sdr-check" macosx >/dev/null
rm -rf "$BUILD/shack-sdr-check"
die() { echo "build-macos.sh: $*" >&2; exit 1; }

# ---------------------------------------------------------------- pins
# pin NAME -> "file sha256 url". A function, not an associative array:
# the bash every Mac has is 3.2, which has none.
pin() {
    case $1 in
        uv) echo "uv-aarch64-apple-darwin-0.12.23.tar.gz 50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544 https://github.com/astral-sh/uv/releases/download/0.12.23/uv-aarch64-apple-darwin.tar.gz" ;;
        # The interpreter, and the same release's "full" archive, read only for
        # the licence texts of the libraries linked into libpython (OpenSSL,
        # SQLite, libffi...), which the install-only archive leaves out.
        python) echo "cpython-3.13.16+20261003-aarch64-apple-darwin-install_only.tar.gz d8975d7df4f08f7b1c7aafcdfacbddcec3d366415f2c1a72b2466b6850815933 https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.13.16%2B20261003-aarch64-apple-darwin-install_only.tar.gz" ;;
        python_full) echo "cpython-3.13.16+20261003-aarch64-apple-darwin-pgo+lto-full.tar.zst ca3eb5bf8110eaed1c3e516be4bd4d52bcf636f8e888359353f274288406bae7 https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.13.16%2B20261003-aarch64-apple-darwin-pgo%2Blto-full.tar.zst" ;;
        # rustup-init 1.29.1; the toolchain itself is pinned by version below,
        # and rustup checks what it downloads against the channel's hashes.
        rustup) echo "rustup-init-1.29.1 ec1b9233e7f72990ecd8e62063fa7f6c3dfc2bec8e97f88bff165f9100ac696a https://static.rust-lang.org/rustup/archive/1.29.1/aarch64-apple-darwin/rustup-init" ;;
        portaudio) echo "pa_stable_v190700_20210406.tgz 47efbf42c77c19a05d22e627d42873e991ec0c1357219c0d74ce6a2948cb2def http://files.portaudio.com/archives/pa_stable_v190700_20210406.tgz" ;;
        pyaudio) echo "PyAudio-0.2.14.tar.gz 78dfff3879b4994d1f4fc6485646a57755c6ee3c19647a491f790a0895bd2f87 https://files.pythonhosted.org/packages/26/1d/8878c7752febb0f6716a7e1a52cb92ac98871c5aa522cba181878091607c/PyAudio-0.2.14.tar.gz" ;;
        libiio) echo "libiio-0.26.tar.gz fb445fb860ef1248759f45d4273a4eff360534480ec87af64c6b8db3b99be7e5 https://github.com/analogdevicesinc/libiio/archive/refs/tags/v0.26.tar.gz" ;;
        libad9361) echo "libad9361-iio-0.3.tar.gz 1dc35dd997e1938a97489fa1f349ee16889f9de8901a2c7af46184468dc90598 https://github.com/analogdevicesinc/libad9361-iio/archive/refs/tags/v0.3.tar.gz" ;;
        codec2) echo "codec2-1.2.0.tar.gz cbccae52b2c2ecc5d2757e407da567eb681241ff8dadce39d779a7219dbcf449 https://github.com/drowe67/codec2/archive/refs/tags/1.2.0.tar.gz" ;;
        libad9361_license) echo "libad9361-LICENSE 5525fbd0911b8dcbdc6f0c081ac27fd55b75d6d261c62fa05b9bdc0b72b481f6 https://raw.githubusercontent.com/analogdevicesinc/libad9361-iio/v0.3/LICENSE" ;;
        pyserial_license) echo "pyserial-LICENSE.txt f91cb9813de6a5b142b8f7f2dede630b5134160aedaeaf55f4d6a7e2593ca3f3 https://raw.githubusercontent.com/pyserial/pyserial/v3.5/LICENSE.txt" ;;
        *) die "no pin named $1" ;;
    esac
}
RUST_TOOLCHAIN=1.98.1        # as rust/build.Containerfile

fetch() {   # fetch NAME -> prints the cached path
    local file sha url dest got
    read -r file sha url <<<"$(pin "$1")"
    dest=$CACHE/$file
    if [[ -f $dest ]] && [[ $(shasum -a 256 "$dest" | cut -d' ' -f1) == "$sha" ]]; then
        echo "$dest"; return
    fi
    echo "   fetching $url" >&2
    # A plain tool's user agent: SourceForge answers a browser-like one with
    # an HTML page instead of the file (build-windows.ps1 met it first).
    curl -fsSL -A "Wget/1.21" -o "$dest.part" "$url"
    got=$(shasum -a 256 "$dest.part" | cut -d' ' -f1)
    if [[ $got != "$sha" ]]; then
        rm -f "$dest.part"
        die "$file: SHA-256 $got, expected $sha. Upstream changed the file; check it and update the pin."
    fi
    mv "$dest.part" "$dest"
    echo "$dest"
}

unpack() {  # unpack TARBALL DIR: a fresh copy of the tarball's one top folder
    rm -rf "$2"; mkdir -p "$2"
    tar -xzf "$1" -C "$2" --strip-components 1
}

# ---------------------------------------------------------------- tools
step "uv and Python 3.13.16"
UV=$TOOLS/uv/uv
if [[ ! -x $UV ]]; then
    mkdir -p "$TOOLS/uv"
    tar -xzf "$(fetch uv)" -C "$TOOLS/uv" --strip-components 1
fi
PYHOME=$TOOLS/python-3.13.16
if [[ ! -x $PYHOME/bin/python3.13 ]]; then
    unpack "$(fetch python)" "$PYHOME"
fi
VENV=$WORK/venv
VPY=$VENV/bin/python
if [[ ! -x $VPY ]] || [[ $("$VPY" -c 'import sys; print(sys.version.split()[0])') != 3.13.16 ]]; then
    rm -rf "$VENV"
    "$UV" venv -q -p "$PYHOME/bin/python3.13" "$VENV"
fi
export VIRTUAL_ENV=$VENV
"$UV" pip install -q --only-binary :all: -r "$REPO/packaging/macos/requirements.txt"
CMAKE=$VENV/bin/cmake
CMAKE_COMMON=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET
              -DCMAKE_POLICY_VERSION_MINIMUM=3.5)

LIC=$VENDOR/licences
rm -rf "$LIC"; mkdir -p "$LIC"

# ---------------------------------------------------------------- PortAudio + PyAudio
step "PortAudio v19.7.0 (static) and PyAudio 0.2.14"
if ! "$VPY" -c 'import pyaudio, sys; sys.exit(pyaudio.get_portaudio_version_text().find("V19.7.0") < 0)' 2>/dev/null; then
    unpack "$(fetch portaudio)" "$BUILD/portaudio"
    "$CMAKE" -S "$BUILD/portaudio" -B "$BUILD/portaudio/b" "${CMAKE_COMMON[@]}" -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DCMAKE_INSTALL_PREFIX="$VENDOR/portaudio" >/dev/null
    "$CMAKE" --build "$BUILD/portaudio/b" -j 8 --target portaudio_static >/dev/null
    mkdir -p "$VENDOR/portaudio/static" "$VENDOR/portaudio/include"
    cp "$BUILD/portaudio/b/libportaudio.a" "$VENDOR/portaudio/static/"
    cp "$BUILD/portaudio/include/"*.h "$VENDOR/portaudio/include/"
    unpack "$(fetch pyaudio)" "$BUILD/pyaudio"
    # Static: a folder holding only libportaudio.a, so -lportaudio cannot
    # find a dylib, and the frameworks PortAudio's Core Audio host uses.
    # PyAudio's setup.py has no static option on macOS; these flags are it.
    CFLAGS="-I$VENDOR/portaudio/include" \
    LDFLAGS="-L$VENDOR/portaudio/static -framework CoreAudio -framework AudioToolbox -framework AudioUnit -framework CoreFoundation -framework CoreServices" \
        "$UV" pip install -q --no-build-isolation --no-cache "$BUILD/pyaudio"
fi
"$VPY" -c 'import pyaudio; print("   PyAudio", pyaudio.__version__, "with", pyaudio.get_portaudio_version_text())'
if otool -L "$("$VPY" -c 'import pyaudio._portaudio as m; print(m.__file__)')" | tail -n +2 | grep -q libportaudio; then
    die "PyAudio links a PortAudio dylib; it must have it linked in"
fi
cp "$BUILD/portaudio/LICENSE.txt" "$LIC/portaudio-LICENSE.txt" 2>/dev/null || \
    tar -xzf "$(fetch portaudio)" -O portaudio/LICENSE.txt > "$LIC/portaudio-LICENSE.txt"

# ---------------------------------------------------------------- libiio, libad9361
step "libiio 0.26 and libad9361-iio v0.3, from source"
# Into vendor/libiio as the bundle has them: libiio.dylib (its id
# @rpath/libiio.dylib - the name iio.py's find_library("iio") looks for, so
# no symlink is needed), and beside the bundle's root libad9361.dylib, whose
# reference to libiio is rewritten to @loader_path/libiio/libiio.dylib so it
# loads the very file iio.py loaded. iio.py is that release's own binding.
IIO=$VENDOR/libiio
if [[ ! -f $IIO/libiio.dylib || ! -f $VENDOR/libad9361.dylib || ! -f $VENDOR/py/iio.py ]]; then
    unpack "$(fetch libiio)" "$BUILD/libiio"
    "$CMAKE" -S "$BUILD/libiio" -B "$BUILD/libiio/b" "${CMAKE_COMMON[@]}" -DCMAKE_INSTALL_PREFIX="$BUILD/libiio/inst" \
        -DOSX_FRAMEWORK=OFF -DOSX_PACKAGE=OFF -DWITH_USB_BACKEND=OFF -DWITH_SERIAL_BACKEND=OFF -DWITH_TESTS=OFF \
        -DWITH_DOC=OFF -DWITH_MAN=OFF -DPYTHON_BINDINGS=OFF >/dev/null
    "$CMAKE" --build "$BUILD/libiio/b" -j 8 >/dev/null
    "$CMAKE" --install "$BUILD/libiio/b" >/dev/null
    rm -rf "$IIO"; mkdir -p "$IIO" "$VENDOR/py"
    cp "$BUILD/libiio/inst/lib/libiio.0.26.dylib" "$IIO/libiio.dylib"
    install_name_tool -id @rpath/libiio.dylib "$IIO/libiio.dylib"
    cp "$BUILD/libiio/bindings/python/iio.py" "$VENDOR/py/iio.py"
    unpack "$(fetch libad9361)" "$BUILD/libad9361"
    # Its CMakeLists makes a framework whatever it is told; the library
    # inside is taken out of it.
    "$CMAKE" -S "$BUILD/libad9361" -B "$BUILD/libad9361/b" "${CMAKE_COMMON[@]}" -DOSX_PACKAGE=OFF -DWITH_DOC=OFF \
        -DLIBIIO_LIBRARIES="$BUILD/libiio/inst/lib/libiio.dylib" -DLIBIIO_INCLUDEDIR="$BUILD/libiio/inst/include" >/dev/null
    "$CMAKE" --build "$BUILD/libad9361/b" -j 8 --target ad9361 >/dev/null
    cp "$BUILD/libad9361/b/ad9361.framework/Versions/0.2/ad9361" "$VENDOR/libad9361.dylib"
    install_name_tool -id @rpath/libad9361.dylib -change @rpath/libiio.0.dylib @loader_path/libiio/libiio.dylib \
        "$VENDOR/libad9361.dylib"
fi
tar -xzf "$(fetch libiio)" -O libiio-0.26/COPYING.txt > "$LIC/libiio-COPYING.txt"
cp "$(fetch libad9361_license)" "$LIC/libad9361-LICENSE"
# The bindings must load this library and report 0.26, found the way the
# frozen program finds it (host.bundled_libiio: DYLD_LIBRARY_PATH for the import).
DYLD_LIBRARY_PATH=$IIO "$VPY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import iio, os
d = os.path.dirname(iio._lib._name); print("   libiio", ".".join(map(str, iio.version[:2])), iio.version[2], "from", d)
assert iio.version[:2] == (0, 26), iio.version; assert os.path.samefile(d, sys.argv[2]), d' "$VENDOR/py" "$IIO"

# ---------------------------------------------------------------- codec2
step "codec2 1.2.0, from source"
if [[ ! -f $VENDOR/libcodec2.dylib ]]; then
    unpack "$(fetch codec2)" "$BUILD/codec2"
    "$CMAKE" -S "$BUILD/codec2" -B "$BUILD/codec2/b" "${CMAKE_COMMON[@]}" -DUNITTEST=OFF >/dev/null
    "$CMAKE" --build "$BUILD/codec2/b" -j 8 --target codec2 >/dev/null
    cp "$BUILD/codec2/b/src/libcodec2.1.2.dylib" "$VENDOR/libcodec2.dylib"
    install_name_tool -id @rpath/libcodec2.dylib "$VENDOR/libcodec2.dylib"
fi
tar -xzf "$(fetch codec2)" -O codec2-1.2.0/COPYING > "$LIC/codec2-COPYING"

# ---------------------------------------------------------------- ohsdigi
step "ohsdigi with Rust $RUST_TOOLCHAIN"
export RUSTUP_HOME=$TOOLS/rustup CARGO_HOME=$TOOLS/cargo
if [[ ! -x $CARGO_HOME/bin/cargo ]]; then
    rustup_init=$(fetch rustup); chmod +x "$rustup_init"
    "$rustup_init" -y -q --no-modify-path --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
fi
# An extension module leaves Python's symbols to be found when it is
# loaded: -undefined dynamic_lookup is how a Mac linker is told so (PyO3
# does it itself only through a build script, which ohsdigi has none of).
(cd "$REPO/rust/ohsdigi" && env PATH="$CARGO_HOME/bin:$PATH" PYO3_NO_PYTHON=1 PYO3_BUILD_EXTENSION_MODULE=1 \
    CARGO_TARGET_DIR="$BUILD/ohsdigi-target" \
    RUSTFLAGS="-C link-arg=-undefined -C link-arg=dynamic_lookup --remap-path-prefix=$REPO/rust=/src --remap-path-prefix=$CARGO_HOME/registry=/cargo" \
    "$CARGO_HOME/bin/cargo" +"$RUST_TOOLCHAIN" build -q --release --locked --features python --target aarch64-apple-darwin)
# Into the source tree as ohscore/ohsdigi.abi3.so (ignored by git), where the
# suite below imports it and PyInstaller collects it.
cp "$BUILD/ohsdigi-target/aarch64-apple-darwin/release/libohsdigi.dylib" "$REPO/ohscore/ohsdigi.abi3.so"
cp "$REPO/rust/ohsdigi/LICENSE-THIRD-PARTY" "$LIC/ohsdigi-LICENSE-THIRD-PARTY.txt"
(cd "$REPO" && "$VPY" -c "from ohscore import ohsdigi; e = ohsdigi.encode('ft4', 'CQ G4XYZ IO91'); assert ''.join(map(str, e.tones)) == '0132103311233031311022300030202121023133023323031212322012213001002310012202210103011011112103311313201', e.tones; print('   ohsdigi', ohsdigi.__version__, 'loads and encodes FT4 here')")

# ---------------------------------------------------------------- licences
step "Licence texts: cty.dat's notice and pyserial's"
# cty.dat's notice keeps the name in licences/ that WSJT-X's copy of it
# had; the file itself is ohscore/data's, which the spec collects.
cp "$REPO/ohscore/data/cty.dat-copyright.txt" "$LIC/cty.dat-copyright.txt"
read -r f _ <<<"$(pin pyserial_license)"; cp "$(fetch pyserial_license)" "$LIC/$f"
# A work folder from a build before 17/10/2026 still has WSJT-X's tools and
# its licence texts; none of it may reach the bundle.
rm -rf "$VENDOR/wsjtx"
rm -f "$LIC"/wsjtx-COPYING "$LIC"/boost-LICENSE_1_0.txt "$LIC"/fftw-COPYING "$LIC"/gcc-COPYING.RUNTIME \
      "$LIC"/libquadmath-COPYING.LIB "$LIC"/qt5-LICENSE.LGPL3

# ---------------------------------------------------------------- Python's own libraries' licences
step "Licences of the libraries inside Python"
# Everything python-build-standalone links into libpython3.13.dylib; not
# Tcl/Tk/X11 (only _tkinter, which the specs exclude) nor OpenSSL 1.1.
"$VPY" - "$(fetch python_full)" "$LIC" <<'EOF'
import sys, tarfile, zstandard
from pathlib import Path
skip = {"tcl", "tix", "tk", "libX11", "libXau", "libxcb", "openssl-1.1"}
out = Path(sys.argv[2]); n = 0
with open(sys.argv[1], "rb") as f, tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(f), mode="r|") as t:
    for m in t:
        name = Path(m.name).name
        if m.isfile() and m.name.startswith("python/licenses/LICENSE.") and name.split(".")[1] not in skip:
            (out / f"python-{name}").write_bytes(t.extractfile(m).read()); n += 1
print(f"   {n} licence texts")
EOF

# ---------------------------------------------------------------- tests
if ((TESTS)); then
    step "Test suite under the build's Python"
    # The venv first on PATH: tools the suite runs as `python3` (release.sh,
    # update-feed.py) need its cryptography. codec2 is found, as a run from
    # source finds a library, through dyld's fallback path. SHACK_NO_WSJTX
    # hides any installed WSJT-X (ohscore/host.py find_tool), so the suite
    # tests what ships - ohsdigi alone - and not the Mac's own WSJT-X 3.0.2,
    # which does not read one of ohsdigi's 2.7.0 messages back.
    (cd "$REPO" && SHACK_NO_WSJTX=1 PATH="$VENV/bin:$PATH" DYLD_FALLBACK_LIBRARY_PATH="$VENDOR:/usr/local/lib:/usr/lib" \
        "$VPY" -m unittest discover -s tests)
fi

# ---------------------------------------------------------------- per app
for app in "${APPS[@]}"; do
    case $app in
        nb)  PKG=openhamshack-nb;    NAME="OpenHamShack QO-100 NB"; PYDIR=ohsnb;  ENVP=OHS_NB
             FT8_CONF='{"mode": "ft8", "vfo": 10489540000.0}'; FT8_ARGS=() ;;
        ham) PKG=openhamshack-radio; NAME="OpenHamShack Radio";     PYDIR=ohsradio; ENVP=OHS_RADIO
             FT8_CONF='{}'; FT8_ARGS=(--band 20m --mode ft8) ;;
    esac
    RELEASE=$(tr -d '[:space:]' < "$REPO/$PYDIR/VERSION")
    VERSION=$RELEASE${PREVIEW:++$PREVIEW}
    VERSION_DIR=$BUILD/version-$PKG
    rm -rf "$VERSION_DIR"; mkdir -p "$VERSION_DIR"
    echo "$VERSION" > "$VERSION_DIR/VERSION"

    step "$NAME $VERSION: icon"
    ICNS=$VENDOR/$PKG.icns
    (cd "$REPO" && "$VPY" tools/make-ico.py --app "$app" "$ICNS")

    step "$NAME $VERSION: PyInstaller"
    DIST=$BUILD/dist
    OHSMAC_VENDOR=$VENDOR OHSMAC_ICNS=$ICNS OHSMAC_PYLICENCE=$PYHOME/lib/python3.13/LICENSE.txt \
    OHSMAC_VERSION_FILE=$VERSION_DIR/VERSION \
        "$VPY" -m PyInstaller --noconfirm --log-level WARN --distpath "$DIST" --workpath "$BUILD/pyi-work" \
        "$REPO/packaging/macos/$PKG.spec"
    APP=$DIST/$NAME.app
    FW=$APP/Contents/Frameworks
    [[ -d $APP ]] || die "PyInstaller made no $APP"
    if find "$APP" -name 'QtPdf*' -o -name 'libqpdf.dylib' | grep -q .; then
        die "Qt PDF is in the bundle again (packaging/windows/bundle_prune.py no longer catches it)"
    fi
    [[ -f $FW/ohscore/ohsdigi.abi3.so ]] || die "ohsdigi is not in the bundle"

    step "$NAME $VERSION: libraries into Contents/Frameworks"
    mkdir -p "$FW/libiio"
    cp "$IIO/libiio.dylib" "$FW/libiio/"
    cp "$VENDOR/libad9361.dylib" "$VENDOR/libcodec2.dylib" "$FW/"
    # WSJT-X is no longer carried (above); nothing of an older build's copy
    # may be left in the bundle either.
    rm -rf "$FW/wsjtx" "$APP/Contents/Resources/wsjtx"

    if ((SIGN)); then
        step "$NAME $VERSION: Developer ID signature, hardened runtime, inside out"
        unlock
        sign() { codesign --force --options runtime --timestamp --keychain "$KEYCHAIN" -s "$IDENTITY" "$@" 2>&1 \
                     | grep -v "replacing existing signature" || true; }
        # Every Mach-O but the main executable, deepest first, so each
        # container is signed after what it holds; then the bundle, with
        # the entitlements (the microphone).
        find "$APP/Contents" -type f ! -path "$APP/Contents/MacOS/$PKG" -print0 \
            | xargs -0 file -h | awk -F': ' '/Mach-O/ {sub(/ \(for architecture [^)]*\)$/, "", $1); print $1}' | sort -u \
            | awk -F/ '{print NF "\t" $0}' | sort -rn | cut -f2- \
            | while IFS= read -r f; do sign "$f"; done
        sign --entitlements "$REPO/packaging/macos/entitlements.plist" "$APP"
        codesign --verify --deep --strict "$APP" || die "the signed bundle does not verify"
        codesign -dv "$APP" 2>&1 | grep -E '^(Authority=Developer|TeamIdentifier|Runtime|Timestamp)' | sed 's/^/   /'
    else
    step "$NAME $VERSION: ad-hoc signature, inside out"
    # Every piece of code first, then the bundle, which seals them. Ad hoc
    # (-s -): what an arm64 Mac needs to run anything; it names nobody. A
    # Developer ID build signs the same list with --options runtime and a
    # timestamp (docs/macos.md).
    sign() { codesign --force --sign - "$@" 2>&1 | grep -v "replacing existing signature" || true; }
    sign "$FW/libiio/libiio.dylib" "$FW/libad9361.dylib" "$FW/libcodec2.dylib"
    sign "$APP"
    codesign --verify --deep --strict "$APP" || die "the signed bundle does not verify"
    fi

    # Every Mach-O in the bundle must run natively: one with no arm64 slice
    # would need Rosetta 2, which Apple is retiring. WSJT-X's tools were
    # the only ones until 17/10/2026; this keeps another from creeping in.
    intel=$(find "$APP" -type f -print0 | xargs -0 file -h \
            | awk -F': ' '/Mach-O/ && !/arm64/ && !/\(for architecture / {print $1}' | sed "s|^$APP/||")
    [[ -z $intel ]] || die "Mach-O files with no arm64 slice (they would need Rosetta 2):"$'\n'"$intel"
    echo "   every Mach-O in the bundle has an arm64 slice"

    # Every Mach-O in the bundle, every slice: the newest macOS any of them
    # was built for (LC_BUILD_VERSION minos, or the older
    # LC_VERSION_MIN_MACOSX) must not be later than Info.plist's
    # LSMinimumSystemVersion. Found 07/10/2026: the plist said 12.0 while
    # NumPy needed 14.0.
    "$VPY" - "$APP" <<'EOF' || die "a binary in the bundle needs a later macOS than LSMinimumSystemVersion (above)"
import plistlib, subprocess, sys
from pathlib import Path
app = Path(sys.argv[1])
floor = plistlib.loads((app / "Contents/Info.plist").read_bytes())["LSMinimumSystemVersion"]
ver = lambda s: tuple(int(x) for x in s.split("."))
worst, bad = ("0", None), []
for f in app.rglob("*"):
    if f.is_symlink() or not f.is_file():
        continue
    with open(f, "rb") as fh:
        if fh.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):
            continue
    want, cmd = None, ""
    for line in subprocess.run(["otool", "-arch", "all", "-l", str(f)], capture_output=True, text=True).stdout.splitlines():
        w = line.split()
        if len(w) == 2 and w[0] == "cmd":
            cmd = w[1]
        # Only these two commands' fields: LC_SOURCE_VERSION has a "version" line too.
        elif len(w) == 2 and (cmd, w[0]) in (("LC_BUILD_VERSION", "minos"), ("LC_VERSION_MIN_MACOSX", "version")):
            want = w[1] if want is None or ver(w[1]) > ver(want) else want
    if want and ver(want) > ver(worst[0]):
        worst = (want, f.relative_to(app))
    if want and ver(want) > ver(floor):
        bad.append(f"{want}  {f.relative_to(app)}")
print(f"   newest macOS any binary needs: {worst[0]} ({worst[1]}); LSMinimumSystemVersion {floor}")
for b in sorted(bad, key=lambda b: ver(b.split()[0]), reverse=True)[:20]:
    print("   too new: " + b)
sys.exit(1 if bad else 0)
EOF
    echo "   $(codesign -dv "$APP" 2>&1 | grep -E '^(Identifier|Signature)=' | tr '\n' ' ')"

    step "$NAME $VERSION: nothing encumbered in the bundle"
    # No AAC or AMBE codec and no SDRplay API carried, linked or defined by
    # anything in the .app (RADIO-SDR-PLAN 5.5), checked with ohs-libs' own
    # tool, vendored and hash-checked.
    "$VPY" "$REPO/packaging/shack_vendor.py" --check-encumbered "$APP" || die "the bundle failed the encumbered check"

    step "$NAME $VERSION: smoke test - headless on the simulator"
    EXE=$APP/Contents/MacOS/$PKG
    SMOKE=$BUILD/smoke-$PKG
    rm -rf "$SMOKE"; mkdir -p "$SMOKE"
    export "${ENVP}_CONF=$SMOKE/config.json" "${ENVP}_DATA=$SMOKE/data" "${ENVP}_UI_CONF=$SMOKE/ui.json"
    "$EXE" --headless --device sim --no-audio --seconds 3 >/dev/null

    step "$NAME $VERSION: smoke test - the bundle's own libiio"
    # Nothing listens at 127.0.0.1's IIO port: "No Pluto at" is only said
    # once libiio.dylib has loaded and been refused.
    printf '{"device": "pluto", "plutoUri": "ip:127.0.0.1"}' > "$SMOKE/config.json"
    said=$("$EXE" --headless --no-audio --seconds 2 2>&1 || true)
    grep -q "No Pluto at ip:127.0.0.1" <<<"$said" && ! grep -qE "could not be loaded|not the 0.2x series" <<<"$said" || \
        die "the frozen build did not reach its own libiio:"$'\n'"$said"
    echo "   $(grep -m1 "No Pluto at" <<<"$said" | cut -c1-110)..."

    step "$NAME $VERSION: smoke test - ohsdigi, no WSJT-X, and the update signature check from the bundle"
    rm -f "$SMOKE/config.json"
    # SHACK_NO_WSJTX, here and in the FT8 smoke test: as the suite, the
    # bundle on its own, whatever WSJT-X this Mac has.
    said=$(SHACK_NO_WSJTX=1 "$EXE" --headless --device sim --no-audio --seconds 1 -v 2>&1)
    # The version it reports is the one this build was given (a preview's
    # label included): what About shows and what the update check sends.
    said_version=$(grep -m1 " INFO version: " <<<"$said" | sed 's/.* INFO version: //' || true)
    [[ $said_version == "$VERSION" ]] || die "the frozen build says it is '$said_version', not $VERSION"
    echo "   version: $said_version"
    # Q65 is encoded by ohsdigi since 0.2.0 (ohscore/diag.py _q65_encoder);
    # q65code is still carried, as the fallback a build without it would
    # use, so its fact naming q65code would mean ohsdigi's Q65 is missing.
    for fact in "ft8/ft4 encoder: ohsdigi .*Contents/Frameworks/ohscore/ohsdigi" "jt9: not installed \(optional; ohsdigi decodes\)" \
                "ft8/ft4 decoder: ohsdigi; no jt9" \
                "q65 encoder: ohsdigi$" \
                "cty.dat: .*Contents/Frameworks/ohscore/data/cty.dat" "codec2: .*Contents/Frameworks/libcodec2.dylib" \
                "update signatures: .*self-test passed"; do
        line=$(grep -m1 -E "${fact%%: *}: " <<<"$said" || true)
        echo "   ${line#* INFO }" | cut -c1-160
        grep -qE "$fact" <<<"$line" || die "start-up facts do not say \"$fact\":"$'\n'"$said"
    done

    step "$NAME $VERSION: smoke test - FT8 decoded by the bundle's ohsdigi (40 s)"
    # Until 17/10/2026 this said "by the bundle's jt9" while the default
    # decoder, ohsdigi, did the decoding: the bundled jt9 was crashing every
    # slot and this step passed regardless.
    printf '%s' "$FT8_CONF" > "$SMOKE/config.json"
    said=$(SHACK_NO_WSJTX=1 "$EXE" --headless --device sim --no-audio --seconds 40 ${FT8_ARGS[@]+"${FT8_ARGS[@]}"} 2>&1)
    n=$(grep -c "^decode: .*'mode': 'ft8'" <<<"$said" || true)
    grep -m2 "^decode: .*'mode': 'ft8'" <<<"$said" | cut -c1-150 | sed 's/^/   /'
    ((n >= 1)) || die "the frozen build decoded no FT8 in 40 s on the simulator:"$'\n'"$said"
    echo "   $n FT8 decodes"

    if [[ $app == ham ]]; then
        step "$NAME $VERSION: smoke test - the CW skimmer's worker process"
        # The skimmer's decoders run in a spawned child, which in a frozen
        # app is this executable started again: it works only with
        # multiprocessing.freeze_support() at the entry point and shack_cw.skim
        # and cty.dat in the bundle. The self-test decodes a synthetic band
        # in that child and names each station's country.
        said=$("$EXE" --cw-skim-selftest 2>&1) || die "the frozen build's CW skimmer worker failed:"$'\n'"$said"
        sed 's/^/   /' <<<"$said"
        grep -q "worker process pid" <<<"$said" && grep -q "cw-skim-selftest: PASS" <<<"$said" || \
            die "the frozen build's --cw-skim-selftest did not pass in a worker process:"$'\n'"$said"
    fi

    step "$NAME $VERSION: smoke test - sound out through PortAudio"
    # The real backend, to the Mac's default output, for 3 s: it must open
    # and play (the engine logs the backend's status at stop); a backend
    # that fell back to "null" means no sound.
    rm -f "$SMOKE/config.json"
    said=$("$EXE" --headless --device sim --seconds 3 -v 2>&1)
    line=$(grep -m1 "audio: {" <<<"$said" || true)
    echo "   ${line#* INFO }" | cut -c1-160
    grep -q "'backend': 'portaudio'" <<<"$line" || die "no PortAudio output:"$'\n'"$said"
    unset "${ENVP}_CONF" "${ENVP}_DATA" "${ENVP}_UI_CONF"

    step "$NAME $VERSION: disk image"
    STAGE=$BUILD/dmg-$PKG
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    ditto "$APP" "$STAGE/$NAME.app"
    ln -s /Applications "$STAGE/Applications"
    DMG=$OUT/$PKG-$RELEASE${PREVIEW:+-$PREVIEW}-arm64.dmg
    hdiutil create -quiet -ov -fs HFS+ -format UDZO -volname "$NAME $VERSION" -srcfolder "$STAGE" "$DMG"
    rm -rf "$STAGE"
    if ((SIGN)); then
        unlock
        sign "$DMG"
        if ((NOTARIZE)); then
            step "$NAME $VERSION: notarise (notarytool, profile $PROFILE)"
            # Unlocked again: other sessions on the Mac mini use (and lock)
            # the same keychain, and a submission can take half an hour.
            unlock
            xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --keychain "$KEYCHAIN" --wait \
                --output-format plist > "$BUILD/notary-$PKG.plist"
            status=$(plutil -extract status raw -o - "$BUILD/notary-$PKG.plist")
            sub=$(plutil -extract id raw -o - "$BUILD/notary-$PKG.plist")
            echo "   submission $sub: $status"
            if [[ $status != Accepted ]]; then
                xcrun notarytool log "$sub" --keychain-profile "$PROFILE" --keychain "$KEYCHAIN" || true
                die "notarisation was not accepted"
            fi
            xcrun stapler staple -q "$DMG"
            xcrun stapler validate -q "$DMG" && echo "   ticket stapled"
            spctl -a -t open --context context:primary-signature -vv "$DMG" 2>&1 | sed 's/^/   /'
        fi
    fi
    (cd "$OUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
    echo "built $DMG"
    echo "sha256 $(cut -d' ' -f1 < "$DMG.sha256")"
    if ((SIGN && NOTARIZE)); then
        echo "signed ($IDENTITY) and notarised"
    elif ((SIGN)); then
        echo "signed but NOT NOTARISED (--no-notarize): Gatekeeper will refuse it on another Mac"
    else
        echo "UNSIGNED (ad-hoc): for testing; Gatekeeper will ask the user to confirm it (docs/INSTALL.md)"
    fi
done
