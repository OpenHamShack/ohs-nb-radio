#!/bin/sh
# Check a built QO-100 NB or Radio store image the way the controller runs
# it - read-only root, every capability dropped, /tmp a tmpfs, its own
# user - for the one thing 0.1.10-beta.1 got wrong: every decoder the app
# offers loads, and FT8 and FT4 decode a slot (python3 -m ohscore.selftest).
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
