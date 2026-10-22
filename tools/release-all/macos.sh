#!/bin/bash
# release-all.sh's macOS stage, run on the development VM: for each app,
# the release commit's tree goes to the Mac, which builds it with
# tools/build-macos.sh --sign - Developer ID signed with the Mac's own
# signing keychain, notarised with its keychain profile ohs-notary, and
# stapled (the keychain password, the identity and the notary API key are
# the Mac's and are used where they are; nothing here reads them) - then
# mac-prove.sh checks the image as a user would get it, and the .dmg
# comes back. What mac-one.sh and mac-prove.sh did by hand for NB 0.1.22.
#   tools/release-all/macos.sh <run dir>
#
# The work folder is kept: build-macos.sh's Python, Rust, libraries and
# downloads are most of a build's time. On the external build disk when it
# is attached (MAC_EXT_WORK), else MAC_WORK in the Mac's home; a new one
# is seeded from MAC_SEED's cache, tools and vendor folders. Never deleted
# here. -no-tests: the suite passed once, on Linux, for this tree.
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
: "${MAC_HOST:?no MAC_HOST in the configuration}" "${MAC_WORK:?no MAC_WORK}"
M=$RUN_DIR/mac
mkdir -p "$M/out"

step "macos: the work folder on the Mac"
R=$(ra_ssh "$MAC_HOST" "ext='${MAC_EXT_WORK:-}'
    if [ -n \"\$ext\" ] && [ -d \"\$(dirname \"\$ext\")\" ] && [ -w \"\$(dirname \"\$ext\")\" ]; then echo \"\$ext\"; else echo ~/$MAC_WORK; fi")
[[ -n $R ]] || die "the Mac did not say where to build"
echo "work folder $R"
ra_ssh "$MAC_HOST" "set -e; mkdir -p '$R/work'
    if [ ! -e '$R/work/cache' ] && [ -n '${MAC_SEED:-}' ] && [ -d ${MAC_SEED:-/nonexistent}/cache ]; then
        cp -cR ${MAC_SEED}/cache ${MAC_SEED}/tools ${MAC_SEED}/vendor '$R/work/' 2>/dev/null \
            || cp -R ${MAC_SEED}/cache ${MAC_SEED}/tools ${MAC_SEED}/vendor '$R/work/'
    fi
    df -h '$R' | tail -1"

for a in $APPS; do
    v=$(ver_of "$a") c=$(commit_of "$a") pkg=$(app_pkg "$a")
    dmg=$pkg-$v-arm64.dmg
    step "macos $a $v: source to the Mac"
    git -C "$TREE" archive --format=tar.gz -o "$M/$a-src.tgz" "$c"
    ra_ssh "$MAC_HOST" "rm -rf '$R/src-$a' && mkdir -p '$R/src-$a'"
    ra_scp "$M/$a-src.tgz" "$MAC_HOST:$R/$a.tgz"
    ra_ssh "$MAC_HOST" "tar -xzf '$R/$a.tgz' -C '$R/src-$a' && rm '$R/$a.tgz' && rm -f '$R/work/out/$dmg' '$R/work/out/$dmg.sha256'"

    step "macos $a $v: build, sign, notarise, staple"
    ra_ssh "$MAC_HOST" "ulimit -n 8192; cd '$R' && bash 'src-$a/tools/build-macos.sh' --app $a --work '$R/work' --sign --no-tests" \
        > "$M/$a-build.log" 2>&1 || { tail -n 25 "$M/$a-build.log"; die "build-macos.sh failed (log: $M/$a-build.log)"; }
    tail -n 6 "$M/$a-build.log"

    step "macos $a $v: Gatekeeper and a headless receive-only run"
    ra_ssh "$MAC_HOST" "bash '$R/src-$a/tools/release-all/mac-prove.sh' '$R/work/out/$dmg' '$(app_macname "$a")' $pkg $v '$R/prove'" \
        | tee "$M/$a-prove.out"
    grep -q '^MACPROVE PASS' "$M/$a-prove.out" || die "mac-prove.sh did not pass"

    step "macos $a $v: the image back"
    ra_scp "$MAC_HOST:$R/work/out/$dmg" "$MAC_HOST:$R/work/out/$dmg.sha256" "$M/out/"
    ( cd "$M/out" && sha256sum -c --quiet "$dmg.sha256" ) || die "$dmg did not arrive whole"
done
echo "macos: PASS"
