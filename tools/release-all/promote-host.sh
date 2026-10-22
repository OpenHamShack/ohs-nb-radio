#!/bin/bash
# The release host's half of release-all's publishing stage (promote.sh
# runs it there, from the release host's worktree at the release commits).
#   tools/release-all/promote-host.sh <run dir on this host>
#
# In the scratch folders linux-host.sh made: release.sh --windows and
# --macos-release add the installer and the image (source first, older
# ones archived, the files to remove listed), then feed.py writes each
# app's feed from the LIVE one. A dry run stops there, the feed signed
# with a throw-away key. A real run then checks that the release host's
# own folders are as linux-host.sh found them (nothing else released
# meanwhile), puts the scratch folders in their place, uploads with
# tools/publish.sh - source first, then each app, the feed last of every
# upload, the superseded files removed - and checks the live site
# (live.py).
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
S=$RUN_DIR/srv
SRV=${RA_SRV:-/srv}
real_folder() { case $1 in nb) echo "$SRV/openhamshack-nb-releases" ;; ham) echo "$SRV/openhamshack-ham-releases" ;;
                           source) echo "$SRV/source-site" ;; esac; }
snapshot() { ( cd "$1" && find . -printf '%P\t%s\t%T@\n' | sort ); }
# The lines under release.sh's "remove from the remote site:" (or "...
# source site:") headings, kept indented as publish.sh --remove-list reads
# them. Screenshots are left out: they belong to the product pages, which
# publish.sh never uploads.
removals() {  # removals site|source <log>
    awk -v want="$1" '
        /remove from the remote source site:$/ { mode = "source"; next }
        /remove from the remote site:$/        { mode = "site"; next }
        /^  [^ ]/ && mode == want              { print; next }
                                               { mode = "" }' "$2" | grep -v '^  shots/' || true
}
: > "$RUN_DIR/remove-source.txt"

cd "$here"
for a in $APPS; do
    v=$(ver_of "$a") c=$(commit_of "$a") pkg=$(app_pkg "$a")
    export RELEASES=$S/$a ARCHIVE=$S/$a-archive BUILDS=$S/$a-build SOURCE_SITE=$S/source \
           SOURCE_SITE_ARCHIVE=$S/source-archive RELEASE_NO_FEED=1
    git checkout -q --detach "$c"
    : > "$RUN_DIR/remove-$a.txt"
    if wants windows; then
        step "promote $a $v: the Windows installer into the release folder"
        bash tools/release.sh "$a" --windows "$RUN_DIR/in/$pkg-$v-setup.exe" | tee "$RUN_DIR/windows-$a.log"
        removals site "$RUN_DIR/windows-$a.log" >> "$RUN_DIR/remove-$a.txt"
        removals source "$RUN_DIR/windows-$a.log" >> "$RUN_DIR/remove-source.txt"
    fi
    if wants macos; then
        step "promote $a $v: the macOS image into the release folder"
        bash tools/release.sh "$a" --macos-release "$RUN_DIR/in/$pkg-$v-arm64.dmg" --commit "$c" | tee "$RUN_DIR/macos-$a.log"
        removals site "$RUN_DIR/macos-$a.log" >> "$RUN_DIR/remove-$a.txt"
        removals source "$RUN_DIR/macos-$a.log" >> "$RUN_DIR/remove-source.txt"
    fi
    if ! wants linux; then
        # Not released for Linux: this version's .debs leave the folder,
        # so neither the feed nor the upload sees them (the hand recipe of
        # NB 0.1.19-0.1.21, Windows only). Kept beside the run.
        step "promote $a $v: Linux held back"
        mkdir -p "$RUN_DIR/held-linux"
        mv "$S/$a/${pkg}_${v}"_*.deb "$S/$a/${pkg}_${v}"_*.deb.sha256 "$RUN_DIR/held-linux/"
    fi
    step "promote $a $v: the update feed, from the live one"
    rehearse=()
    ((DRY)) && rehearse=(--rehearsal --key "$RUN_DIR/rehearsal.key")
    live_url=$(app_feed "$a")
    [[ -z ${RA_LIVE_FEED_BASE:-} ]] || live_url=$RA_LIVE_FEED_BASE/$a/update.json   # the tests' stand-in
    python3 tools/release-all/feed.py --app "$a" --version "$v" --releases "$S/$a" --live-url "$live_url" \
        --out "$RUN_DIR/feed-$a" --platforms "$PLATFORMS" "${rehearse[@]}"
    unset RELEASES ARCHIVE BUILDS SOURCE_SITE SOURCE_SITE_ARCHIVE RELEASE_NO_FEED
done
git checkout -q --detach "$LAST"
for f in "$RUN_DIR"/remove-*.txt; do
    echo "${f##*/}:"; sed 's/^  /  remove /' "$f"
done

if ((DRY)); then
    echo "dry run: stopping before the release host's folders change; nothing uploaded"
    rm -rf "$S"     # the scratch copies (over a gigabyte); the logs, feeds and lists stay
    echo "promote-host: PASS"
    exit 0
fi

step "promote: the release host's folders are as the run found them"
for f in $APPS source; do
    snapshot "$(real_folder "$f")" | cmp -s - "$RUN_DIR/snapshot-$f" \
        || die "$(real_folder "$f") changed since this run copied it (another release?); nothing put in place or uploaded"
done
for f in $APPS source; do
    real=$(real_folder "$f")
    for side in archive build; do
        [[ -d $S/$f-$side ]] || continue
        # An archive never loses or changes a file (release.sh archive_to
        # refuses a different file of the same name): the same here.
        ( cd "$S/$f-$side" && find . -type f -printf '%P\n' ) | while read -r n; do
            if [[ -e $real-$side/$n ]] && ! cmp -s "$S/$f-$side/$n" "$real-$side/$n"; then
                die "$real-$side/$n already holds a different file"
            fi
        done
    done
done

step "promote: the scratch folders into place"
for f in $APPS source; do
    real=$(real_folder "$f")
    rsync -a --delete "$S/$f/" "$real/"
    for side in archive build; do
        [[ -d $S/$f-$side ]] && { mkdir -p "$real-$side"; rsync -a --ignore-existing "$S/$f-$side/" "$real-$side/"; }
    done
done
for a in $APPS; do
    python3 tools/update-feed.py verify --app "$a" --releases "$(real_folder "$a")"
done

rm -rf "$S"
step "promote: publish.sh source"
bash tools/publish.sh source --remove-list "$RUN_DIR/remove-source.txt"
for a in $APPS; do
    step "promote: publish.sh $a"
    bash tools/publish.sh "$a" --version "$(ver_of "$a")" --remove-list "$RUN_DIR/remove-$a.txt"
done

step "promote: the live site"
python3 tools/release-all/live.py --run "$RUN_DIR" --platforms "$PLATFORMS" $(for a in $APPS; do echo "--app $a=$(ver_of "$a")"; done)
echo "promote-host: PASS"
