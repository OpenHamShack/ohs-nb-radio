#!/usr/bin/env bash
# Build rtlsdr.dll, the RTL-SDR library Radio's Windows installer carries
# (shack_sdr.sources.rtlsdr opens it over ctypes), from source, with the
# MinGW-w64 cross toolchain on Linux.
#
#   tools/build-rtlsdr-windows.sh [--out DIR]       (default rust/dist/rtlsdr-windows/, not tracked)
#
# Why build it rather than take a release's: the RTL-SDR Blog's own
# Windows build (Release.zip, v1.3.6) links Microsoft's Visual C++ 2010
# runtime, msvcr100.dll, which has had no security updates for years and
# would have had to ship beside it. This one links the Universal C
# Runtime that every supported Windows has and Python itself uses
# (-mcrtdll=ucrt: api-ms-win-crt-*.dll), with libusb, libgcc and
# winpthreads linked in statically, so rtlsdr.dll is one file needing only
# Windows itself.
#
# What goes in, each pinned by sha256 (a changed upstream file stops the
# build) and published on the source site (packaging/windows/sources.txt),
# which is how the GPL's source obligation is met:
#   - the RTL-SDR Blog's librtlsdr fork, tag v1.3.6 (GPL-2.0-or-later): the
#     fork most Windows guides use, and the one that drives the Blog V4
#     dongle's tuner. Only the library (src/librtlsdr.c and the tuners),
#     none of its command-line tools.
#   - libusb 1.0.26 (LGPL-2.1-or-later), the release tarball.
#
# The same commit builds the same bytes: fixed paths for the sources
# (-ffile-prefix-map), no timestamp in the PE header (--no-insert-timestamp)
# and the symbols stripped. A SHA256SUMS goes beside the DLL; copy both to
# the Windows build host and pass -RtlSdr to build-windows.ps1, as ohsdigi.pyd
# is passed with -Ohsdigi.
#
# Scratch goes under $RTLSDR_WORK (default ~/build/rtlsdr-windows; never
# /tmp, a small shared tmpfs) and is removed at the end.
set -euo pipefail

here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)
out="$here/rust/dist/rtlsdr-windows"
if [ "${1:-}" = "--out" ]; then out=$(mkdir -p "$2" && cd "$2" && pwd); fi
work=${RTLSDR_WORK:-$HOME/build/rtlsdr-windows}
host=x86_64-w64-mingw32
CC=${CC:-$host-gcc}

RTL_URL=https://github.com/rtlsdrblog/rtl-sdr-blog/archive/refs/tags/v1.3.6.tar.gz
RTL_TAR=rtl-sdr-blog-1.3.6.tar.gz
RTL_SHA=0da16913e2988f79d9f3ce2794cecfd35f187ce0a5581c4e0de1b28f01f61a38
USB_URL=https://github.com/libusb/libusb/releases/download/v1.0.26/libusb-1.0.26.tar.bz2
USB_TAR=libusb-1.0.26.tar.bz2
USB_SHA=12ce7a61fc9854d1d2a1ffe095f7b5fac19ddba095c259e6067a46500381b5a5

command -v "$CC" >/dev/null || { echo "build-rtlsdr-windows.sh: no $CC (Debian: gcc-mingw-w64-x86-64)" >&2; exit 2; }

rm -rf "$work"
mkdir -p "$work" "$out"
trap '[ -n "${KEEP_WORK:-}" ] || rm -rf "$work"' EXIT
cd "$work"
fetch() {   # url file sha256
    curl -sSfL -o "$2" "$1"
    echo "$3  $2" | sha256sum -c --quiet - || { echo "build-rtlsdr-windows.sh: $2 is not the pinned file" >&2; exit 1; }
}
fetch "$RTL_URL" "$RTL_TAR" "$RTL_SHA"
fetch "$USB_URL" "$USB_TAR" "$USB_SHA"
tar xzf "$RTL_TAR"
tar xjf "$USB_TAR"

export SOURCE_DATE_EPOCH=1700000000
FLAGS="-O2 -mcrtdll=ucrt -ffile-prefix-map=$work=. -fno-ident"

# libusb, static, for linking into rtlsdr.dll only.
(cd libusb-1.0.26 && ./configure --host=$host --prefix="$work/usb" --enable-static --disable-shared \
    CC="$CC" CFLAGS="$FLAGS" >/dev/null && make -s -j"$(nproc)" >/dev/null 2>&1 && make -s install >/dev/null)

# librtlsdr: the library's own sources, as its CMakeLists builds rtlsdr_shared.
src=rtl-sdr-blog-1.3.6
"$CC" $FLAGS -shared -o rtlsdr.dll \
    -I"$src/include" -I"$work/usb/include/libusb-1.0" \
    "$src/src/librtlsdr.c" "$src/src/tuner_e4k.c" "$src/src/tuner_fc0012.c" "$src/src/tuner_fc0013.c" \
    "$src/src/tuner_fc2580.c" "$src/src/tuner_r82xx.c" \
    "$work/usb/lib/libusb-1.0.a" \
    -static-libgcc -Wl,-Bstatic -lwinpthread -Wl,-Bdynamic \
    -Wl,--exclude-libs,ALL -Wl,--no-insert-timestamp -s
install -m 644 rtlsdr.dll "$out/rtlsdr.dll"

# Only Windows' own DLLs and the UCRT may be needed: no msvcr*, no
# libgcc, no winpthread, no libusb beside it.
needs=$(objdump -p "$out/rtlsdr.dll" | sed -n 's/^\s*DLL Name: //p' | sort -u)
bad=$(printf '%s\n' "$needs" | grep -viE '^(kernel32|advapi32|user32|ole32|setupapi|api-ms-win-crt-[a-z0-9-]+)\.dll$' || true)
if [ -n "$bad" ]; then
    echo "build-rtlsdr-windows.sh: rtlsdr.dll needs more than Windows and the UCRT: $bad" >&2
    exit 1
fi
# Read once into a variable: `objdump | grep -q` under pipefail fails when
# grep stops reading early.
table=$(objdump -p "$out/rtlsdr.dll")
for fn in rtlsdr_open rtlsdr_read_sync rtlsdr_set_center_freq rtlsdr_get_tuner_gains; do
    grep -q "\b$fn\b" <<<"$table" || { echo "build-rtlsdr-windows.sh: $fn is not exported" >&2; exit 1; }
done
if grep -q "\blibusb_" <<<"$table"; then
    echo "build-rtlsdr-windows.sh: rtlsdr.dll exports libusb's functions" >&2
    exit 1
fi
(cd "$out" && sha256sum rtlsdr.dll | sed 's/ \*/  /' > SHA256SUMS)
echo "built $out/rtlsdr.dll ($(printf '%s ' $needs))"
cat "$out/SHA256SUMS"
