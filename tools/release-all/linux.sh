#!/bin/bash
# release-all.sh's Linux stage, run on the development VM: carries the
# release commits to the release host (as a git bundle) and runs
# linux-host.sh there, which builds the .debs with release.sh into scratch
# copies of the release folders. Then fetches the .debs back for the
# website, and ohsdigi.pyd's checksum for the gate.
#   tools/release-all/linux.sh <run dir>
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
: "${RELEASE_HOST:?no RELEASE_HOST in the configuration}" "${RELEASE_REPO:?no RELEASE_REPO}"
HOST_ROOT=${HOST_ROOT:-build/release-all}
hrun="$HOST_ROOT/$RUN"
htree="$HOST_ROOT/tree"

step "linux: copy the release commits to the release host"
ra_ssh "$RELEASE_HOST" "mkdir -p $hrun"
ra_scp "$RUN_DIR/release.bundle" "$RUN_DIR/run.env" "$RELEASE_HOST:$hrun/"

step "linux: the release host's worktree at the release commits"
# Its own worktree, kept between runs as the development VM's is (ohsdigi's
# rust/target), detached, so nothing here makes or moves a branch.
ra_ssh "$RELEASE_HOST" "set -e; cd $RELEASE_REPO; git fetch -q hub; git fetch -q ~/$hrun/release.bundle
    [ -d ~/$htree ] || git worktree add -q --detach ~/$htree $BASE
    test -z \"\$(git -C ~/$htree status --porcelain)\" || { echo '~/$htree has uncommitted changes' >&2; exit 1; }
    git -C ~/$htree checkout -q --detach $LAST"

step "linux: release.sh on the release host (log: $hrun/linux-host.log there)"
ra_ssh "$RELEASE_HOST" "bash ~/$htree/tools/release-all/linux-host.sh ~/$hrun > ~/$hrun/linux-host.log 2>&1" \
    || { ra_ssh "$RELEASE_HOST" "tail -n 25 ~/$hrun/linux-host.log" || true; die "linux-host.sh failed"; }
ra_ssh "$RELEASE_HOST" "tail -n 25 ~/$hrun/linux-host.log"

step "linux: the .debs back, for the website"
mkdir -p "$RUN_DIR/linux"
for a in $APPS; do
    pkg=$(app_pkg "$a") v=$(ver_of "$a")
    ra_scp "$RELEASE_HOST:$hrun/out/${pkg}_${v}_*" "$RELEASE_HOST:$hrun/out/ohsdigi-$a.sha256" "$RUN_DIR/linux/"
    ( cd "$RUN_DIR/linux" && for f in "${pkg}_${v}"_*.deb; do sha256sum -c --quiet "$f.sha256"; done ) \
        || die "$a's .debs did not arrive whole"
done
echo "linux: PASS"
