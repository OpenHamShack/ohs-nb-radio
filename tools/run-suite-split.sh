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
JOBS=1
if [ "${1:-}" = "-j" ]; then JOBS=$2; shift 2; fi
PY=${PYTHON:-python3}
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
# so the default is one at a time).
for m in "$@"; do
    while [ "$(jobs -p | wc -l)" -ge "$JOBS" ]; do sleep 1; done
    run_one "$m" &
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
