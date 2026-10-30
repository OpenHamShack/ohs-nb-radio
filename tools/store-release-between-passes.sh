#!/bin/bash
# A Store Radio release that never cuts a weather-satellite pass short:
# tools/store-release.sh --no-install, then the install only once the
# box is between passes, then any passes to decode again.
#
# Usage:
#   tools/store-release-between-passes.sh <commit> [<passId>...]
#
# Why: an install restarts Radio for about nine minutes (30/10/2026: the
# 07:17Z pass was lost to an install that began with two minutes to its
# AOS). So the install waits until /api/wxsat/status says `waiting` with
# the next pass at least 15 minutes off, or `idle`, and gives up after two
# hours. NO_INSTALL_FROM / NO_INSTALL_UNTIL (UTC HHMM) add a window to keep
# clear, such as another session's test of the box.
#
# Writes ~/build/store-release-radio-<commit>.out (the release) and prints
# a short summary; posts nothing itself (store-release.sh notifies).
set -u
commit=${1:?usage: $0 <commit> [<passId>...]}
shift
cd "$(dirname "$0")/.." || exit 1
. ~/.config/openhamshack/box-update.conf
out=~/build/store-release-radio-$commit.out
status_json() {
    ssh "$BOX_HOST" 'T=$(sudo cat /etc/openhamshack/local-screen.token); curl -s -m 10 -H "Authorization: Bearer $T" http://127.0.0.1/radio/api/wxsat/status' 2>/dev/null
}

tools/store-release.sh --no-install radio "$commit" >"$out" 2>&1 || { echo "BUILD FAILED"; tail -20 "$out"; exit 1; }
cmd=$(grep -A1 "To install:" "$out" | tail -1)
[ -n "$cmd" ] || { echo "no install command in $out"; exit 1; }

st=unknown; eta=0
for _ in $(seq 240); do
    read -r st eta < <(status_json | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["state"], int(d.get("etaS") or 0))' 2>/dev/null)
    hm=$(date -u +%H%M)
    if [ -n "${NO_INSTALL_FROM:-}" ] && [ "$hm" -ge "$NO_INSTALL_FROM" ] && [ "$hm" -lt "${NO_INSTALL_UNTIL:?}" ]; then
        sleep 30; continue
    fi
    [ "$st" = waiting ] && [ "${eta:-0}" -gt 900 ] && break
    [ "$st" = idle ] && break
    sleep 30
done
echo "state before install: $st, next pass in ${eta}s, at $(date -u +%H:%M)Z"
eval "$cmd" 2>&1 | tail -3
rc=${PIPESTATUS[0]}
echo "INSTALL rc=$rc"
[ "$rc" -eq 0 ] || exit "$rc"

sleep 30
for p in "$@"; do
    ssh "$BOX_HOST" "T=\$(sudo cat /etc/openhamshack/local-screen.token); curl -s -X POST -H \"Authorization: Bearer \$T\" http://127.0.0.1/radio/api/wxsat/passes/$p/decode" 2>/dev/null
    echo
done
