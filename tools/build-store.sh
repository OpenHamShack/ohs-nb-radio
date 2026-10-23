#!/bin/sh
# Build the OpenHamShack store package for QO-100 NB or Radio: a signed
# .d360mod carrying its container image, so a controller with no route out
# can install it (D12).
#
#   tools/build-store.sh qo100nb|radio [--allow-dirty]
#
# Environment:
#   SHACK_STORE_OUT   where the package goes (default ~/build/apps/shack-<app>)
#   SHACK_STAGE       scratch for the staged repository (default ~/build/m3-nb-radio/stage-<app>;
#                     never /tmp, a small shared tmpfs)
#   DOCK360_SRC       a tree of Dock360's feature/ohs-edition (default ~/build/m3-flex/dock360)
#   DOCK360_PY        a Python with Dock360's requirements (default ~/build/venvs/dock360/bin/python)
#   SHACK_MODULES_KEY the OpenHamShack modules signing key, read in place and never copied
#                     (default ~/.config/openhamshack/keys/ohs-modules.key)
#   OHSDIGI_WHEELS     the ohs-ohsdigi wheels tools/build-wheels.sh made (default ~/build/ohs-dist/ohsdigi)
#   SDRPLAY_DIST      Radio only: the SDRplay API installer and SoapySDRPlay3 source that
#                     tools/vendor/sdrplay.lock names (default ~/build/ohs-dist/sdrplay)
#   SHACK_STORE_DROP_SDRPLAY
#                     Radio only. 0 (the default): the image carries SDRplay's API and
#                     SoapySDRPlay3, as every Radio image has. 1: it carries neither, and
#                     the manifest asks for the controller's host library sdrplay-api
#                     instead (RADIO-SDR-PLAN 6.3). Leave it at 0 until the platform
#                     release with host libraries is on the controllers and sdrplay-api
#                     is installed there: an image built with 1 on a controller without
#                     it shows the RSP as needing SDRplay's API, and ohs-box loses its
#                     RSPdx. The plan's order is platform first, then this image.
#
# How: the module's tree - store/<app>/ at the top, with ohscore/, the app's
# package, its pad declarations, LICENSE and the pinned shared libraries
# beside it - is cut from HEAD with git archive (a package is exactly a
# commit; a dirty tree is refused unless --allow-dirty, and even then only
# committed files go in), committed into a scratch repository, and handed
# to ~/openhamshack-os/tools/package-app.sh, which builds the image from a
# fresh clone of it and signs the package, as every OpenHamShack app's is.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:-}
case "$APP" in
    qo100nb) PKG=ohsnb ;;
    radio) PKG=ohsradio ;;
    *) echo "usage: $0 qo100nb|radio [--allow-dirty]" >&2; exit 2 ;;
esac
ALLOW_DIRTY=0
[ "${2:-}" = "--allow-dirty" ] && ALLOW_DIRTY=1
OUT=${SHACK_STORE_OUT:-$HOME/build/apps/shack-$APP}
STAGE=${SHACK_STAGE:-$HOME/build/m3-nb-radio/stage-$APP}
DOCK360_SRC=${DOCK360_SRC:-$HOME/build/m3-flex/dock360}
export DOCK360_PY=${DOCK360_PY:-$HOME/build/venvs/dock360/bin/python}
KEY=${SHACK_MODULES_KEY:-$HOME/.config/openhamshack/keys/ohs-modules.key}
PACKAGER=${SHACK_PACKAGE_APP:-$HOME/openhamshack-os/tools/package-app.sh}
OHSDIGI_WHEELS=${OHSDIGI_WHEELS:-$HOME/build/ohs-dist/ohsdigi}
SDRPLAY_DIST=${SDRPLAY_DIST:-$HOME/build/ohs-dist/sdrplay}
DROP_SDRPLAY=${SHACK_STORE_DROP_SDRPLAY:-0}
case "$DROP_SDRPLAY" in 0|1) ;; *) echo "SHACK_STORE_DROP_SDRPLAY is 0 or 1" >&2; exit 2 ;; esac

cd "$ROOT"
if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git status --porcelain)" ]; then
    echo "The tree has uncommitted changes; commit them (or --allow-dirty to package HEAD anyway)." >&2
    exit 1
fi
[ -r "$KEY" ] || { echo "No signing key at $KEY" >&2; exit 1; }
COMMIT=$(git rev-parse --short=12 HEAD)

rm -rf "$STAGE"
mkdir -p "$STAGE"
git archive HEAD "store/$APP" | tar -x -C "$STAGE"
mv "$STAGE/store/$APP/"* "$STAGE/"
rm -rf "$STAGE/store"
git archive HEAD ohscore "$PKG" tools/vendor LICENSE | tar -x -C "$STAGE"
cp "$STAGE/$PKG/pad-actions.json" "$STAGE/$PKG/pad-layout.json" "$STAGE/"
# Not shipped: the window, its catalogs' sources, the developer's ohsdigi.
rm -rf "$STAGE/ohscore/ui" "$STAGE/$PKG/ui"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$STAGE/ohscore/"ohsdigi*.so "$STAGE/ohscore/"ohsdigi*.pyd "$STAGE/tools/vendor/shack_i18n-"*.whl
# ohsdigi, the decoder FT8, FT4 and HSmodem need, from the pinned wheels
# (tools/vendor/ohsdigi.lock). Up to 0.1.10-beta.1 nothing put it in the
# image: the line above removes a developer's own build and nothing took
# its place, so the store app listed FT8 and never decoded a slot. A
# missing or different wheel stops the build here; the Containerfile checks
# the hash again and makes the image prove its decoders load
# (python3 -m ohscore.selftest), so neither half can ship without the other.
for arch in x86_64 aarch64; do
    want=$(sed -n "s/^ohs-ohsdigi==.*--hash=sha256:\([0-9a-f]*\).*# $arch\$/\1/p" tools/vendor/ohsdigi.lock)
    # Chosen by the pinned hash, not by name: the folder keeps every
    # version still referenced by a published build (0.1.0 beside 0.2.0),
    # and taking the first name that matched picked 0.1.0 and stopped.
    whl=
    for f in "$OHSDIGI_WHEELS"/ohs_ohsdigi-*-manylinux_*_"$arch".whl; do
        [ -f "$f" ] && [ -n "$want" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$want" ] && { whl=$f; break; }
    done
    [ -n "$want" ] && [ -n "$whl" ] || { echo "No ohs-ohsdigi wheel for $arch in $OHSDIGI_WHEELS matches tools/vendor/ohsdigi.lock (tools/build-wheels.sh)" >&2; exit 1; }
    cp "$whl" "$STAGE/tools/vendor/"
done
# Radio's SDRplay receivers: SDRplay's API installer and the SoapySDRPlay3
# source, pinned by hash in tools/vendor/sdrplay.lock and never committed
# (the API is SDRplay's, not ours to put in a GPL repository). The
# Containerfile checks the hashes again; a missing or different file stops
# the build here, so a Radio image can never quietly lose the RSP.
if [ "$APP" = radio ] && [ "$DROP_SDRPLAY" = 1 ]; then
    # The switch-over (RADIO-SDR-PLAN 6.3): no SDRplay file in the image, the
    # service from the controller's host library. host_libraries is read
    # only by a platform that has the key; an older one refuses the module
    # outright rather than installing a Radio that cannot see the API.
    echo "build-store.sh: SHACK_STORE_DROP_SDRPLAY=1 - this Radio image carries no SDRplay API" >&2
    sed -i '/^# >>> sdrplay-in-image/,/^# <<< sdrplay-in-image/d' "$STAGE/Containerfile"
    if grep -q -e '--from=sdrplay' -e ' AS sdrplay' "$STAGE/Containerfile"; then
        echo "build-store.sh: the Containerfile still builds or copies SDRplay's files" >&2; exit 1
    fi
    sed -i 's/^  broker_devices: \[\(.*\)\]$/  broker_devices: [\1]\n  host_libraries: [sdrplay-api]/' "$STAGE/module.yaml"
    grep -q '^  host_libraries: \[sdrplay-api\]$' "$STAGE/module.yaml" \
        || { echo "build-store.sh: could not add host_libraries to module.yaml" >&2; exit 1; }
elif [ "$APP" = radio ]; then
    mkdir -p "$STAGE/sdrplay"
    grep -v '^#' tools/vendor/sdrplay.lock | while read -r want name; do
        f="$SDRPLAY_DIST/$name"
        if [ ! -f "$f" ] || [ "$(sha256sum "$f" | cut -d' ' -f1)" != "$want" ]; then
            echo "No $name in $SDRPLAY_DIST matching tools/vendor/sdrplay.lock (SDRplay publishes the installer; keep a copy beside the build)" >&2
            exit 1
        fi
        cp "$f" "$STAGE/sdrplay/"
    done
fi
echo "$COMMIT" > "$STAGE/$PKG/COMMIT"
git -C "$STAGE" init -q -b main
git -C "$STAGE" add -A
git -C "$STAGE" -c user.name="build-store" -c user.email="build@openhamshack.invalid" \
    commit -q -m "shack-$APP store package from openhamshack-nb $COMMIT"

"$PACKAGER" "$STAGE" . "$OUT" --key "$KEY" --dock360 "$DOCK360_SRC"
ls -l "$OUT"
