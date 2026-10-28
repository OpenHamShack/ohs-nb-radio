#!/bin/sh
# Run only the test modules near what changed since <base>: the check an
# agent runs before merging a branch, leaving the full suite to the
# release (GUIDE section 8: agents test only what they changed).
#
#   tools/suite-affected.sh [-j N] [--list] <base>
#
# <base> is what the branch will merge into (usually main). The modules
# are tools/suite_affected.py's choice - the changed test files, tests
# named like a changed module or its package, tests importing a changed
# module, and tests naming a changed script or data file; its header has
# the rules. It errs towards running more. A changed file nothing maps to
# is listed as "no test found near ..." so it is seen, not silently
# untested. --list prints the choice and runs nothing. The run itself is
# tools/run-suite-split.sh with those modules (PYTHON, LOG_DIR, TIMEOUT,
# RERUN_RED as there); a run naming modules is never recorded in the
# suite cache, so the release still runs everything once.
set -u
cd "$(dirname "$0")/.."
JOBS=1 LIST=0
while :; do
    case ${1:-} in
        -j) JOBS=$2; shift 2 ;;
        --list) LIST=1; shift ;;
        *) break ;;
    esac
done
[ $# -eq 1 ] || { echo "usage: $0 [-j N] [--list] <base>" >&2; exit 2; }
out=$(python3 tools/suite_affected.py "$1") || exit 2
mods=$(printf '%s\n' "$out" | grep -v '^#')
printf '%s\n' "$out" | grep '^#'
n=$(printf '%s\n' "$mods" | grep -c .)
echo "suite-affected: $n test modules near the changes since $1"
if [ $LIST = 1 ]; then
    printf '%s\n' "$mods" | grep .
    exit 0
fi
[ "$n" -gt 0 ] || { echo "nothing to run"; exit 0; }
# shellcheck disable=SC2086
exec tools/run-suite-split.sh -j "$JOBS" $mods
