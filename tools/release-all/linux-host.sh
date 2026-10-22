#!/bin/bash
# The release host's half of release-all.sh's Linux stage (linux.sh runs
# it there, from the release host's own worktree at the release commits).
#   tools/release-all/linux-host.sh <run dir on this host>
#
# release.sh builds into SCRATCH copies of this host's release folders and
# source site, in the run folder - for a real release as well as a dry
# run. The real folders change only in promote-host.sh, after every
# platform has passed, and only if nothing else changed them meanwhile
# (a snapshot of each is taken here, before the copy). So a run that
# fails anywhere leaves them exactly as they were, and the same version
# can simply be run again; with release.sh writing straight into them, as
# before, the .debs of a release that never went out stayed behind and
# refused the next attempt at that version.
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
S=$RUN_DIR/srv
# The real folders (release.sh's own defaults; RA_SRV moves them for the tests).
SRV=${RA_SRV:-/srv}
real_folder() { case $1 in nb) echo "$SRV/openhamshack-nb-releases" ;; ham) echo "$SRV/openhamshack-ham-releases" ;;
                           source) echo "$SRV/source-site" ;; esac; }
snapshot() { ( cd "$1" && find . -printf '%P\t%s\t%T@\n' | sort ); }

step "linux: scratch copies of the release folders"
rm -rf "$S"
mkdir -p "$S" "$RUN_DIR/out"
for f in $APPS source; do
    src=$(real_folder "$f")
    [[ -d $src ]] || die "no $src"
    snapshot "$src" > "$RUN_DIR/snapshot-$f"
    cp -a "$src" "$S/$f"
done

cd "$here"
for a in $APPS; do
    v=$(ver_of "$a") c=$(commit_of "$a") pkg=$(app_pkg "$a")
    step "linux: release.sh $a $v at ${c:0:12}"
    git checkout -q --detach "$c"
    RELEASES=$S/$a ARCHIVE=$S/$a-archive BUILDS=$S/$a-build SOURCE_SITE=$S/source \
        SOURCE_SITE_ARCHIVE=$S/source-archive RELEASE_SUITE_PROVED=$SUITE_TREE RELEASE_NO_FEED=1 \
        bash tools/release.sh "$a" "$v"
    cp "$S/$a/${pkg}_${v}"_*.deb "$S/$a/${pkg}_${v}"_*.deb.sha256 "$RUN_DIR/out/"
    sha256sum < "$S/$a-build/${pkg}-${v}-ohsdigi/windows-amd64/ohsdigi.pyd" | cut -d' ' -f1 > "$RUN_DIR/out/ohsdigi-$a.sha256"
done
git checkout -q --detach "$LAST"
echo "linux-host: PASS"
