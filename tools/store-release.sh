#!/bin/bash
# One store release, start to finish, with no session in the loop: the
# suite on this host, the store build on the signing host (at the same
# time), then the install on the box.
#
# Usage:
#   tools/store-release.sh [--no-install] [--skip-suite] [--check] <radio|qo100nb> <commit>
#
# Why a script: until 23/10 a store release went agent -> session ->
# session. One agent ran the suite at -j 4 on a 16-core host, another
# session on another machine built and signed, and each step waited for a
# message. Store Radio 0.1.22-beta.6 lost a round trip to a commit that
# was never pushed. Every step below was already a script; this only joins
# them up and refuses at the first thing that is not right.
#
# Order and what each step refuses:
#   1. <commit> must be on the hub, have hub/main as an ancestor (a store
#      package must never drop something main already shipped - see
#      ~/.claude/CLAUDE.md, 20 September), and carry a store/<app>/
#      module.yaml version above the one installed on the box. Dock360
#      refuses an older version anyway, but only after the build.
#   2. The suite (tools/run-suite-split.sh, RERUN_RED=2) runs here, in a
#      detached worktree at <commit>, while the signing host builds from
#      its own detached worktree at the same commit. The build runs inside
#      an 8G systemd scope because the signing host is shared.
#   3. The build only counts if its log says "selftest: PASS",
#      "check-encumbered: clean" and "DONE rc=0".
#   4. Only when both are green: tools/box-store-update.sh, which makes a
#      signed rollback of what is installed before touching the box.
#
# --no-install stops after step 3 and prints the box-store-update.sh
# command. --skip-suite is for a commit whose tree a green run has already
# covered (say so in the handover). --check validates arguments and config
# only: no git, no ssh. JOBS (default 8) is the suite's -j; PYTHON
# (default ~/build/venvs/ohs-qt/bin/python) its interpreter.
#
# Hosts come from ~/.config/openhamshack/box-update.conf (BOX_HOST,
# SIGN_HOST), as tools/box-store-update.sh reads them, because this
# repository's source is public. The signing host must have its own
# ~/openhamshack-nb clone with a "hub" remote.
#
# Everything goes to ~/build/store-release-<app>-<commit>/ (release.log,
# the suite's per-module logs, build.log copied back). It ends by posting
# the result to Brian's phone through ~/.config/claude-account/notify,
# when that exists.
set -uo pipefail

usage() { echo "usage: $0 [--no-install] [--skip-suite] [--check] <radio|qo100nb> <commit>" >&2; exit 2; }

INSTALL=1 SUITE=1 CHECK=0
while [ $# -gt 0 ]; do
    case $1 in
        --no-install) INSTALL=0 ;;
        --skip-suite) SUITE=0 ;;
        --check) CHECK=1 ;;
        -*) usage ;;
        *) break ;;
    esac
    shift
done
[ $# -eq 2 ] || usage
APP=$1 COMMIT=$2
case $APP in radio|qo100nb) ;; *) echo "store-release: unknown app '$APP' (radio or qo100nb)" >&2; exit 2 ;; esac
[[ $COMMIT =~ ^[0-9a-f]{7,40}$ ]] || { echo "store-release: '$COMMIT' is not a commit id" >&2; exit 2; }

CONF=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
[ -r "$CONF" ] || { echo "store-release: no config at $CONF" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONF"
[ -n "${BOX_HOST:-}" ] && [ -n "${SIGN_HOST:-}" ] || { echo "store-release: $CONF must set BOX_HOST and SIGN_HOST" >&2; exit 2; }
# 8, not 16: a test process takes more than one core (the decoders run
# threads), and above about 8 the simulator-paced tests fail on timing.
JOBS=${JOBS:-8}
[[ $JOBS =~ ^[1-9][0-9]?$ ]] || { echo "store-release: JOBS must be 1-99" >&2; exit 2; }

if [ $CHECK = 1 ]; then
    echo "app=$APP commit=$COMMIT box=$BOX_HOST sign=$SIGN_HOST jobs=$JOBS suite=$SUITE install=$INSTALL"
    exit 0
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$HOME/build/store-release-$APP-$COMMIT
mkdir -p "$OUT"
LOG=$OUT/release.log
exec > >(tee -a "$LOG") 2>&1

notify() {
    local n=$HOME/.config/claude-account/notify
    [ -x "$n" ] && "$n" "$1" >/dev/null 2>&1
    true
}
fail() { echo "FAILED: $1"; notify "Store $APP $COMMIT failed: $1"; exit 1; }

echo "== store-release $APP $COMMIT $(date -Is)"

# 1. what is being released
git -C "$REPO" fetch -q hub || fail "git fetch hub"
FULL=$(git -C "$REPO" rev-parse --verify -q "$COMMIT^{commit}") || fail "$COMMIT is not in this clone after fetching hub"
git -C "$REPO" branch -r --contains "$FULL" | grep -q '^ *hub/' || fail "$COMMIT is not on the hub - push it first"
git -C "$REPO" merge-base --is-ancestor hub/main "$FULL" || fail "hub/main is not an ancestor of $COMMIT - merge main first"
YAML=$(git -C "$REPO" show "$FULL:store/$APP/module.yaml") || fail "no store/$APP/module.yaml at $COMMIT"
MODULE=$(sed -n 's/^id: *//p' <<<"$YAML")
VERSION=$(sed -n 's/^version: *//p' <<<"$YAML")
[ -n "$MODULE" ] && [ -n "$VERSION" ] || fail "module.yaml has no id or version"
INSTALLED=$(ssh "$BOX_HOST" "sudo sed -n 's/^version: *//p' /var/lib/dock360/catalogue/uploaded/modules/$MODULE/module.yaml" 2>/dev/null)
echo "$MODULE $VERSION (installed on $BOX_HOST: ${INSTALLED:-none})"
if [ -n "$INSTALLED" ]; then
    # sort -V orders 0.1.22-beta.5 < 0.1.22-beta.6 and puts a .rollback
    # label above its base, which is what Dock360 itself will do.
    [ "$VERSION" != "$INSTALLED" ] && [ "$(printf '%s\n%s\n' "$INSTALLED" "$VERSION" | sort -V | tail -1)" = "$VERSION" ] \
        || fail "$VERSION is not above the installed $INSTALLED - bump store/$APP/module.yaml"
fi

# 2a. the build, on the signing host, in the background
D="~/build/store-radio-$COMMIT"
[ "$APP" = radio ] || D="~/build/store-$APP-$COMMIT"
ssh "$SIGN_HOST" "set -e; C=$FULL; D=$D; W=~/wt/store-$APP-$COMMIT
  git -C ~/openhamshack-nb fetch -q hub
  rm -rf \$D; mkdir -p \$D
  git -C ~/openhamshack-nb worktree remove --force \$W 2>/dev/null || true
  git -C ~/openhamshack-nb worktree add -q --detach \$W \$C
  cd \$W
  SHACK_STORE_OUT=\$D/out SHACK_STAGE=\$D/stage systemd-run --user --scope -q -p MemoryMax=8G \
    sh -c 'tools/build-store.sh $APP && tools/store-check.sh $APP' > \$D/build.log 2>&1; rc=\$?
  echo \"DONE rc=\$rc\" >> \$D/build.log
  cd ~; git -C ~/openhamshack-nb worktree remove --force \$W" > "$OUT/build-ssh.log" 2>&1 &
BUILD_PID=$!
echo "build started on $SIGN_HOST"

# 2b. the suite, here
SUITE_RC=0
if [ $SUITE = 1 ]; then
    W=$OUT/tree
    git -C "$REPO" worktree remove --force "$W" 2>/dev/null
    git -C "$REPO" worktree add -q --detach "$W" "$FULL" || fail "worktree for the suite"
    # ohsdigi is built, never committed, so a fresh tree has none and
    # test_radio errors on it (beta.6's first run did exactly that).
    (cd "$W" && tools/build-ohsdigi.sh --host --install > "$OUT/ohsdigi.log" 2>&1) || fail "ohsdigi build - see $OUT/ohsdigi.log"
    echo "suite: -j $JOBS in $W"
    (cd "$W" && PYTHON=${PYTHON:-$HOME/build/venvs/ohs-qt/bin/python} LOG_DIR=$OUT/suite RERUN_RED=2 \
        tools/run-suite-split.sh -j "$JOBS" > "$OUT/suite.log" 2>&1)
    SUITE_RC=$?
    tail -6 "$OUT/suite.log"
    git -C "$REPO" worktree remove --force "$W"
else
    echo "suite: skipped (--skip-suite)"
fi

wait $BUILD_PID
scp -q "$SIGN_HOST:$D/build.log" "$OUT/build.log" || fail "could not fetch the build log"
grep -E '^(Wrote|selftest|store-check|check-encumbered|DONE)' "$OUT/build.log"
[ $SUITE_RC = 0 ] || fail "suite red - see $OUT/suite.log"

# 3. the build's own verdict
grep -q '^DONE rc=0$' "$OUT/build.log" || fail "build failed - see $OUT/build.log"
grep -q '^selftest: PASS' "$OUT/build.log" || fail "selftest did not PASS"
grep -q '^check-encumbered: clean' "$OUT/build.log" || fail "check-encumbered not clean"
PKG="$D/out/$MODULE-$VERSION.d360mod"
SHA=$(ssh "$SIGN_HOST" "sha256sum $PKG" | cut -d' ' -f1)
[[ $SHA =~ ^[0-9a-f]{64}$ ]] || fail "no package at $SIGN_HOST:$PKG"
echo "package $SIGN_HOST:$PKG sha256 $SHA"

# 4. the box
if [ $INSTALL = 0 ]; then
    echo "not installed (--no-install). To install:"
    echo "  tools/box-store-update.sh $MODULE $VERSION $SIGN_HOST:$PKG $SHA"
    notify "Store $APP $VERSION built and green, not installed"
    exit 0
fi
"$REPO/tools/box-store-update.sh" "$MODULE" "$VERSION" "$SIGN_HOST:$PKG" "$SHA" || fail "install on $BOX_HOST"
echo "== installed $MODULE $VERSION on $BOX_HOST $(date -Is)"
notify "Store $APP $VERSION installed on $BOX_HOST"
