#!/bin/bash
# After a store install: is the app on the box really up, and did it come up
# clean? store-release.sh runs this after box-store-update.sh; run it alone
# after an install made by hand.
#
#   tools/store-post-install.sh [--since "YYYY-MM-DD HH:MM:SS"] [--version V] [--smoke FILE] <radio|qo100nb>
#
# Why: Store Radio 0.1.22-beta.15 installed "fine" - box-store-update.sh
# said DONE - and then segfaulted in _ctypes when an ADS-B session reopened
# the RSPdx (the kernel's "segfault" and the unit's "status=139" on
# 28/10 09:38, the two lines check 2 looks for). Every step of an install
# can pass while the app it installed is crashing.
#
# On the box (BOX_HOST in ~/.config/openhamshack/box-update.conf), as root:
#   1. the module is "active" in `dock360ctl module list` (waiting up to
#      POST_INSTALL_WAIT_S, default 120 s, for it to get there);
#   2. its journal since --since (the box's clock; default the last 15
#      minutes) has no "status=139" (a container ended by SIGSEGV) or
#      "segfault", and no Traceback at error level; the kernel's journal
#      over the same time has no "segfault" either (a crash in the
#      container's process is logged there, not in the unit's);
#   3. the in-container selftest passes (python3 -m ohscore.selftest, in
#      the running container, as the build ran it in the image: it opens
#      no radio, sound card or network);
#   4. if there is a smoke list - --smoke FILE, else store/<app>/smoke.json
#      in this checkout - each check in it answers, through the controller's
#      local-screen token, which tools/box_api.py reads on the box and never
#      sends back: {"checks": [{"get": "api/status", "keys": ["app", ...]},
#      {"get": "api/ais/vessels"}]}. GET only: a smoke check never changes
#      the radio.
#
# Any failure notifies Brian's phone (~/.config/claude-account/notify, if
# there) and prints the rollback command box-store-update.sh left
# (/var/backups/ohs-store-rollback/<module>/rollback-<module>-<version>.sh).
# It never rolls back by itself: a crash may be the hardware or the air,
# and only Brian decides to take a version off his box. Exit 0 all passed,
# 1 a check failed, 2 usage.
#
# OHS_BOX_LOCAL=1 runs the box half here with no ssh or sudo (the tests
# put fake dock360ctl, journalctl and podman on PATH and point
# OHS_API_ROOT at a fake controller); never set it otherwise.
set -uo pipefail

usage() { echo "usage: $0 [--since 'YYYY-MM-DD HH:MM:SS'] [--version V] [--smoke FILE] <radio|qo100nb>" >&2; exit 2; }

SINCE= VERSION= SMOKE=
while [ $# -gt 0 ]; do
    case $1 in
        --since) SINCE=${2:-}; shift ;;
        --version) VERSION=${2:-}; shift ;;
        --smoke) SMOKE=${2:-}; shift ;;
        -*) usage ;;
        *) break ;;
    esac
    shift
done
[ $# -eq 1 ] || usage
APP=$1
case $APP in
    radio) PKG=ohsradio ;;
    qo100nb) PKG=ohsnb ;;
    *) echo "store-post-install: unknown app '$APP' (radio or qo100nb)" >&2; exit 2 ;;
esac
MODULE=shack-$APP
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ -n "$VERSION" ] || VERSION=$(sed -n 's/^version: *//p' "$REPO/store/$APP/module.yaml")
[[ $VERSION =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]*$ ]] || { echo "store-post-install: bad version '$VERSION'" >&2; exit 2; }
if [ -n "$SINCE" ]; then
    [[ $SINCE =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}$ ]] || { echo "store-post-install: --since must be 'YYYY-MM-DD HH:MM:SS'" >&2; exit 2; }
else
    SINCE="-15min"
fi
[ -n "$SMOKE" ] || { [ -f "$REPO/store/$APP/smoke.json" ] && SMOKE=$REPO/store/$APP/smoke.json; }
[ -z "$SMOKE" ] || [ -r "$SMOKE" ] || { echo "store-post-install: cannot read $SMOKE" >&2; exit 2; }
WAIT=${POST_INSTALL_WAIT_S:-120}
[[ $WAIT =~ ^[0-9]+$ ]] || { echo "store-post-install: POST_INSTALL_WAIT_S must be seconds" >&2; exit 2; }

LOCAL=${OHS_BOX_LOCAL:-0}
if [ "$LOCAL" = 1 ]; then
    BOX_HOST=local
else
    CONF=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
    [ -r "$CONF" ] || { echo "store-post-install: no config at $CONF" >&2; exit 2; }
    # shellcheck disable=SC1090
    source "$CONF"
    [ -n "${BOX_HOST:-}" ] || { echo "store-post-install: $CONF must set BOX_HOST" >&2; exit 2; }
fi
box_run() {
    if [ "$LOCAL" = 1 ]; then sh -s; else ssh -T "$BOX_HOST" sudo sh -s 2> >(grep -v chdir >&2); fi
}
notify() {
    local n=$HOME/.config/claude-account/notify
    [ -x "$n" ] && "$n" "$1" >/dev/null 2>&1
    true
}

echo "== post-install checks: $MODULE $VERSION on $BOX_HOST, journal since $SINCE"
# One script on the box. Values go in as shell assignments at its top,
# each already validated above, so nothing in them is ever parsed twice.
OUT=$( { cat <<EOF
M='$MODULE' APP='$APP' PKG='$PKG' SINCE='$SINCE' WAIT='$WAIT'
EOF
cat <<'EOF'
bad=0
state() { dock360ctl module list 2>/dev/null | awk -v m="$M" '$1 == m { print $3 }'; }
n=0
while [ "$(state)" != active ] && [ $n -lt "$WAIT" ]; do sleep 3; n=$((n + 3)); done
s=$(state)
if [ "$s" = active ]; then echo "ok   active"; else echo "FAIL not active (${s:-not installed})"; bad=$((bad + 1)); fi
u=dock360-$M.service
hits=$( { journalctl _SYSTEMD_USER_UNIT=$u + USER_UNIT=$u --since "$SINCE" --no-pager -o short-iso 2>/dev/null | grep -E 'status=139|segfault'
         journalctl _SYSTEMD_USER_UNIT=$u + USER_UNIT=$u --since "$SINCE" --no-pager -o short-iso -p err 2>/dev/null | grep 'Traceback'
         journalctl -k --since "$SINCE" --no-pager -o short-iso 2>/dev/null | grep 'segfault'; } | head -5)
if [ -z "$hits" ]; then echo "ok   journal clean"; else echo "FAIL journal:"; echo "$hits" | sed 's/^/       /'; bad=$((bad + 1)); fi
U=$(id -u dock360 2>/dev/null)
if st=$(sudo -u dock360 env XDG_RUNTIME_DIR=/run/user/$U podman exec -w /opt/shack-$APP dock360-$M python3 -m ohscore.selftest $PKG 2>&1); then
    echo "ok   selftest"
else
    echo "FAIL selftest:"; echo "$st" | tail -5 | sed 's/^/       /'; bad=$((bad + 1))
fi
echo "CHECKS $bad"
EOF
} | box_run)
echo "$OUT" | grep -v '^CHECKS '
BAD=$(sed -n 's/^CHECKS //p' <<<"$OUT")
[ -n "$BAD" ] || { echo "FAIL the checks did not run on $BOX_HOST"; BAD=1; }

if [ -n "$SMOKE" ]; then
    if [ "$LOCAL" = 1 ]; then
        python3 "$REPO/tools/box_api.py" smoke --prefix "$APP" "$SMOKE" || BAD=$((BAD + 1))
    else
        T=/var/tmp/ohs-smoke-$$
        ssh -T "$BOX_HOST" "mkdir -m 700 $T && cat > $T/box_api.py" < "$REPO/tools/box_api.py" 2> >(grep -v chdir >&2)
        ssh -T "$BOX_HOST" "cat > $T/smoke.json" < "$SMOKE" 2> >(grep -v chdir >&2)
        ssh -T "$BOX_HOST" "sudo python3 $T/box_api.py smoke --prefix $APP $T/smoke.json" 2> >(grep -v chdir >&2) \
            | sed 's/^[0-9:]* //' || BAD=$((BAD + 1))
        ssh -T "$BOX_HOST" "rm -rf $T" 2>/dev/null
    fi
fi

if [ "$BAD" != 0 ]; then
    RB="ssh $BOX_HOST sudo /var/backups/ohs-store-rollback/$MODULE/rollback-$MODULE-$VERSION.sh"
    echo "POST-INSTALL CHECKS FAILED for $MODULE $VERSION. Not rolled back; to go back:"
    echo "  $RB"
    notify "Store $APP $VERSION installed but its checks FAILED on $BOX_HOST. Rollback: $RB"
    exit 1
fi
echo "post-install checks passed"
