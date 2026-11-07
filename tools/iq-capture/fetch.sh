#!/bin/bash
# Collect one finished IQ capture from the controller:
#
#   fetch.sh <name>
#
# copies /var/lib/ohs-iq/<name>/ (the cut-down parts, their metadata and
# capture.json) and the capture's log into ~/naughtcade-private/iq/<name>/
# on this host, checks every file's size and sha256 against what the box
# itself measures, and only then removes the box's copy. The recordings
# are private (Naughtcade's calibration material, never distributed), so
# the folders are 0700 and the files 0600, and nothing goes through a
# shared /tmp.
#
# Run by ohs-iq-fetch@<name>.service from a user timer at 22:30 UTC on the
# capture's date (deploy.sh installs it), or by hand. If the capture is
# still running or still cutting its last part down, it waits, checking
# every 5 minutes for up to 3 hours. A failure leaves the box's copy alone
# and, where this host has it, posts to Brian's phone.
#
# The controller is BOX_HOST in ~/.config/openhamshack/box-update.conf
# (this repository is public); sudo there is passwordless.
#
# Exit status: 0 fetched and removed from the box; 1 failed (the box's copy
# is kept); 2 bad arguments or no configuration.
set -uo pipefail
umask 077

NAME=${1:-}
[[ $NAME =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$ ]] || { echo "usage: $0 <capture name>" >&2; exit 2; }
CONF=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
[ -r "$CONF" ] || { echo "fetch: no config at $CONF" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONF"
[ -n "${BOX_HOST:-}" ] || { echo "fetch: $CONF must set BOX_HOST" >&2; exit 2; }
WAIT_S=${OHS_IQ_FETCH_WAIT_S:-300}
WAIT_TRIES=${OHS_IQ_FETCH_TRIES:-36}

# Only the tests (tests/test_iq_capture.py) move these, to scratch folders.
SRC=${OHS_IQ_BOX_ROOT:-/var/lib/ohs-iq}/$NAME
BOXLOG=${OHS_IQ_BOX_LOG_DIR:-/var/log/ohs-iq-capture}/$NAME.log
TOP=$HOME/naughtcade-private
DEST=$TOP/iq/$NAME

say() { echo "$(date -u +%FT%TZ) fetch $NAME: $*"; }
fail() {
    say "FAILED: $*; the box's copy is kept"
    [ -x "$HOME/.config/claude-account/notify" ] \
        && "$HOME/.config/claude-account/notify" "IQ capture $NAME: fetch failed - $*" >/dev/null 2>&1
    exit 1
}
# The box's "Could not chdir to home directory" (no home for this account) is dropped.
box() { ssh -T -o BatchMode=yes "$BOX_HOST" "$@" 2> >(grep -v chdir >&2); }
# Each stdin-free call is given /dev/null: ssh would otherwise swallow the
# file list the copy loop is reading.

# Finished means capture.json is there and the service is not running
# (it writes capture.json last, after the final cut-down).
for (( i = 1; ; i++ )); do
    state=$(box "sudo systemctl is-active ohs-iq-capture@$NAME.service; sudo test -f $SRC/capture.json && echo has-status" < /dev/null)
    [ $? = 255 ] && state="unreachable"
    case $state in
        *has-status*) [[ $state == active* || $state == activating* ]] || break ;;
    esac
    [ $i -ge "$WAIT_TRIES" ] && fail "the capture has not finished (${state//$'\n'/, })"
    say "not finished yet (${state//$'\n'/, }); looking again in $WAIT_S s"
    sleep "$WAIT_S"
done
say "capture status: $(box "sudo cat $SRC/capture.json" < /dev/null | python3 -c 'import json, sys
d = json.load(sys.stdin)
print(d.get("status"), len(d.get("parts") or []), "part(s), receiver restored:", d.get("restored"))' 2>/dev/null)"

mkdir -p "$DEST" && chmod 700 "$TOP" "$TOP/iq" "$DEST"
# size, sha256 and name of every file, as the box measures them
listing=$(box sudo sh -s <<EOF
cd '$SRC' || exit 1
for f in *; do
    [ -f "\$f" ] || continue
    printf '%s %s %s\n' "\$(stat -c %s "\$f")" "\$(sha256sum < "\$f" | cut -d' ' -f1)" "\$f"
done
EOF
) || fail "cannot list $SRC on the box"
[ -n "$listing" ] || fail "$SRC is empty"
n=0 bytes=0
while read -r size sha f; do
    [[ $f =~ ^[A-Za-z0-9._-]+$ ]] || fail "unexpected file name '$f'"
    box "sudo cat '$SRC/$f'" < /dev/null > "$DEST/$f.partial" || fail "copying $f"
    got_size=$(stat -c %s "$DEST/$f.partial")
    got_sha=$(sha256sum < "$DEST/$f.partial" | cut -d' ' -f1)
    if [ "$got_size" != "$size" ] || [ "$got_sha" != "$sha" ]; then
        fail "$f copied wrong ($got_size B ${got_sha:0:12}, the box has $size B ${sha:0:12})"
    fi
    chmod 600 "$DEST/$f.partial" && mv "$DEST/$f.partial" "$DEST/$f"
    n=$(( n + 1 )) bytes=$(( bytes + size ))
done <<<"$listing"
box "sudo cat $BOXLOG" < /dev/null > "$DEST/capture.log" 2>/dev/null && chmod 600 "$DEST/capture.log"
say "copied $n file(s), $bytes B, sizes and sha256 match the box"

box "sudo rm -rf -- '$SRC'" || fail "removing $SRC from the box"
say "removed $SRC from the box; the log stays there ($BOXLOG)"
