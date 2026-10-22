#!/bin/bash
# release-all.sh's publishing stage (a rehearsal in a dry run), run on the
# development VM once every platform has passed: checks that the
# installer's ohsdigi.pyd is the one release.sh built, carries the
# installers and images to the release host, and runs promote-host.sh
# there, which adds them to the scratch release folders, writes the feeds
# from the live ones and - not in a dry run - puts the folders in place,
# uploads them and checks the live site.
#   tools/release-all/promote.sh <run dir>
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
HOST_ROOT=${HOST_ROOT:-build/release-all}
hrun="$HOST_ROOT/$RUN"
htree="$HOST_ROOT/tree"

if wants windows; then
    step "promote: the installers carry release.sh's ohsdigi.pyd"
    for a in $APPS; do
        cmp -s "$RUN_DIR/win/ohsdigi.sha256" "$RUN_DIR/linux/ohsdigi-$a.sha256" \
            || die "the Windows build's ohsdigi.pyd ($(cat "$RUN_DIR/win/ohsdigi.sha256")) is not the one release.sh built for $a ($(cat "$RUN_DIR/linux/ohsdigi-$a.sha256")): the build is not reproducible any more"
    done
fi

step "promote: installers and images to the release host"
ra_ssh "$RELEASE_HOST" "mkdir -p $hrun/in"
files=()
wants windows && files+=("$RUN_DIR"/win/out/*-setup.exe "$RUN_DIR"/win/out/*-setup.exe.sha256)
wants macos && files+=("$RUN_DIR"/mac/out/*.dmg "$RUN_DIR"/mac/out/*.dmg.sha256)
((${#files[@]} == 0)) || ra_scp "${files[@]}" "$RELEASE_HOST:$hrun/in/"

step "promote: on the release host (log: $hrun/promote-host.log there)"
rc=0
ra_ssh "$RELEASE_HOST" "bash ~/$htree/tools/release-all/promote-host.sh ~/$hrun > ~/$hrun/promote-host.log 2>&1" || rc=$?
ra_ssh "$RELEASE_HOST" "grep -E '^(== step|feed |FEED|  remove|published|publish.sh: (published|verified)|live|LIVE|dry run)' ~/$hrun/promote-host.log | tail -n 60" || true
# The failing step, as promote-host.sh named it, for the notification.
((rc == 0)) || { ra_ssh "$RELEASE_HOST" "grep '^== step' ~/$hrun/promote-host.log | tail -1; tail -n 15 ~/$hrun/promote-host.log" || true; die "promote-host.sh failed"; }
ra_scp "$RELEASE_HOST:$hrun/remove-*.txt" "$RUN_DIR/" 2>/dev/null || true
echo "promote: PASS"
