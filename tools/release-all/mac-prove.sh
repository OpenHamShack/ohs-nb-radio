#!/bin/bash
# On the Mac, after build-macos.sh --sign: the release image checked as a
# user gets it (macos.sh runs it from the release commit's own tree).
#
#   mac-prove.sh <dmg> <App Name> <executable> <version> <scratch folder>
#
# The .app is copied out of the image into the scratch folder (never
# ~/Applications: another session keeps a test copy there) and given the
# quarantine flag a browser download carries, so Gatekeeper judges it as
# it would a downloaded copy. Then: spctl must accept it as notarised
# Developer ID, the image's stapled ticket must validate, and the program must run
# headless on the simulator, receive-only (it cannot transmit; there is no
# radio here), name this version and exit cleanly. Ends with MACPROVE PASS
# or MACPROVE FAIL: <what>.
# No set -u: the Mac's bash is 3.2, where an empty array counts as unset.
DMG=$1 NAME=$2 EXE=$3 V=$4 W=$5
bad=()
rm -rf "$W/$NAME.app"; mkdir -p "$W"
MP=$(mktemp -d "${TMPDIR:-/tmp}/ohsprove.XXXX")
hdiutil attach -nobrowse -readonly -mountpoint "$MP" "$DMG" >/dev/null || { echo "MACPROVE FAIL: cannot attach $DMG"; exit 1; }
ditto "$MP/$NAME.app" "$W/$NAME.app"
hdiutil detach "$MP" >/dev/null; rmdir "$MP"
xattr -w com.apple.quarantine "0081;$(printf %x "$(date +%s)");Safari;" "$W/$NAME.app"

gk=$(spctl -a -vv "$W/$NAME.app" 2>&1); echo "$gk"
grep -q "accepted" <<< "$gk" && grep -q "Notarized Developer ID" <<< "$gk" || bad+=("spctl did not accept it as notarised Developer ID")
codesign -dv "$W/$NAME.app" 2>&1 | grep -E "Authority=Developer|TeamIdentifier|Identifier="
# The ticket is stapled to the image (build-macos.sh staples the .dmg),
# which is what a user downloads; the .app inside carries none of its own.
st=$(xcrun stapler validate "$DMG" 2>&1 | tail -1); echo "$st"
grep -q "worked" <<< "$st" || bad+=("the image has no valid stapled ticket")

C=$W/conf-$EXE; rm -rf "$C"; mkdir -p "$C"
case $EXE in *nb) P=OHS_NB ;; *) P=OHS_RADIO ;; esac
env "${P}_CONF=$C/config.json" "${P}_DATA=$C/data" SHACK_NO_WSJTX=1 QT_QPA_PLATFORM=offscreen \
    "$W/$NAME.app/Contents/MacOS/$EXE" --headless --device sim --receive-only --no-audio --seconds 8 -v > "$C/run.log" 2>&1
rc=$?
echo "run exit $rc"
grep -E "version:|receive-only|ohsdigi|Traceback|exiting|update signatures" "$C/run.log" | head -8
(( rc == 0 )) || bad+=("the headless run exited $rc")
grep -q Traceback "$C/run.log" && bad+=("the headless run printed a Traceback")
grep -qF "version: $V" "$C/run.log" || bad+=("the headless run did not say version $V")
if ((${#bad[@]})); then
    printf 'MACPROVE FAIL: %s\n' "$(IFS=';'; echo "${bad[*]}")"
    exit 1
fi
echo "MACPROVE PASS"
