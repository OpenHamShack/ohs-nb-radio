#!/bin/bash
# A whole QO-100 NB and/or Radio release in one command, run on the
# development VM, with one notification at the end (Brian, 18/10/2026).
#
#   tools/release-all.sh <app>=<version>... [--yes] [--dry-run]
#                        [--platforms linux,windows,macos] [--base <hub branch>]
#   tools/release-all.sh nb ham --version <version>     (both the same version)
#
#   e.g. tools/release-all.sh nb=0.1.23 ham=0.1.22
#        tools/release-all.sh nb=0.1.23+rc0 ham=0.1.22+rc0 --dry-run --yes
#
# What NB 0.1.22 / Radio 0.1.21 took seven hours and a dozen hand scripts
# to do (HANDOVER, 18/10), in the same order and with the same checks:
#
#  1. preflight: this checkout is committed, clean and at hub/main (or, for
#     a dry run, --base); each app's version is newer than its last release
#     commit; and what the release REMOVES against that commit is listed -
#     deleted and renamed files, and where most lines went (~/.claude/
#     CLAUDE.md: a release that silently dropped a fix shipped on 20/09
#     because only additions were looked at). Then it waits for "yes",
#     unless --yes.
#  2. the suite, once, by tools/run-suite-split.sh in a worktree of its own
#     (~/build/release-all/tree, kept: rust/target is a cache): red modules
#     run again alone, twice; only one that fails every time stops it.
#  3. the release commits, NB's then Radio's on top, by release.sh
#     --commit-only, so that every platform builds from them at once.
#  4. Linux, Windows and macOS IN PARALLEL, each a driver in
#     tools/release-all/ with its own log and status line:
#       linux    release.sh on the release host, into SCRATCH copies of its
#                release folders and source site (never the real ones yet);
#       windows  archive + ohsdigi to the Windows build VM, prep, build and
#                sign there (the signing secret stays on it), the install
#                checks (win-check.ps1), the installer copied back;
#       macos    the Mac: build-macos.sh --sign (Developer ID, notarised
#                with profile ohs-notary, stapled; the keychain and the API
#                key stay on it), then spctl and a headless receive-only
#                run of the app copied out of the image (mac-prove.sh).
#     Build caches stay: the Mac's work folder and the VM's build folders
#     (the newest two per app; older ones go, to bound the VM's disk).
#  5. only if every requested platform passed: the gate. A dry run stops
#     after rehearsing step 6 in the scratch folders (feed signed with a
#     throw-away key, website staged and checked, nothing uploaded).
#  6. publish (promote.sh, then site.sh): hub main is fast-forwarded to the
#     release commits first (refused if main moved during the run); the
#     installer and image join the scratch release folders (release.sh
#     --windows, --macos-release); the feed is written from the LIVE feed,
#     published later than it; the scratch folders replace the release
#     host's (refused if those changed meanwhile); publish.sh source, then
#     each app, with the files to remove; the website's downloads page
#     (only these apps' entries, refused if anything else would change),
#     the superseded downloads removed; then the live checks: every older
#     version offered the new one, every download matching the feed, the
#     installer's signature, every removed file a 404.
#  7. ONE notification ($NOTIFY, on $NOTIFY_HOST if set): success, or the
#     step that failed. It is sent however the run ends.
#
# --platforms limits the builds and the feed to those platforms; the
# others keep what the live feed offers (Linux's .debs are still built,
# for the source tarball and release commit, and held back). Everything
# is in ~/build/release-all/<run>/ here and on the release host: run.env,
# each stage's log, status and time. Hosts and folders come from
# ~/.config/openhamshack/nb-release.conf (RA_CONF), never this repository
# (its source tarballs are public).
#
# A dry run's version may carry a "+label" (0.1.23+rc0): the form
# ohscore/update.py reads as "a build that is not a release", so the apps
# run with it, and the feed (plain numbers only) can never offer it. A
# "-rc0" is refused: the apps cannot parse it.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=release-all/lib.sh
source "$here/tools/release-all/lib.sh"
TOOLS=${RA_TOOLS:-$here/tools/release-all}

usage() {
    echo "usage: tools/release-all.sh <nb|ham>=<version>... [--yes] [--dry-run] [--platforms linux,windows,macos] [--base <hub branch>]" >&2
    echo "       tools/release-all.sh nb ham --version <version> [...]" >&2
    exit 2
}

APPS=() YES=0 DRY=0 PLATFORMS=linux,windows,macos BASE_REF=main common_ver=
declare -A VER=()
while (($#)); do
    case $1 in
        nb=*|ham=*) a=${1%%=*}; [[ -z ${VER[$a]:-} ]] || { echo "$a named twice" >&2; usage; }
                    APPS+=("$a"); VER[$a]=${1#*=} ;;
        nb|ham) [[ -z ${VER[$1]:-} ]] || { echo "$1 named twice" >&2; usage; }
                APPS+=("$1"); VER[$1]=- ;;
        --version) common_ver=${2:?--version needs a value}; shift ;;
        --yes) YES=1 ;;
        --dry-run) DRY=1 ;;
        --platforms) PLATFORMS=${2:?--platforms needs a list}; shift ;;
        --base) BASE_REF=${2:?--base needs a branch}; shift ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
    shift
done
((${#APPS[@]})) || usage
for a in "${APPS[@]}"; do
    if [[ ${VER[$a]} == - ]]; then
        [[ -n $common_ver ]] || { echo "$a: no version (use $a=<version>, or --version)" >&2; usage; }
        VER[$a]=$common_ver
    fi
done
# NB first, always: its release commit goes under Radio's, as for 0.1.22.
ordered=()
for a in nb ham; do [[ -n ${VER[$a]:-} ]] && ordered+=("$a"); done
APPS=("${ordered[@]}")
for p in ${PLATFORMS//,/ }; do
    case $p in linux|windows|macos) ;; *) echo "--platforms: $p is not linux, windows or macos" >&2; usage ;; esac
done
[[ -n ${PLATFORMS//,/} ]] || usage
release_re='^[0-9]+(\.[0-9]+){1,3}$'
for a in "${APPS[@]}"; do
    v=${VER[$a]}
    if [[ $v =~ $release_re ]]; then continue; fi
    if [[ $v =~ ^[0-9]+(\.[0-9]+){1,3}-.+ ]]; then
        echo "$a $v: a pre-release is written ${v%%-*}+${v#*-} (ohscore/update.py cannot read \"-\"; \"+label\" is a build that is not a release)" >&2
        exit 2
    fi
    if [[ $v =~ ^[0-9]+(\.[0-9]+){1,3}\+[0-9A-Za-z]+([.-][0-9A-Za-z]+)*$ ]]; then
        ((DRY)) || { echo "$a $v is not a release version: only a --dry-run may use a +label" >&2; exit 2; }
        continue
    fi
    echo "$a: $v is not a version such as 0.1.23" >&2
    exit 2
done
[[ $BASE_REF == main ]] || ((DRY)) || { echo "--base: a real release is cut from hub/main only" >&2; exit 2; }

CONF=${RA_CONF:-$HOME/.config/openhamshack/nb-release.conf}
[[ -f $CONF ]] || { echo "no $CONF (the hosts and folders: see GUIDE section 6)" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONF"
: "${NOTIFY:?$CONF sets no NOTIFY}"

ROOT=${RA_ROOT:-$HOME/build/release-all}
TREE=${RA_TREE:-$ROOT/tree}
mkdir -p "$ROOT"
exec 9> "$ROOT/.lock"
flock -n 9 || { echo "another release-all.sh is running ($ROOT/.lock)" >&2; exit 1; }
label=$(for a in "${APPS[@]}"; do printf '%s-%s_' "$a" "${VER[$a]}"; done)
RUN="$(date +%Y%m%d-%H%M%S)-${label%_}$( ((DRY)) && echo -dry || true)"
RUN_DIR=$ROOT/$RUN
mkdir -p "$RUN_DIR"
echo "run $RUN_DIR"
what=$(for a in "${APPS[@]}"; do printf '%s %s, ' "$(app_site "$a")" "${VER[$a]}"; done)
what="${what%, } ($PLATFORMS)$( ((DRY)) && echo ", DRY RUN" || true)"

# --- timing and the one notification -----------------------------------
STAGE=preflight
T0=$(date +%s)
timing() { echo "$1 $2" >> "$RUN_DIR/timings"; }
staged() {  # staged <name> <command...>: one serial stage, timed and logged
    STAGE=$1; shift
    local t; t=$(date +%s)
    echo "== $STAGE"
    # In a subshell started with & rather than inside an "if": bash ignores
    # set -e anywhere in an if's condition, so a function's failed step
    # would not stop it.
    local rc=0
    ( "$@" ) > "$RUN_DIR/$STAGE.log" 2>&1 &
    wait $! || rc=$?
    timing "$STAGE" $(( $(date +%s) - t ))
    if (( rc == 0 )); then
        echo "   $STAGE: PASS ($(( $(date +%s) - t ))s)"
    else
        FAILED="$STAGE$(last_step "$RUN_DIR/$STAGE.log")"
        echo "   $STAGE: FAIL - see $RUN_DIR/$STAGE.log"
        tail -n 15 "$RUN_DIR/$STAGE.log" | sed 's/^/   | /'
        exit 1
    fi
}
last_step() {
    local s; s=$(grep '^== step ' "$1" 2>/dev/null | tail -1 | sed 's/^== step //') || true
    [[ -n $s ]] && echo " ($s)" || true
}
FAILED=
finish() {
    local rc=$? msg
    trap - EXIT
    timing total $(( $(date +%s) - T0 ))
    if (( rc == 0 )); then
        msg="release-all: $what - $( ((DRY)) && echo "dry run PASSED, nothing published" || echo "PUBLISHED and checked live")"
    else
        msg="release-all: $what - FAILED at ${FAILED:-$STAGE}; nothing after it was done. Log: $RUN_DIR"
    fi
    echo "$msg"
    echo "timings (seconds):"; sed 's/^/  /' "$RUN_DIR/timings"
    # One notification, whatever happened (but not for a "no" typed at the
    # prompt: whoever typed it is there); its own failure must not hide
    # the run's result.
    (( rc == 3 )) && exit 3
    # NOTIFY_HOST: the notifier lives on another machine; the message is
    # quoted for its shell, since it carries brackets and semicolons.
    if [[ -n ${NOTIFY_HOST:-} ]]; then
        ra_ssh "$NOTIFY_HOST" "$NOTIFY $(printf %q "$msg")" >/dev/null 2>&1
    else
        $NOTIFY "$msg" >/dev/null 2>&1
    fi || echo "(the notification could not be sent)" >&2
    exit "$rc"
}
trap finish EXIT

# --- 1. preflight -------------------------------------------------------
git -C "$here" fetch -q hub
BASE=$(git -C "$here" rev-parse --verify -q "hub/$BASE_REF^{commit}") || { FAILED="preflight (no hub/$BASE_REF)"; exit 1; }
[[ -z $(git -C "$here" status --porcelain) ]] || { FAILED="preflight (this checkout has uncommitted changes)"; exit 1; }
[[ $(git -C "$here" rev-parse HEAD) == "$BASE" ]] \
    || { FAILED="preflight (this checkout is not at hub/$BASE_REF ${BASE:0:12}: run the script that will be released)"; exit 1; }

removals() {  # removals <app> <version>: what this release takes away
    local a=$1 v=$2 marker prev pv
    marker=$(app_marker "$a")
    prev=$(git -C "$here" log --first-parent --format='%H %s' "$BASE" \
           | grep -m1 -E "^[0-9a-f]+ $marker [0-9][^ ]*\$" || true)
    if [[ -z $prev ]]; then
        echo "$(app_site "$a") $v: no earlier \"$marker <version>\" on hub/$BASE_REF; nothing to compare with"
        return 0
    fi
    pv=${prev##* }
    prev=${prev%% *}
    if [[ ${v%%+*} == "$pv" || $(printf '%s\n%s\n' "$pv" "${v%%+*}" | sort -V | tail -1) != "${v%%+*}" ]]; then
        echo "$(app_site "$a") $v is not newer than its last release, $pv (${prev:0:12})" >&2
        return 1
    fi
    echo "$(app_site "$a") $v against $pv (${prev:0:12}):"
    local gone
    gone=$(git -C "$here" diff --name-status -M --diff-filter=DR "$prev" "$BASE")
    if [[ -n $gone ]]; then
        awk -F'\t' '$1 == "D" {print "  DELETED  " $2} $1 ~ /^R/ {print "  RENAMED  " $2 " -> " $3}' <<< "$gone"
    else
        echo "  no file deleted or renamed"
    fi
    git -C "$here" diff --shortstat "$prev" "$BASE" | sed 's/^ */  /'
    echo "  most lines removed:"
    git -C "$here" diff --numstat "$prev" "$BASE" | awk -F'\t' '$2 != "-" && $2 > 0 {print $2 "\t" $3}' \
        | sort -rn | head -8 | awk -F'\t' '{printf "    -%-6s %s\n", $1, $2}'
}
STAGE="preflight (version or removals)"
report=$(for a in "${APPS[@]}"; do removals "$a" "${VER[$a]}" || exit 1; done) || { FAILED=$STAGE; exit 1; }
echo "$report" | tee "$RUN_DIR/removals.txt"
STAGE=preflight
# The feed's one line of "what's new" is the release's notes
# (update-feed.py release_notes): written and committed before a release,
# as for every release since 0.1.16, or the banner says nothing.
if ((! DRY)); then
    for a in "${APPS[@]}"; do
        [[ -f $here/docs/release-notes/$a-${VER[$a]}.txt ]] \
            || { FAILED="preflight (no docs/release-notes/$a-${VER[$a]}.txt)"; exit 1; }
    done
fi
if ((! YES)); then
    printf 'Release %s from hub/%s %s? Type yes: ' "$what" "$BASE_REF" "${BASE:0:12}"
    answer=
    read -r answer || true
    [[ $answer == yes ]] || { FAILED="preflight (not confirmed)"; exit 3; }
fi

# The worktree everything is built from: kept between runs, since its
# rust/target is ohsdigi's cache. Detached, so a release commit made in a
# dry run belongs to no branch and is simply left behind.
if [[ ! -d $TREE ]]; then
    git -C "$here" worktree add -q --detach "$TREE" "$BASE"
else
    [[ -z $(git -C "$TREE" status --porcelain) ]] || { FAILED="preflight ($TREE has uncommitted changes)"; exit 1; }
    git -C "$TREE" checkout -q --detach "$BASE"
fi
SUITE_TREE=$(git -C "$TREE" rev-parse "HEAD^{tree}")

# --- 2. the suite -------------------------------------------------------
suite() {
    cd "$TREE"
    LOG_DIR="$RUN_DIR/suite" RERUN_RED=${SUITE_RERUNS:-2} tools/run-suite-split.sh -j "${SUITE_JOBS:-1}"
}
staged suite suite

# --- 3. the release commits ---------------------------------------------
commits() {
    cd "$TREE"
    for a in "${APPS[@]}"; do
        step "release commit $a ${VER[$a]}"
        RELEASE_SUITE_PROVED=$SUITE_TREE bash tools/release.sh "$a" "${VER[$a]}" --commit-only
    done
}
staged commits commits
{
    echo "RUN=$(printf %q "$RUN")"
    echo "DRY=$DRY"
    echo "APPS=$(printf %q "${APPS[*]}")"
    echo "PLATFORMS=$(printf %q "$PLATFORMS")"
    echo "BASE=$BASE"
    echo "SUITE_TREE=$SUITE_TREE"
    echo "TREE=$(printf %q "$TREE")"
    for a in "${APPS[@]}"; do
        echo "VER_$a=$(printf %q "${VER[$a]}")"
        echo "COMMIT_$a=$(git -C "$TREE" log --format='%H %s' "$BASE..HEAD" \
                         | awk -v s="$(app_marker "$a") ${VER[$a]}" 'substr($0, 42) == s {print $1; exit}')"
    done
    echo "LAST=$(git -C "$TREE" rev-parse HEAD)"
    # The configuration, for the drivers (and the release host's half).
    grep -E '^[A-Z_]+=' "$CONF"
} > "$RUN_DIR/run.env"
# The release commits travel to the release host as a bundle, not by a push
# to hub: a dry run's commits must never reach the hub at all.
git -C "$TREE" bundle create "$RUN_DIR/release.bundle" "$BASE..HEAD" > /dev/null 2>&1 \
    || { FAILED="commits (git bundle)"; exit 1; }

# --- 4. the platforms, at once ------------------------------------------
# Linux runs whatever --platforms says: its release.sh makes the source
# tarball every other platform's package needs, and holds its .debs back
# when Linux is not being released.
STAGE=builds
declare -A pid=() t_start=()
drivers=(linux)
wants windows && drivers+=(windows)
wants macos && drivers+=(macos)
echo "== builds: ${drivers[*]} (logs $RUN_DIR/<platform>.log)"
for d in "${drivers[@]}"; do
    t_start[$d]=$(date +%s)
    # set +e: under the inherited -e a failed driver would end the subshell
    # before its exit status and end time were written.
    ( set +e; "$TOOLS/$d.sh" "$RUN_DIR" > "$RUN_DIR/$d.log" 2>&1; echo $? > "$RUN_DIR/$d.rc"; date +%s > "$RUN_DIR/$d.end" ) &
    pid[$d]=$!
done
bad=()
for d in "${drivers[@]}"; do
    wait "${pid[$d]}" || true
    rc=$(cat "$RUN_DIR/$d.rc" 2>/dev/null || echo 1)
    secs=$(( $(cat "$RUN_DIR/$d.end" 2>/dev/null || date +%s) - ${t_start[$d]} ))
    timing "$d" "$secs"
    if [[ $rc == 0 ]]; then
        echo "PASS ${secs}s" > "$RUN_DIR/$d.status"
    else
        echo "FAIL${secs:+ ${secs}s}$(last_step "$RUN_DIR/$d.log")" > "$RUN_DIR/$d.status"
        bad+=("$d$(last_step "$RUN_DIR/$d.log")")
    fi
    echo "   $d: $(cat "$RUN_DIR/$d.status")"
done

# --- 5. the gate ---------------------------------------------------------
if ((${#bad[@]})); then
    FAILED="build: ${bad[*]}"
    exit 1
fi

# --- 6. publish (or rehearse it) ----------------------------------------
if ((! DRY)); then
    # Main first, before anything leaves: the source tarball names these
    # commits, and site-build.py finds release notes on main's first-parent
    # line. If someone pushed to main since preflight, stop here: nothing
    # has been uploaded and the release host's folders are untouched, so a
    # second run (same versions) is clean.
    STAGE="push main"
    git -C "$here" fetch -q hub
    [[ $(git -C "$here" rev-parse hub/main) == "$BASE" ]] \
        || { FAILED="push main (hub/main moved since preflight; nothing published, run again)"; exit 1; }
    git -C "$TREE" push -q hub "HEAD:refs/heads/main" || { FAILED="push main (refused)"; exit 1; }
    echo "== hub main fast-forwarded to $(git -C "$TREE" rev-parse --short HEAD)"
fi
staged promote "$TOOLS/promote.sh" "$RUN_DIR"
staged site "$TOOLS/site.sh" "$RUN_DIR"
STAGE=done
