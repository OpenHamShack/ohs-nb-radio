#!/bin/bash
# Record real air on the controller's receiver and run a decoder's real-file
# test on it, from shack, with no session relaying messages.
#
#   tools/capture-and-test.sh --yes-receiver [--drop-sessions] [--rate S/s]
#       [--antenna A|B|C] [--keep-on-box] [--no-test]
#       <dmr|ais|adsb|dab> <freqHz> <seconds>
#
# Why: until 28/10 a real-signal check was a session asking Brian, an agent
# writing a one-off script onto the box (/var/tmp/dmrcapture.py), and
# another relaying the file back - an hour of round trips for a minute of
# IQ. This is that script, made once, with the safety it lacked written in.
#
# The receiver is Brian's. Nothing happens without --yes-receiver, which
# means "Brian has agreed that this capture may take his receiver now"; and
# even then it refuses while something holds the receiver (rxOwner: a DAB
# station, the AIS or ADS-B map) unless --drop-sessions says that may be
# stopped too (it is not started again afterwards; a map client starts its
# own session again). --drop-sessions also lets the tune stop background
# decoder sessions that pin the span, which leave the saved sessions for
# good (SERVER-API "The pinned span"). It never transmits, and refuses while
# the radio is on the air. A dropped holder is stopped before anything is
# saved, and the dial is read only once rxOwner is empty again: an ended
# AIS or ADS-B session keeps the receiver for its linger (60 s), and read
# during it "before" would be the session's 162 MHz. Each wait for the
# receiver to come back (there, and after its own session) allows 90 s.
#
# On the box (BOX_HOST in ~/.config/openhamshack/box-update.conf; this
# repository is public) tools/box_api.py does the work as root with the
# controller's local-screen token, which stays there: it saves the dial,
# mode and antenna (and the sample rate, with --rate), tunes - dmr: the
# dial, FM; dab: a DAB session on the block, which centres the receiver;
# ais/adsb: their map sessions, which set the centre and (ADS-B) the rate
# themselves - records IQ for <seconds>, and restores everything, checking
# it did. It runs under ssh -tt, so Ctrl-C here is Ctrl-C there and the
# restore runs; a dropped connection (SIGHUP) restores too.
#
# Then the recording (.sigmf-data and .sigmf-meta) is copied to
# ~/build/real-<decoder>/<recording id>/, each file's size and sha256
# checked against the box's own, and deleted from the box (--keep-on-box
# keeps it in the app's Recordings). A folder per capture, so the test
# reads this capture and not every one before it. A dmr capture gets a
# <id>.channel naming <freqHz>, which dmr_real mixes down to.
#
# Last, in ~/ohs-libs (OHS_LIBS) rust/, the decoder's ignored real-file
# test with its folder variable (dmr_real: SHACK_DMR_DIR; ais real_air:
# SHACK_AIS_DIR; adsb_real: SHACK_ADSB_DIR; dab_tii_real list_every_file:
# SHACK_DAB_DIR); its other variables (SHACK_AIS_MIN, SHACK_DMR_SECONDS)
# pass through from this environment. The whole output goes to test.log in
# the folder; this prints a ten-line summary.
#
# Exit status: 0 captured, restored and the test passed; 1 a failure (the
# summary says which); 2 a usage or refusal before anything changed; 3 the
# box refused (on the air, receiver held); 4 the receiver was NOT put back
# exactly (the summary names what differs - fix it before anything else);
# 130 interrupted (restored).
#
# OHS_BOX_LOCAL=1 runs the box half on this host with no ssh or sudo, for
# the tests (with OHS_API_ROOT, OHS_TOKEN_FILE and CAPTURE_RECORDINGS_DIR
# pointing at a fake controller); never set it otherwise.
set -uo pipefail

usage() {
    echo "usage: $0 --yes-receiver [--drop-sessions] [--rate S/s] [--antenna A|B|C] [--keep-on-box] [--no-test] <dmr|ais|adsb|dab> <freqHz> <seconds>" >&2
    exit 2
}

YES=0 DROP=0 RATE= ANT= KEEP=0 TEST=1
while [ $# -gt 0 ]; do
    case $1 in
        --yes-receiver) YES=1 ;;
        --drop-sessions) DROP=1 ;;
        --keep-on-box) KEEP=1 ;;
        --no-test) TEST=0 ;;
        --rate) RATE=${2:-}; shift ;;
        --antenna) ANT=${2:-}; shift ;;
        -*) usage ;;
        *) break ;;
    esac
    shift
done
[ $# -eq 3 ] || usage
DEC=$1 FREQ=$2 SECS=$3
case $DEC in
    dmr) VAR=SHACK_DMR_DIR T="--test dmr_real recordings_of_local_repeaters" ;;
    ais) VAR=SHACK_AIS_DIR T="--test ais real_air" ;;
    adsb) VAR=SHACK_ADSB_DIR T="--test adsb_real real_recordings" ;;
    dab) VAR=SHACK_DAB_DIR T="--test dab_tii_real list_every_file" ;;
    *) echo "capture-and-test: unknown decoder '$DEC' (dmr, ais, adsb or dab)" >&2; exit 2 ;;
esac
[[ $FREQ =~ ^[1-9][0-9]{5,9}$ ]] || { echo "capture-and-test: <freqHz> must be a whole number of Hz, e.g. 430900000" >&2; exit 2; }
[[ $SECS =~ ^[1-9][0-9]{0,2}$ ]] && [ "$SECS" -le 600 ] \
    || { echo "capture-and-test: <seconds> must be 1-600 (Radio stops an IQ recording at 10 minutes)" >&2; exit 2; }
if [ -n "$RATE" ]; then
    # 2400000, or 2.4M / 2.4e6 for the same
    RATE=$(python3 -c 'import sys
s = sys.argv[1].upper().rstrip("S/").replace("M", "e6").replace("K", "e3")
r = float(s)
assert 48e3 <= r <= 20e6 and r == int(r)
print(int(r))' "$RATE" 2>/dev/null) || { echo "capture-and-test: --rate must be a sample rate, 48000 to 20000000 S/s" >&2; exit 2; }
    [ "$DEC" != adsb ] || { echo "capture-and-test: ADS-B sets its own rate (6 MS/s on an RSP); leave out --rate" >&2; exit 2; }
fi
case $ANT in
    "") ;;
    A|B|C) ANT="Antenna $ANT" ;;
    *) echo "capture-and-test: --antenna must be A, B or C" >&2; exit 2 ;;
esac

if [ $YES = 0 ]; then
    cat >&2 <<EOF
capture-and-test: refused. The receiver belongs to Brian: this tunes it away
from whatever he is listening to for $SECS s (and back after). Pass
--yes-receiver only when Brian has agreed to this capture taking it now.
EOF
    exit 2
fi

LOCAL=${OHS_BOX_LOCAL:-0}
if [ "$LOCAL" = 1 ]; then
    BOX_HOST=local
    RECDIR=${CAPTURE_RECORDINGS_DIR:?CAPTURE_RECORDINGS_DIR must name the fake controller recordings}
else
    CONF=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
    [ -r "$CONF" ] || { echo "capture-and-test: no config at $CONF" >&2; exit 2; }
    # shellcheck disable=SC1090
    source "$CONF"
    [ -n "${BOX_HOST:-}" ] || { echo "capture-and-test: $CONF must set BOX_HOST" >&2; exit 2; }
    RECDIR=/var/lib/dock360/modules/shack-radio/data/recordings
fi
LIBS=${OHS_LIBS:-$HOME/ohs-libs}
CARGO=${CARGO:-$(command -v cargo || echo "$HOME/.cargo/bin/cargo")}
REPO=$(cd "$(dirname "$0")/.." && pwd)

# The box half. A script on stdin through `sudo sh -s`, so nothing needs
# quoting twice; ssh's "Could not chdir to home directory" (the box has no
# home for this account) is dropped.
box_run() {
    if [ "$LOCAL" = 1 ]; then sh -s <<<"$1"; else ssh -T "$BOX_HOST" sudo sh -s <<<"$1" 2> >(grep -v chdir >&2); fi
}
box_put() {
    if [ "$LOCAL" = 1 ]; then cp "$1" "$2"; else ssh -T "$BOX_HOST" "cat > $2" < "$1" 2> >(grep -v chdir >&2); fi
}
# -tt: a terminal on the box, so Ctrl-C here reaches box_api.py as SIGINT.
box_py() {
    if [ "$LOCAL" = 1 ]; then
        python3 "$@"
    else
        local q="" x
        for x in "$@"; do q="$q $(printf '%q' "$x")"; done
        # The box's "Could not chdir to home directory" arrives on the
        # terminal's stdout under -tt, so it is filtered there; the status
        # is ssh's (the helper's), not grep's.
        ssh -tt -q "$BOX_HOST" "sudo python3$q" | grep --line-buffered -v 'Could not chdir'
        return "${PIPESTATUS[0]}"
    fi
}

if [ "$LOCAL" = 1 ]; then
    mkdir -p "$HOME/build/tmp"
    BOXTMP=$(mktemp -d "$HOME/build/tmp/capture-box.XXXXXX")
else
    # Made as this account (so the helper can be copied in), 0700; the
    # helper, as root, writes its result and log beside itself.
    BOXTMP=/var/tmp/ohs-capture-$$
    ssh -T "$BOX_HOST" "mkdir -m 700 $BOXTMP" 2> >(grep -v chdir >&2) \
        || { echo "capture-and-test: cannot reach $BOX_HOST" >&2; exit 1; }
fi
cleanup() { box_run "rm -rf $BOXTMP" >/dev/null 2>&1; }
trap cleanup EXIT
box_put "$REPO/tools/box_api.py" "$BOXTMP/box_api.py" || { echo "capture-and-test: cannot copy the helper to $BOX_HOST" >&2; exit 1; }

echo "capture-and-test: $DEC at $FREQ Hz for $SECS s on $BOX_HOST${ANT:+, $ANT}${RATE:+, $RATE S/s}"
args=(capture --prefix radio --decoder "$DEC" --freq "$FREQ" --seconds "$SECS" --result "$BOXTMP/result.json" --log "$BOXTMP/capture.log")
[ -n "$RATE" ] && args+=(--rate "$RATE")
[ -n "$ANT" ] && args+=(--antenna "$ANT")
[ $DROP = 1 ] && args+=(--drop-sessions)
[ $KEEP = 1 ] && args+=(--keep)
box_py "$BOXTMP/box_api.py" "${args[@]}"
RC=$?
RESULT=$(box_run "cat $BOXTMP/result.json" 2>/dev/null)
field() {
    python3 -c 'import json, sys
v = json.loads(sys.argv[1] or "{}").get(sys.argv[2])
print("" if v is None else v if isinstance(v, (str, int, float)) else json.dumps(v))' "$RESULT" "$1"
}
RESTORED=$(field restored)
if [ $RC != 0 ]; then
    echo "capture-and-test: the capture did not complete (rc $RC); see the lines above"
    if [ "$(field untouched)" = True ]; then
        echo "nothing on the receiver was changed"
    elif [ "$RESTORED" = True ]; then
        echo "receiver restored: $(field before)"
    else
        echo "RECEIVER NOT RESTORED: $(field notRestored) - put it back by hand"
        RC=4
    fi
    exit $RC
fi

ID=$(field id)
[[ $ID =~ ^[A-Za-z0-9._+-]+$ ]] || { echo "capture-and-test: the box named no usable recording id ('$ID')" >&2; exit 1; }
OUT=$HOME/build/real-$DEC/$ID
mkdir -p "$OUT"
box_run "cat $BOXTMP/capture.log" > "$OUT/capture.log" 2>/dev/null

# Copied, then checked against what the box itself measures: a short copy
# (ssh dropped, disk full here) must never reach the test as a real capture.
for part in meta data; do
    f="$RECDIR/$ID.sigmf-$part"
    read -r want_size want_sha <<<"$(box_run "stat -c %s '$f' && sha256sum '$f' | cut -d' ' -f1" | tr '\n' ' ')"
    [ -n "$want_sha" ] || { echo "capture-and-test: $f is not on the box" >&2; exit 1; }
    box_run "cat '$f'" > "$OUT/$ID.sigmf-$part"
    got_size=$(stat -c %s "$OUT/$ID.sigmf-$part")
    got_sha=$(sha256sum "$OUT/$ID.sigmf-$part" | cut -d' ' -f1)
    if [ "$got_size" != "$want_size" ] || [ "$got_sha" != "$want_sha" ]; then
        echo "capture-and-test: $ID.sigmf-$part copied wrong ($got_size B $got_sha, the box has $want_size B $want_sha); left on the box" >&2
        exit 1
    fi
    [ $part = data ] && DATA_SIZE=$got_size DATA_SHA=$got_sha
done
[ "$DEC" = dmr ] && echo "$FREQ" > "$OUT/$ID.channel"
if [ $KEEP = 1 ]; then
    WHERE="kept on the box too"
elif box_py "$BOXTMP/box_api.py" delete --prefix radio "$ID" >/dev/null; then
    WHERE="deleted from the box"
else
    WHERE="NOT deleted from the box (delete it in Recordings)"
fi

TRES="test: not run (--no-test)"
TAIL=""
if [ $TEST = 1 ]; then
    # shellcheck disable=SC2086
    (cd "$LIBS/rust" && env "$VAR=$OUT" "$CARGO" test --release -p shack_sdr $T -- --ignored --nocapture) > "$OUT/test.log" 2>&1
    TRC=$?
    name=${T#--test }
    if [ $TRC = 0 ]; then TRES="test $name: PASS"; else TRES="test $name: FAIL (rc $TRC)"; RC=1; fi
    TAIL=$(grep -v -e '^\s*$' -e '^\s*Compiling' -e '^\s*Finished' -e '^\s*Running' "$OUT/test.log" | tail -5)
fi

echo "$DEC $FREQ Hz, $SECS s: recording $ID, centre $(field centreHz) Hz at $(field rateHz) S/s"
echo "copied $DATA_SIZE B, sha256 ${DATA_SHA:0:16}… matches the box; $WHERE"
echo "receiver restored: $(field before)"
echo "folder: $OUT"
echo "$TRES"
[ -n "$TAIL" ] && printf '%s\n' "$TAIL"
exit $RC
