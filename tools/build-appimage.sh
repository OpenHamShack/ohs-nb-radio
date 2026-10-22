#!/bin/sh
# Build OpenHamShack QO-100 NB's or Radio's AppImage with the shared kit
# (ohs-libs packaging/appimage, inside Debian bookworm with podman, so it
# runs on any x86-64 Linux from Debian 12 / Ubuntu 22.04 on).
#
#   tools/build-appimage.sh nb|ham [--out DIR]
#
# Environment:
#   SHACK_KIT   the kit's packaging/ folder (default ~/ohs-libs/packaging; it
#               needs the "[pyinstaller] spec" support, ohs-libs 63f1004)
#   SHACK_WORK  scratch for the staged sources (default ~/build/m3-nb-radio/appimage-<app>;
#               never /tmp, a small shared tmpfs)
#
# The sources are one commit (git archive HEAD), never the working tree, with
# the pinned shared libraries unpacked beside them (packaging/shack_vendor.py,
# hash-checked). The frozen requirements are packaging/windows/requirements.txt's
# pins, less what is Windows-only, plus pylibiio for the Pluto (libiio
# itself, and Qt's xcb and the C libraries below it, are the host's).
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:-}
shift || true
case "$APP" in
    nb)  PKG=ohsnb; KIND=qo100nb; NAME="OpenHamShack QO-100 NB"; ICON=qo100-nb
         SUMMARY="QO-100 narrowband transceiver"; GUID="{5B0E6A3C-6F0B-4C41-9C1E-4A3B7E0C2D91}" ;;
    ham) PKG=ohsradio; KIND=radio; NAME="OpenHamShack Radio"; ICON=radio
         SUMMARY="All-band amateur radio SDR transceiver"; GUID="{6CB153AC-60F0-4FF0-8805-E27009992212}" ;;
    *) echo "usage: $0 nb|ham [--out DIR]" >&2; exit 2 ;;
esac
OUT=$(pwd)
if [ "${1:-}" = "--out" ]; then OUT=$(mkdir -p "$2" && cd "$2" && pwd); fi
KIT=${SHACK_KIT:-$HOME/ohs-libs/packaging}
WORK=${SHACK_WORK:-$HOME/build/m3-nb-radio/appimage-$APP}
VERSION=$(tr -d ' \t\r\n' < "$ROOT/$PKG/VERSION")

rm -rf "$WORK"
mkdir -p "$WORK/src"
cd "$ROOT"
git archive HEAD ohscore "$PKG" LICENSE | tar -x -C "$WORK/src"
mv "$WORK/src/LICENSE" "$WORK/LICENSE"
# x86-64 only (the kit's AppImages are), so that architecture's shack_sdr.
python3 "$ROOT/packaging/shack_vendor.py" "$WORK/src" linux_x86_64
find "$WORK/src" -maxdepth 1 -name '*.dist-info' -type d -exec rm -rf {} +
rm -rf "$WORK/src/shack_pad/udev"
cp "$ROOT/packaging/appimage/qt-app.spec" "$ROOT/packaging/appimage/host-libs.txt" "$WORK/"
# The pins every frozen build uses; PyAudio's Linux wheel is built from
# source against bookworm's PortAudio in the kit's container.
REQ=$(grep -E '^(numpy|PyQt6|PyQt6-Qt6|PyQt6-sip|PyAudio|pyserial|cryptography|cffi|pycparser)==' \
      "$ROOT/packaging/windows/requirements.txt" | sed 's/.*/"&"/' | paste -sd, -)
[ "$PKG" = ohsradio ] && REQ="$REQ,$(grep -E '^(paramiko|bcrypt|PyNaCl)==' "$ROOT/packaging/windows/requirements.txt" \
      | sed 's/.*/"&"/' | paste -sd, -)"
# numpy 2.5 needs Python 3.12; the kit's container is bookworm's 3.11 (for
# its glibc 2.36), so the AppImage takes 2.4.6, the newest for 3.11.
REQ=$(printf '%s' "$REQ" | sed 's/"numpy==[^"]*"/"numpy==2.4.6"/')
REQ="$REQ,\"pylibiio==0.25\""
sed -e "s|@KIND@|$KIND|g" -e "s|@NAME@|$NAME|" -e "s|@SUMMARY@|$SUMMARY|" -e "s|@EXE@|shack-$KIND|" \
    -e "s|@VERSION@|$VERSION|" -e "s|@PKG@|$PKG|" -e "s|@ICON@|$ICON|" -e "s|@GUID@|$GUID|" \
    -e "s|@REQUIREMENTS@|$REQ|" "$ROOT/packaging/appimage/app.toml.in" > "$WORK/shack-app.toml"

"$KIT/appimage/build-appimage.sh" "$WORK/shack-app.toml" --out "$OUT"

# Nothing encumbered inside (RADIO-SDR-PLAN 5.5), checked on what was just
# built. The check cannot read the AppImage's squashfs, so it reads the
# tree the AppImage unpacks itself to (--appimage-extract runs no part of
# the app). A finding deletes the AppImage.
appimage=$(ls -t "$OUT"/*.AppImage 2>/dev/null | head -n 1)
if [ -n "$appimage" ]; then
    rm -rf "$WORK/squashfs-root"
    (cd "$WORK" && "$appimage" --appimage-extract >/dev/null)
    if ! python3 "$ROOT/packaging/shack_vendor.py" --check-encumbered "$WORK/squashfs-root"; then
        rm -f "$appimage"
        echo "build-appimage.sh: the AppImage failed the encumbered check" >&2
        exit 1
    fi
    rm -rf "$WORK/squashfs-root"
fi
