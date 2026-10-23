#!/bin/sh
# Check a built QO-100 NB or Radio store image the way the controller runs
# it - read-only root, every capability dropped, /tmp a tmpfs, its own
# user - for the one thing 0.1.10-beta.1 got wrong: every decoder the app
# offers loads, and FT8 and FT4 decode a slot, RTTY a message through
# shack_sdr (python3 -m ohscore.selftest). Then that nothing encumbered is
# in the image (below).
#
#   tools/store-check.sh qo100nb|radio [image]
#       (default image localhost/dock360-shack-<app>:<store/<app>/module.yaml version>,
#        the tag ~/openhamshack-os/tools/package-app.sh builds it under)
#
# The Containerfile runs the same check at build time, so an image that
# fails it should never exist; this is for an image someone already has -
# one loaded from a package, or built before the check was added - and
# for the release checklist, which runs it after tools/build-store.sh.
# The entrypoint is replaced (podman run does not replace ENTRYPOINT with
# a command; GUIDE §5), so no server starts, no radio is opened and nothing
# can be keyed. Exits non-zero when the check fails.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP=${1:-}
case "$APP" in
    qo100nb) PKG=ohsnb ;;
    radio) PKG=ohsradio ;;
    *) echo "usage: $0 qo100nb|radio [image]" >&2; exit 2 ;;
esac
VERSION=$(sed -n 's/^version: *//p' "$ROOT/store/$APP/module.yaml" | head -1)
IMAGE=${2:-localhost/dock360-shack-$APP:$VERSION}

podman run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
    --entrypoint python3 -w "/opt/shack-$APP" "$IMAGE" -m ohscore.selftest "$PKG"

# Nothing encumbered in the image (RADIO-SDR-PLAN 5.5): no AAC or AMBE
# codec, and no Debian package of one, anywhere in its filesystem - checked
# by ohs-libs' own tool (vendored, hash-checked) over an export of the
# image, never by anything run inside it.
#
# One exception: a Radio image built the old way (SHACK_STORE_DROP_SDRPLAY=0,
# tools/build-store.sh) still carries SDRplay's API and SoapySDRPlay3. For
# such an image alone the API's own files and symbols are left out of the
# denylist, and this says so. Radio's default image since 23/10/2026 carries
# none (the controller lends the API as a host library, RADIO-SDR-PLAN 6.3)
# and is checked against the whole list, as is NB's, and also for any
# SoapySDRPlay3 module left behind.
SDRPLAY_SKIP=""
if [ "$APP" = radio ] && podman run --rm --entrypoint test "$IMAGE" -e /usr/local/bin/sdrplay_apiService; then
    SDRPLAY_SKIP="libsdrplay_api* sdrplay_api*.dll sdrplay_apiService* sdrplay_api_*"
    echo "store-check: this Radio image still carries SDRplay's API (RADIO-SDR-PLAN 6.3); its files are not counted" >&2
fi
EXPORT=$(mktemp -d "${SHACK_STAGE_TMP:-$HOME/build}/store-check-XXXXXX")
trap 'rm -rf "$EXPORT"' EXIT
ctr=$(podman create --entrypoint true "$IMAGE")
podman export "$ctr" | tar -x -C "$EXPORT" 2>/dev/null || true
podman rm "$ctr" >/dev/null
if [ "$APP" = radio ] && [ -z "$SDRPLAY_SKIP" ]; then
    left=$(find "$EXPORT" \( -iname 'libsdrPlaySupport*' -o -name 'sdrplay_api*.h' -o -name 'libsdrplay_api*' \) -print)
    if [ -n "$left" ]; then
        echo "store-check: an image without SDRplay's API still carries SDRplay files:" >&2
        echo "$left" >&2
        exit 1
    fi
    echo "store-check: no SDRplay API or SoapySDRPlay3 in the image (host library sdrplay-api)" >&2
fi
python3 - "$ROOT" "$EXPORT" $SDRPLAY_SKIP <<'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "packaging"))
import shack_vendor
root, tree, skip = Path(sys.argv[1]), Path(sys.argv[2]), tuple(sys.argv[3:])
sys.exit(shack_vendor.encumbered(root, [tree, "--dpkg-root", tree], skip=skip))
EOF
