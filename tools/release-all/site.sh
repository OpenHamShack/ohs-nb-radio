#!/bin/bash
# release-all.sh's website stage, on the development VM (where the
# website's repository, SITE_REPO, its live build, SITE_LIVE, and the
# uploader, SITE_UPLOADER = openhamshack-os, are): the released files
# under their published names, site.py's stage and guard, then - not in
# a dry run - publish-web.sh site (dry, then for real) with the superseded
# downloads removed, the stage made the live build, the data change merged
# into the site's main, and every new download checked over HTTPS.
#   tools/release-all/site.sh <run dir>
#
# A dry run builds, guards and checks the stage in a detached worktree of
# the site's repository, then removes both: nothing is uploaded or merged.
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
: "${SITE_REPO:?no SITE_REPO}" "${SITE_LIVE:?no SITE_LIVE}" "${SITE_UPLOADER:?no SITE_UPLOADER}"
SITE_REPO=${SITE_REPO/#\~/$HOME} SITE_LIVE=${SITE_LIVE/#\~/$HOME} SITE_UPLOADER=${SITE_UPLOADER/#\~/$HOME}
D=$RUN_DIR/site
F=$D/files
rm -rf "$D"
mkdir -p "$F"

step "site: the release's files under their published names"
put() {  # put <from> <published name>
    cp "$1" "$F/$2"
    echo "$(sha256sum < "$F/$2" | cut -d' ' -f1)  $2" > "$F/$2.sha256"
}
args=()
for a in $APPS; do
    v=$(ver_of "$a") pkg=$(app_pkg "$a") P=OpenHamShack-$(app_site "$a")-$(ver_of "$a")
    args+=(--release "$a=$v")
    if wants linux; then
        put "$RUN_DIR/linux/${pkg}_${v}_amd64.deb" "$P-linux-x86_64.deb"
        put "$RUN_DIR/linux/${pkg}_${v}_arm64.deb" "$P-linux-arm64.deb"
        put "$RUN_DIR/linux/${pkg}_${v}_all.deb" "$P-linux-all.deb"
    fi
    wants windows && put "$RUN_DIR/win/out/$pkg-$v-setup.exe" "$P-windows-x64.exe"
    wants macos && put "$RUN_DIR/mac/out/$pkg-$v-arm64.dmg" "$P-macos-arm64.dmg"
done

step "site: a worktree of the website's main"
[[ -z $(git -C "$SITE_REPO" status --porcelain) ]] || die "$SITE_REPO has uncommitted changes"
branch=release-all/$RUN
if ((DRY)); then
    git -C "$SITE_REPO" worktree add -q --detach "$D/repo" main
else
    git -C "$SITE_REPO" worktree add -q -b "$branch" "$D/repo" main
fi
cleanup() { git -C "$SITE_REPO" worktree remove --force "$D/repo" 2>/dev/null || true; }
trap cleanup EXIT

step "site: stage, guard and check-site"
python3 "$here/tools/release-all/site.py" "${args[@]}" --platforms "$PLATFORMS" --files "$F" \
    --site "$D/repo" --live "$SITE_LIVE" --stage "$D/stage" | tee "$D/site.out"
grep -q '^SITE PASS' "$D/site.out" || die "site.py did not pass"
removes=()
while read -r p; do removes+=(--remove "$p"); done < <(sed -n 's/^remove: //p' "$D/site.out")

if ((DRY)); then
    rm -rf "$D/stage"
    echo "dry run: the stage passed its guard and check-site; removed, nothing uploaded (would remove: ${removes[*]:-nothing})"
    echo "site: PASS"
    exit 0
fi

step "site: commit the downloads data"
git -C "$D/repo" add data/downloads.json
git -C "$D/repo" commit -q -m "Downloads: $(for a in $APPS; do printf '%s %s ' "$(app_site "$a")" "$(ver_of "$a")"; done)($PLATFORMS)" \
    -m "Written by openhamshack-nb tools/release-all: only these apps' released entries change; the stage was built from a copy of the live dist and checked to differ from it only in their pages and files."

step "site: publish-web.sh site --dry-run"
( cd "$SITE_UPLOADER" && PUBLISH_LOCAL_DIR=$D/stage tools/publish-web.sh site --docroot-is-ours --dry-run "${removes[@]}" )
step "site: publish-web.sh site"
( cd "$SITE_UPLOADER" && PUBLISH_LOCAL_DIR=$D/stage tools/publish-web.sh site --docroot-is-ours "${removes[@]}" ) | tee "$D/publish.out"
grep -q '^publish-web.sh: PASS' "$D/publish.out" || die "publish-web.sh did not report PASS"

step "site: the stage is the live build; the data merged into main"
mv "$SITE_LIVE" "$SITE_LIVE-pre-$RUN"
mv "$D/stage" "$SITE_LIVE"
trap - EXIT
git -C "$SITE_REPO" merge -q --ff-only "$branch"
git -C "$SITE_REPO" worktree remove "$D/repo"
git -C "$SITE_REPO" branch -q -d "$branch"
# The copies collect-downloads.py reads (GUIDE section 6: NB and Radio
# from ~/build/nb-radio-release, macOS only from beta-build/desktop/macos).
for a in $APPS; do
    sub=$( [[ $a == nb ]] && echo nb || echo radio )
    keep=$HOME/build/nb-radio-release/$a mac=$HOME/build/beta-build/desktop/macos/$sub
    mkdir -p "$keep" "$mac"
    for f in "$F"/OpenHamShack-"$(app_site "$a")"-*; do
        case $f in *-macos-arm64.dmg*) dst=$mac ;; *) dst=$keep ;; esac
        slot=${f##*/"$(ver_of "$a")"-}; slot=${slot%.sha256}
        # The same slot's older versions go; this version's files stay.
        find "$dst" -maxdepth 1 -name "OpenHamShack-$(app_site "$a")-*-$slot*" \
            ! -name "OpenHamShack-$(app_site "$a")-$(ver_of "$a")-*" -delete
        cp "$f" "$dst/"
    done
done

step "site: every new download over HTTPS"
bad=0
for f in "$F"/*; do
    case $f in *.sha256) continue ;; esac
    n=${f##*/}
    got=$(curl -sSfL "https://openhamshack.com/downloads/$n?v=$RANDOM$RANDOM" | sha256sum | cut -d' ' -f1)
    if [[ $got == "$(cut -d' ' -f1 < "$f.sha256")" ]]; then echo "live: $n"; else echo "LIVE MISMATCH: $n"; bad=1; fi
done
for ((i = 1; i < ${#removes[@]}; i += 2)); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "https://openhamshack.com/${removes[i]}?v=$RANDOM")
    if [[ $code == 404 ]]; then echo "gone: ${removes[i]}"; else echo "STILL SERVED ($code): ${removes[i]}"; bad=1; fi
done
((bad == 0)) || die "the live downloads page does not match"
echo "site: PASS"
