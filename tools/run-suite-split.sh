#!/bin/sh
# The whole suite, one test module per interpreter, with a one-screen summary.
#
#   tools/run-suite-split.sh [-j N] [module ...]     (default: every tests/test_*.py)
#
# Why not `python3 -m unittest discover -s tests`, as release.sh runs it:
# one interpreter holding every module's windows, decoders and fixtures
# outgrew the ohs-dev VM's memory and was OOM-killed partway, so a
# full run there gave no answer at all. A process per module frees each
# module's memory when it ends, and a module that crashes or hangs costs
# only its own line instead of the run.
#
# Each module's output goes to $LOG_DIR/<module>.log (default
# ~/build/suite-split-<date>, never /tmp: that is a small tmpfs every
# session shares); the summary names the failures and where to read them.
# A module gets $TIMEOUT seconds (default 1200). PYTHON picks the
# interpreter (default python3; a venv with pip's PyQt6 works too).
# Exit status is 0 only when every module passed.
#
# RERUN_RED=N runs the modules that came out red again, one at a time, up
# to N more times, each run taking only what was still red; the last run
# decides. Many tests here pace a simulator in real
# time, so on a host another session is loading (the release host reached
# a load of 28 during the NB 0.1.22 release) a few dozen fail by timing and pass
# alone; GUIDE section 5 says to rerun red modules serially before
# believing them, and this is that step, so a release need not be cut by
# hand around it. A module that fails every time is still red.
#
# A green full run is remembered (the suite cache, 28/10/2026). Each
# release ran the whole suite again - 25 minutes - on a tree some agent
# had already run green an hour before, often differing only in the
# store version line the release commit bumps. So a full run (no modules
# named) that ends green, in a worktree with nothing uncommitted, writes
# a record to $SUITE_CACHE_DIR (default ~/build/suite-cache, shared by
# every worktree on this host) named by the committed tree's "effective"
# hash (below) and a key made of the interpreter (its path, version and
# every installed distribution) and the ohsdigi module the tests import
# (ohscore/ohsdigi.abi3.so's sha256, or "none"): the same tree under a
# different Python or ohsdigi is a different run. A dirty worktree never
# counts, because the record would name a tree the tests did not see;
# nor does a run during which HEAD moved or a tracked file changed.
#
#   tools/run-suite-split.sh --if-needed [-j N]
#
# exits 0 at once, printing "tree <hash> already green at <time>", when
# that record exists; otherwise it runs the full suite as above (and
# records it if green). store-release.sh runs the suite this way.
#
# The tests' scratch files (tempfile, so $TMPDIR) go to a folder of this
# run's own on disk, $SUITE_TMP_ROOT/<run> (default ~/build/tmp), removed
# when the run ends, never to /tmp: on the development VM /tmp is a 12 GB
# tmpfs, so every scratch home, fixture recording and fake release folder
# a full run leaves there is RAM, shared with every other session, and the
# NB 0.1.22 suite was one of the things that filled it. The reruns below
# share the first run's folder (exec keeps the environment) and the last
# of them removes it.
set -u
cd "$(dirname "$0")/.."
JOBS=1 IF_NEEDED=0
while :; do
    case ${1:-} in
        -j) JOBS=$2; shift 2 ;;
        --if-needed) IF_NEEDED=1; shift ;;
        *) break ;;
    esac
done
if [ $IF_NEEDED = 1 ] && [ $# -gt 0 ]; then
    echo "--if-needed is for the full suite: name no modules" >&2; exit 2
fi
PY=${PYTHON:-python3}
CACHE_DIR=${SUITE_CACHE_DIR:-$HOME/build/suite-cache}
TIMEOUT=${TIMEOUT:-1200}
LOG_DIR=${LOG_DIR:-$HOME/build/suite-split-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$LOG_DIR"
# The folder is this process's: exec keeps the PID, so a rerun knows it
# for its own, while a runner started by a test of this script (a new
# process that inherits the variables) makes its own and leaves this alone.
if [ "${SUITE_TMP_PID:-}" != "$$" ]; then
    SUITE_TMP=$(mkdir -p "${SUITE_TMP_ROOT:-$HOME/build/tmp}" && mktemp -d "${SUITE_TMP_ROOT:-$HOME/build/tmp}/suite.XXXXXX") \
        || { echo "cannot make a scratch folder under ${SUITE_TMP_ROOT:-$HOME/build/tmp}" >&2; exit 1; }
    SUITE_TMP_PID=$$
    export SUITE_TMP SUITE_TMP_PID
fi
export TMPDIR=$SUITE_TMP
# Any way out but the exec below: a run interrupted by hand is cleaned too.
trap 'rm -rf "$SUITE_TMP"' EXIT

# The tree with every store/*/module.yaml's top-level "version:" line
# blanked, so a store release commit - which changes only that line -
# has the effective tree of the commit before it. Built in an index file
# of this run's own (GIT_INDEX_FILE), so the worktree's real index is
# never touched: read HEAD's tree into it, put a copy of each module.yaml
# with that one line replaced in place of the real one (hash-object -w
# stores the copy, a few hundred bytes), and write-tree. Why that line is
# safe to ignore: nothing the suite runs reads a store module.yaml's
# version (the apps report VERSION's; the store form is built and tested
# by build-store.sh and store-check.sh, never here). A test that started
# reading it would make this unsafe, so that would have to change too.
effective_tree() {
    idx=$SUITE_TMP/effective-index
    rm -f "$idx"
    GIT_INDEX_FILE=$idx git read-tree HEAD || return 1
    for f in $(git ls-tree -r --name-only HEAD store | grep '^store/[^/]*/module\.yaml$'); do
        blob=$(git show "HEAD:$f" | sed 's/^version:.*/version: (ignored by the suite cache)/' | git hash-object -w --stdin) || return 1
        GIT_INDEX_FILE=$idx git update-index --cacheinfo "100644,$blob,$f" || return 1
    done
    GIT_INDEX_FILE=$idx git write-tree
    rm -f "$idx"
}

# What the tests ran with besides the tree. Every installed distribution
# is in it because a venv upgraded in place (PyQt6, numpy) is a different
# run under the same path.
run_key() {
    py=$("$PY" -c 'import sys, hashlib, importlib.metadata as m
d = sorted("%s==%s" % (x.metadata["Name"], x.version) for x in m.distributions())
print(sys.executable, sys.version.split()[0], hashlib.sha256("\n".join(d).encode()).hexdigest()[:16])') || return 1
    if [ -f ohscore/ohsdigi.abi3.so ]; then
        dig=$(sha256sum ohscore/ohsdigi.abi3.so | cut -c1-16)
    else
        dig=none
    fi
    echo "python=$py"
    echo "ohsdigi=$dig"
}

# Only the first process of a run decides whether it may be recorded: the
# reruns below exec this script with the red modules named, keep the PID,
# and inherit the decision; a runner started by a test of this script
# (another PID) decides for itself, and names its modules, so never records.
if [ "${SUITE_CACHE_PID:-}" != "$$" ]; then
    SUITE_CACHE_FILE= SUITE_CACHE_TREE= SUITE_CACHE_INFO=
    if [ $# -eq 0 ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            echo "suite cache: the worktree has uncommitted changes, so this run will not be recorded"
        elif SUITE_CACHE_TREE=$(git rev-parse 'HEAD^{tree}') && eff=$(effective_tree) && info=$(run_key); then
            key=$(printf '%s\n' "$info" | sha256sum | cut -c1-16)
            SUITE_CACHE_FILE=$CACHE_DIR/$eff-$key
            SUITE_CACHE_INFO="tree=$eff
committed_tree=$SUITE_CACHE_TREE
commit=$(git rev-parse HEAD)
$info"
            if [ $IF_NEEDED = 1 ] && [ -f "$SUITE_CACHE_FILE" ]; then
                echo "tree $eff already green at $(sed -n 's/^time=//p' "$SUITE_CACHE_FILE")"
                exit 0
            fi
        else
            echo "suite cache: could not work out this tree's key, so this run will not be recorded"
            SUITE_CACHE_FILE=
        fi
    fi
    SUITE_CACHE_PID=$$
    export SUITE_CACHE_PID SUITE_CACHE_FILE SUITE_CACHE_TREE SUITE_CACHE_INFO
fi

if [ $# -eq 0 ]; then
    set -- $(cd tests && ls test_*.py | sed 's/\.py$//')
fi
export PYTHONPATH=tests QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}

run_one() {
    m=$1
    timeout "$TIMEOUT" "$PY" -m unittest "$m" >"$LOG_DIR/$m.log" 2>&1
    echo "$m $?" >"$LOG_DIR/$m.rc"
}

# A plain job pool: -j N keeps N modules running (the Qt ones are heavy,
# so the default is one at a time). The pool counts its own PIDs: `jobs -p`
# inside $(...) runs in a subshell, which in dash (this host's /bin/sh)
# sees no jobs at all, so -j 4 once started all ~240 modules at once and
# took the machine's memory with it (23/10/2026).
pids=""
for m in "$@"; do
    while :; do
        live=""; n=0
        for p in $pids; do
            if kill -0 "$p" 2>/dev/null; then live="$live $p"; n=$((n + 1)); fi
        done
        pids=$live
        [ "$n" -lt "$JOBS" ] && break
        sleep 1
    done
    run_one "$m" &
    pids="$pids $!"
done
wait

tests=0; fails=0; errors=0; skips=0; bad=""; redmods=""
for m in "$@"; do
    rc=$(cut -d' ' -f2 "$LOG_DIR/$m.rc")
    log="$LOG_DIR/$m.log"
    n=$(sed -n 's/^Ran \([0-9]*\) tests\{0,1\} in.*/\1/p' "$log" | tail -1)
    tests=$((tests + ${n:-0}))
    f=$(sed -n 's/.*failures=\([0-9]*\).*/\1/p' "$log" | tail -1)
    e=$(sed -n 's/.*errors=\([0-9]*\).*/\1/p' "$log" | tail -1)
    s=$(sed -n 's/.*skipped=\([0-9]*\).*/\1/p' "$log" | tail -1)
    fails=$((fails + ${f:-0})); errors=$((errors + ${e:-0})); skips=$((skips + ${s:-0}))
    if [ "$rc" != 0 ]; then
        case $rc in 124) why="timed out" ;; 137) why="killed (OOM?)" ;; *) why="rc=$rc" ;; esac
        bad="$bad
  $m: $why, failures=${f:-0} errors=${e:-0}"
        redmods="$redmods $m"
    fi
    rm -f "$LOG_DIR/$m.rc"
done
echo "modules: $#  tests: $tests  failures: $fails  errors: $errors  skipped: $skips"
echo "logs: $LOG_DIR"
if [ -n "$bad" ]; then
    echo "red:$bad"
    left=${RERUN_RED:-0}
    if [ "$left" -gt 0 ] 2>/dev/null; then
        echo "rerunning the red modules one at a time; that run decides"
        # shellcheck disable=SC2086
        trap - EXIT
        RERUN_RED=$((left - 1)) LOG_DIR="$LOG_DIR/rerun" exec "$0" $redmods
    fi
    exit 1
fi
echo "all green"
# Written last, and only if the tree the run began on is still what is
# checked out with nothing changed: a commit made mid-run, or a test that
# rewrote a tracked file, means the record would not name what ran.
if [ -n "${SUITE_CACHE_FILE:-}" ]; then
    if [ "$(git rev-parse 'HEAD^{tree}' 2>/dev/null)" != "$SUITE_CACHE_TREE" ] || [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        echo "suite cache: the worktree changed during the run, so it is not recorded"
    else
        mkdir -p "$CACHE_DIR"
        printf '%s\ntime=%s\nlogs=%s\n' "$SUITE_CACHE_INFO" "$(date -Is)" "$LOG_DIR" > "$SUITE_CACHE_FILE.$$"
        mv "$SUITE_CACHE_FILE.$$" "$SUITE_CACHE_FILE"
        echo "suite cache: recorded $(basename "$SUITE_CACHE_FILE")"
    fi
fi
