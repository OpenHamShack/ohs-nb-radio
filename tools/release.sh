#!/bin/bash
# Publish a QO-100 NB or Radio release: build the .deb and rebuild the public site
# in one step, so a version is never on the site without being
# downloadable, or downloadable without a checksum beside it.
#   tools/release.sh [nb|ham] <version>      e.g. tools/release.sh 0.2.0
#                                                 tools/release.sh ham 0.1.0
# The app is nb (OpenHamShack QO-100 NB, the default, as the script has always been
# called) or ham (OpenHamShack Radio), the same first argument tools/build-deb.sh
# takes. Writes <package>_<version>_{amd64,arm64,all}.deb and their .sha256
# into $RELEASES (default /srv/openhamshack-nb-releases or
# /srv/openhamshack-ham-releases: the release host, where each site is served from that
# same folder), then rebuilds index.html there. amd64 and arm64 carry
# ohsdigi, the Rust FT8/FT4 encoder, built from the release commit by
# tools/build-ohsdigi.sh in its bookworm container (podman); all is the
# pure-Python package for any other machine. The same run builds the
# Windows ohsdigi.pyd, for the Windows build to take (tools/build-windows.ps1
# -Ohsdigi; the run ends by saying where it is). Before any of that, the
# release commit's own source, <package>-<version>-src.tar.gz, is made into
# $BUILDS and published on the shared source site ($SOURCE_SITE) in this
# app's section; if that fails the run stops with nothing published.
#
# Refuses a dirty tree: a release must be exactly a commit, so ohsnb/VERSION
# (ohsradio/VERSION) always names the code that was actually built. Refuses to
# re-publish a version whose .deb is already in the folder - a box or a
# browser that already has those bytes under that name must never see
# different ones under it; a fix is a new version.
#
# The release commit is "Release <version>" for NB, as it always was, and
# "Release HAM <version>" for HAM: both apps live in one repository, and
# tools/site-build.py finds each app's releases (and so its release notes)
# by its own marker. Run it on main: the notes follow main's first-parent
# history, so a release commit made on a branch and merged later is not
# found there.
#
#   tools/release.sh [nb|ham] --windows <path>/<package>-<version>-setup.exe [--allow-unsigned]
# Adds the Windows installer to a release already published here. It is
# built on Windows (tools/build-windows.ps1 [-App ham]) from the release
# commit, so it can only exist after that commit does - hence a second step
# rather than part of the first. It must be this app's installer, name the
# version ohsnb/VERSION (ohsradio/VERSION) names and whose .deb is already in
# the folder (an installer never appears for a version the site does not
# offer), its .sha256 beside it must match its bytes (a copy damaged on the
# way from the Windows machine stops here), it must carry a valid
# Authenticode signature by 360 Technology with a timestamp (an unsigned
# -NoSign test build, or anyone else's, stops here; see authenticode_ok
# below), and, as with the .deb, a version's .exe is never replaced.
#
# Both steps end by writing and signing the app's update feed,
# $RELEASES/update.json and update.json.sig (tools/update-feed.py write;
# docs/update-feed.md is the contract), from which every installed copy
# learns of the release: the first lists the .debs (and keeps the previous
# installer, still on offer, for Windows until this version's arrives), the
# second adds the installer and signs again. The key is checked before
# anything is committed - a release whose feed every client would refuse
# must not happen at all. Upload the feed LAST: payload, then pages, then
# update.json.sig and update.json; the run says so.
#
# The third-party source the installer's licences require is published on
# the shared source site ($SOURCE_SITE, default /srv/source-site, served as
# https://openhamshack.com/source/; tools/source-site.py, and
# docs/source-site.md for why and how) as this app's manifest,
# <package> (openhamshack-nb or openhamshack-radio; openhamshack-nb and openhamshack-ham
# before the rename): the lines of packaging/windows/sources.txt whose
# installers field names NB or HAM. That is done first, and the installer
# is refused unless every tarball is there and verified. Until 06/10/2026
# each product site had its own source/ folder instead; see
# --retire-product-source below.
#
# Each site offers only its newest installer (from 0.1.4). Once the new one
# is in place, the app's older <package>-*-setup.exe files and their
# .sha256 move out of $RELEASES into $ARCHIVE (default ${RELEASES}-archive,
# beside the site and not part of it; created if need be, nothing ever
# deleted), and the source site is rebuilt, which archives the tarballs no
# manifest names any more. Older .debs stay: the reason is the source, which
# the GPL and LGPL oblige us to offer for whatever we distribute, for as
# long as we do. The .deb carries none of that third-party code; every
# installer does, and keeping each old one on offer meant keeping a
# matching set of tarballs for each. One installer per site, one set.
# They stay only until the upload, though: tools/publish.sh nb|ham then
# prunes every package the new feed does not name, .debs included, from
# this folder and the site into the same $ARCHIVE (from 19/10/2026). The
# run ends with a "remove from the remote site:" list - the same files, by
# their path on the site - for whoever uploads to the public host to delete
# there, since an upload adds files and never takes any away; the source
# site's own list comes before it.
#
#   tools/release.sh [nb|ham] --macos <path>/<package>-<version>-<label>-arm64.dmg --commit <sha>
# Puts a macOS preview on the app's site (Brian, 07/10/2026: the Mac apps
# go up now, unsigned, ahead of the next release). Built on an Apple
# Silicon Mac by tools/build-macos.sh --preview <label> from a `git
# archive` of <sha>, which must be in this branch's history. Mirrors
# --windows: the name must be this app's and carry the version
# ohsnb/VERSION (ohsradio/VERSION) has at <sha>, that release's .deb must be
# in the folder, the .sha256 beside it must match, and a published name is
# never replaced. Its source goes on the source site first, in a section
# of its own (<package>-macos): the scrubbed tree of <sha> and the
# third-party list packaging/macos/sources.txt as it was at <sha>; if
# either cannot be published, neither is the image. Older previews move to
# $ARCHIVE. The update feed is NOT written - see the step for why.
#
#   tools/release.sh [nb|ham] --macos-release <path>/<package>-<version>-arm64.dmg --commit <sha>
# Puts a signed, notarised and stapled release .dmg (tools/build-macos.sh
# --sign) in the folder and the feed - what --macos refuses, and what was
# done by hand for NB 0.1.22 / Radio 0.1.21. The checks are --macos's
# (this app's name, the version at <sha>, that release's .deb in the
# folder, the .sha256, never a published name replaced); the source is the
# release's own tarball (the same commit's tree, so the one already made
# in $BUILDS) under <package>-macos, with packaging/macos/sources.txt as it
# was at <sha>. Older images, previews included, move to $ARCHIVE. Linux
# cannot check notarisation: the Mac's spctl and stapler did, in
# tools/release-all/mac-prove.sh, before the .dmg left it.
#
# For tools/release-all.sh, which runs the suite once and makes both apps'
# release commits before anything is built, so that the three platforms
# can build at once:
#   tools/release.sh [nb|ham] <version> --commit-only
#       the suite and the release commit, and nothing else (no folder, key
#       or host is needed: it runs on the development VM);
#   RELEASE_SUITE_PROVED=<tree>
#       skips the suite when this tree differs from <tree>, the one the
#       caller ran it on, in ohsnb/VERSION and ohsradio/VERSION alone;
#   a HEAD that is already "<marker> <version>" with that VERSION is used
#       as the release commit rather than committing again;
#   RELEASE_NO_FEED=1
#       leaves update.json alone in every step: release-all.sh writes it
#       once, at the end, from the feed that is live.
#
#   tools/release.sh [nb|ham] --retire-product-source
# Once, after the shared source site is uploaded and live: moves this
# product site's old source/ folder into $ARCHIVE/source (never deleted)
# and prints what to remove from the remote product site. It refuses
# unless the public source site already has this app's manifest and every
# tarball in it at full size (tools/source-site.py check --live) - the
# installers on offer must never be without their source, even for the
# length of an upload. source/index.html stays, rewritten by site-build.py
# as a pointer to the source site: installers already out there name
# <site>/source/ in their THIRD-PARTY.txt, and those directions must still
# lead somewhere.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
cd "$here"

app=nb
if [[ ${1:-} == nb || ${1:-} == ham ]]; then
    app=$1
    shift
fi
case $app in
    nb)  pkg=openhamshack-nb;    pydir=ohsnb;  marker="Release";     default_out=/srv/openhamshack-nb-releases
         title="OpenHamShack QO-100 NB";  word=NB;  home=https://openhamshack.com/desktop/nb/ ;;
    ham) pkg=openhamshack-radio; pydir=ohsradio; marker="Release HAM"; default_out=/srv/openhamshack-ham-releases
         title="OpenHamShack Radio"; word=HAM; home=https://openhamshack.com/desktop/ham/ ;;
esac
# The release folders keep their own names: they are this host's, and
# publish.sh maps them onto openhamshack.com.
RELEASES=${RELEASES:-$default_out}
ARCHIVE=${ARCHIVE:-${RELEASES%/}-archive}
export SOURCE_SITE=${SOURCE_SITE:-/srv/source-site}
source_site() { python3 "$here/tools/source-site.py" "$@"; }
update_feed() { python3 "$here/tools/update-feed.py" "$@"; }
# The feed write at the end of each step, unless release-all.sh will write
# it itself (RELEASE_NO_FEED): written per step, the folder's feed would
# be signed three times from whatever the folder held, which need not be
# what is live.
feed_write() {
    if [[ -n ${RELEASE_NO_FEED:-} ]]; then
        echo "update feed not written (RELEASE_NO_FEED: tools/release-all.sh writes it from the live feed)"
        return 0
    fi
    update_feed write --app "$app" --releases "$RELEASES" --version "$1"
}
# Said at the end of each publishing step, before any list of files to
# remove, so whoever uploads cannot miss the order: a client that saw the
# new feed before the files it names would find them missing.
upload_order() {
    echo "upload order: the packages and installers first, then the pages (index.html last of those),"
    echo "  then update.json.sig and update.json - the feed always last"
}

# The same $ARCHIVE as the installers': screenshots no page shows any more
# (site-build.py names them by their bytes, so every re-render leaves some)
# go there too rather than being deleted.
site_build() {
    if [[ $app == nb ]]; then
        python3 "$here/tools/site-build.py" --out "$RELEASES" --archive "$ARCHIVE"
    else
        python3 "$here/tools/site-build.py" --app "$app" --out "$RELEASES" --archive "$ARCHIVE"
    fi
}

# Move a file off the site into a folder of the archive. Same bytes already
# archived: nothing is lost by dropping the site's copy. Different bytes:
# leave both, say so, and fail.
archive_to() {
    local f=$1 dir=$2 name=${1##*/}
    mkdir -p "$dir"
    if [[ -e $dir/$name ]]; then
        if ! cmp -s "$f" "$dir/$name"; then
            echo "$name: $dir already holds a different file of that name; left on the site" >&2
            return 1
        fi
        rm -f "$f"
    else
        mv "$f" "$dir/$name"
    fi
}

if [[ ${1:-} == --retire-product-source ]]; then
    src=$RELEASES/source
    shopt -s nullglob dotglob
    old=()
    for f in "$src"/*; do
        if [[ -f $f && ${f##*/} != index.html ]]; then old+=("$f"); fi
    done
    (( ${#old[@]} )) || { echo "$src holds nothing to retire"; exit 0; }
    source_site check "$pkg" --live \
        || { echo "the source site does not offer all of $pkg's source yet (above); upload" \
                  "$SOURCE_SITE first - $src stays as it is" >&2; exit 1; }
    moved=() failed=0
    for f in "${old[@]}"; do
        if archive_to "$f" "$ARCHIVE/source"; then moved+=("source/${f##*/}"); else failed=1; fi
    done
    site_build
    echo "moved into $ARCHIVE/source:"
    printf '  %s\n' "${moved[@]}"
    echo "upload index.html and source/index.html (now a pointer to the source site), then"
    echo "remove from the remote site:"
    printf '  %s\n' "${moved[@]}"
    exit $failed
fi

# The installer's Authenticode signature, checked on this Linux host with
# osslsigncode (apt install osslsigncode) against the one root Artifact
# Signing chains to, kept in the repository: Debian's CA bundle has no
# code-signing roots. Valid means the signature covers these exact bytes,
# the chain reaches that root, the signer is 360 Technology, and a
# timestamp - verified against the same root - fixes when it was made, so
# the 3-day certificate is judged at that moment and not today. Revocation
# is not checked here (-ignore-crl): Microsoft's CRL server answers with a
# content type OpenSSL refuses, so every check would fail; build-windows.ps1
# already ran Windows' own verification, revocation included, before
# writing the .sha256 that matched above. Rejected: trusting a "signed" line
# in the build log - a log says what happened to some file on the build
# machine, not to these bytes. OSSLSIGNCODE names a stand-in for the tests.
authenticode_ok() {
    local exe=$1 out
    local ossl=${OSSLSIGNCODE:-osslsigncode}
    local root="$here/packaging/windows/microsoft-identity-verification-root-2020.pem"
    command -v "$ossl" >/dev/null \
        || { echo "osslsigncode is not installed, so $(basename "$exe")'s signature cannot be checked (apt install osslsigncode)" >&2; return 1; }
    if ! out=$("$ossl" verify -in "$exe" -CAfile "$root" -TSA-CAfile "$root" -ignore-crl 2>&1); then
        # No signature at all is the one failure --allow-unsigned may pass
        # (return 2); a signature that does not verify never is.
        if grep -q "No signature found" <<< "$out"; then
            echo "$(basename "$exe") is not signed" >&2
            return 2
        fi
        echo "$(basename "$exe") has no valid Authenticode signature (unsigned, as a -NoSign build is, or not chaining to Artifact Signing's root):" >&2
        grep -E "verification|No signature|rror" <<< "$out" | sed 's/^/  /' >&2
        return 1
    fi
    # The first Subject after "Signer's certificate:" is the signing
    # certificate's own; the chain and the timestamp authority follow it.
    local signer
    signer=$(awk '/^Signer.s certificate:/ {f=1} f && /Subject:/ {sub(/^[ \t]*Subject: */, ""); print; exit}' <<< "$out")
    [[ $signer =~ /O=360\ Technology(/|$) ]] \
        || { echo "$(basename "$exe") is signed by '$signer', not 360 Technology" >&2; return 1; }
    grep -q "^Signature verification: ok" <<< "$out" \
        || { echo "$(basename "$exe"): osslsigncode did not report the signature verified" >&2; return 1; }
    { grep -q "Timestamp time:" <<< "$out" && grep -q "^Timestamp Server Signature verification: ok" <<< "$out"; } \
        || { echo "$(basename "$exe") is signed without a valid timestamp; it would stop verifying when its 3-day certificate expires" >&2; return 1; }
    echo "$(basename "$exe"): signed by $signer, $(grep -m1 'Timestamp time:' <<< "$out" | sed 's/^[ \t]*//')"
}

if [[ ${1:-} == --windows ]]; then
    exe=${2:?usage: release.sh [nb|ham] --windows <${pkg}-<version>-setup.exe>}
    name=$(basename "$exe")
    ver=$(tr -d ' \t\r\n' < "$pydir/VERSION")
    [[ $name == "${pkg}-${ver}-setup.exe" ]] \
        || { echo "$name is not ${pkg}-${ver}-setup.exe ($pydir/VERSION is $ver)" >&2; exit 1; }
    [[ -e "$RELEASES/${pkg}_${ver}_all.deb" || -e "$RELEASES/${pkg}_${ver}_amd64.deb" ]] \
        || { echo "release $ver is not published in $RELEASES; run release.sh $app $ver first" >&2; exit 1; }
    [[ ! -e "$RELEASES/$name" ]] \
        || { echo "$name is already published; a fix is a new version" >&2; exit 1; }
    [[ -f "$exe.sha256" ]] || { echo "no $exe.sha256 beside it (build-windows.ps1 writes one)" >&2; exit 1; }
    ( cd "$(dirname "$exe")" && sha256sum -c --quiet "$name.sha256" ) \
        || { echo "$name does not match its .sha256" >&2; exit 1; }
    # --allow-unsigned: the OpenHamShack beta ships unsigned installers
    # (BETA-PLAN "Installers are unsigned for the beta"; the download page
    # says what Windows shows). It passes an installer with no signature
    # at all and nothing else: one signed by anyone but 360 Technology, or
    # without a timestamp, or that osslsigncode cannot check, is refused
    # as before, since that is a wrong file rather than an unsigned one.
    rc=0
    authenticode_ok "$exe" || rc=$?
    if (( rc == 2 )) && [[ ${3:-} == --allow-unsigned ]]; then
        echo "$name: publishing it UNSIGNED (--allow-unsigned): Windows will warn whoever runs it" >&2
    elif (( rc != 0 )); then
        if (( rc == 2 )); then
            echo "$name has no valid Authenticode signature (unsigned, as a -NoSign build is); --allow-unsigned publishes a beta build anyway" >&2
        fi
        echo "not publishing $name" >&2
        exit 1
    fi
    # The installer carries GPL and LGPL code by others (Qt, PyQt6,
    # libiio, codec2, ...; WSJT-X too until 17/10/2026), whose licences require their source to
    # be offered with it, on the shared source site. Published (fetched,
    # or re-checked byte for byte) here, every time, so publishing an
    # installer cannot forget it, and refused if any tarball is missing or
    # wrong - before the .exe is copied, so no installer is ever offered
    # without its source. Nothing leaves the source site yet: the
    # installer this one replaces is still on offer until the copy below.
    source_site publish "$pkg" "$here/packaging/windows/sources.txt" \
            --carried-by "$word" --title "$title" --home "$home" \
        || { echo "the source for $name's third-party components is not complete on the source site" \
                  "($SOURCE_SITE); not publishing it (tools/source-site.py says why above)" >&2; exit 1; }
    cp "$exe" "$exe.sha256" "$RELEASES/"
    # The feed now offers this installer to Windows, signed again. Before
    # the older installers leave below: until this line the feed named the
    # previous one, which must still be there for anyone fetching it.
    feed_write "$ver" \
        || { echo "$name is in $RELEASES but the update feed could not be signed (above); installed" \
                  "copies will not be offered it until update-feed.py write succeeds" >&2; exit 1; }

    # Only now, with the new installer in place, do the old ones and their
    # source leave: until this point they were what the site offered.
    moved=() archive_failed=0
    shopt -s nullglob
    for old in "$RELEASES/$pkg"-*-setup.exe "$RELEASES/$pkg"-*-setup.exe.sha256; do
        f=${old##*/}
        [[ $f == "$name" || $f == "$name.sha256" ]] && continue
        if archive_to "$old" "$ARCHIVE"; then moved+=("$f"); else archive_failed=1; fi
    done
    shopt -u nullglob
    source_site build || archive_failed=1

    site_build
    echo "published $name in $RELEASES"
    upload_order
    if (( ${#moved[@]} )); then
        echo "moved off the site into $ARCHIVE:"
        printf '  %s\n' "${moved[@]}"
        echo "remove from the remote site:"
        printf '  %s\n' "${moved[@]}"
    else
        echo "nothing moved off the site; nothing to remove from the remote site"
    fi
    if (( archive_failed )); then
        echo "$name is published, but something older could not be archived (see above)" \
             "and is still on the site until that is sorted out" >&2
        exit 1
    fi
    exit 0
fi

if [[ ${1:-} == --macos ]]; then
    usage="usage: release.sh [nb|ham] --macos <${pkg}-<version>-<label>-arm64.dmg> --commit <the commit it was built from>"
    dmg=${2:?$usage}
    [[ ${3:-} == --commit && -n ${4:-} ]] || { echo "$usage" >&2; exit 2; }
    name=$(basename "$dmg")
    # The commit the .dmg was built from (tools/build-macos.sh runs on the
    # Mac from a `git archive` of it, so nothing in the image can say which;
    # whoever built it says). It must be on this branch - run on main, as
    # for every step here - so the source published for it stays findable.
    commit=$(git rev-parse --verify --quiet "${4}^{commit}") \
        || { echo "$4 is not a commit in this repository" >&2; exit 1; }
    git merge-base --is-ancestor "$commit" HEAD \
        || { echo "$commit is not in this branch's history; merge it and run this on main" >&2; exit 1; }
    # The source tarball below reads the checkout's .gitattributes and
    # scrub list: uncommitted edits to either would change what is published.
    [[ -z "$(git status --porcelain)" ]] || { echo "uncommitted changes; commit first" >&2; exit 1; }
    ver=$(git show "$commit:$pydir/VERSION" | tr -d ' \t\r\n')
    # A preview only, for now: <package>-<release>-<label>-arm64.dmg, as
    # build-macos.sh --preview names it, whose About says <release>+<label>.
    # A release .dmg (no label) would belong in the update feed, and the
    # Mac does not update itself from one until the build is signed and
    # notarised (docs/macos.md) - so this refuses one rather than putting a
    # Mac release on the site with no feed entry behind it.
    label_re="^${pkg}-${ver//./\\.}-([0-9A-Za-z]+([.-][0-9A-Za-z]+)*)-arm64\\.dmg\$"
    [[ $name =~ $label_re ]] \
        || { echo "$name is not ${pkg}-${ver}-<label>-arm64.dmg ($pydir/VERSION at $commit is $ver); only" \
                  "a labelled preview (build-macos.sh --preview) can be published this way" >&2; exit 1; }
    label=${BASH_REMATCH[1]}
    [[ -e "$RELEASES/${pkg}_${ver}_all.deb" || -e "$RELEASES/${pkg}_${ver}_amd64.deb" ]] \
        || { echo "release $ver is not published in $RELEASES; a preview is published after the release it follows" >&2; exit 1; }
    [[ ! -e "$RELEASES/$name" ]] \
        || { echo "$name is already published; a fix is a new preview label" >&2; exit 1; }
    [[ -f "$dmg.sha256" ]] || { echo "no $dmg.sha256 beside it (build-macos.sh writes one)" >&2; exit 1; }
    ( cd "$(dirname "$dmg")" && sha256sum -c --quiet "$name.sha256" ) \
        || { echo "$name does not match its .sha256" >&2; exit 1; }
    BUILDS=${BUILDS:-${RELEASES%/}-build}
    for d in "$RELEASES" "$BUILDS" "$SOURCE_SITE"; do
        t=$d
        while [[ ! -e "$t" ]]; do t=$(dirname "$t"); done
        [[ -w "$t" ]] || { echo "cannot write $d (create it: sudo install -d -o $USER $d); not publishing" >&2; exit 1; }
    done

    # Its source, on the shared source site, before the image is offered:
    # a section of its own, <package>-macos, apart from the Windows
    # installer's. The two sets differ (the Mac carries FFTW 3.3.8, GCC
    # 8.2.0's libquadmath and libad9361; Windows FFTW 3.3.10, GCC 8.1.0,
    # libusb, dfu-util...), and each must stay exactly as long as its own
    # download does - one manifest per download means a Windows release
    # never takes the Mac's source away, nor this the Windows installer's.
    # First the program's own: the build commit's whole tree, scrubbed as a
    # release's is (tools/source-site.py tarball), since the image carries
    # code no release tarball has. Then the third-party list, as it was at
    # that commit - what this image was built with, not what main says now.
    # If either fails, nothing is copied.
    mac_project="${pkg}-macos" mac_title="$title for macOS (preview)"
    shown="$ver+$label"
    SRC_TARBALL=$(source_site tarball "$here" "$commit" "${pkg}-${ver}-${label}" --out "$BUILDS") \
        && source_site publish-own "$mac_project" "$SRC_TARBALL" --licence GPL-3.0-or-later \
               --carried "$word $shown for macOS (preview): its .dmg" \
               --covers "$title $shown for macOS itself - the whole repository at commit $commit, which the .dmg was built from" \
               --title "$mac_title" --home "$home" \
        || { echo "the source of $name could not be published on the source site ($SOURCE_SITE;" \
                  "tools/source-site.py says why above); not publishing it" >&2; exit 1; }
    tmp_list=$(mktemp -d)
    trap 'rm -rf "$tmp_list"' EXIT
    git show "$commit:packaging/macos/sources.txt" > "$tmp_list/sources.txt" \
        || { echo "$commit has no packaging/macos/sources.txt; not publishing $name" >&2; exit 1; }
    source_site publish "$mac_project" "$tmp_list/sources.txt" --carried-by "$word" \
            --title "$mac_title" --home "$home" \
        || { echo "the source for $name's third-party components is not complete on the source site" \
                  "($SOURCE_SITE); not publishing it (tools/source-site.py says why above)" >&2; exit 1; }
    cp "$dmg" "$dmg.sha256" "$RELEASES/"
    # Deliberately NOT update_feed write: an installed Mac copy is offered
    # nothing until a signed, notarised release .dmg exists. An unsigned
    # image offered through the feed would teach every Mac user to click
    # through Gatekeeper on each update, and the feed's whole point is that
    # what it offers is proven ours - ad-hoc signing proves nothing about
    # who built it. The name keeps it out of a later release's feed as
    # well: update-feed.py looks only for <package>-<release>-arm64.dmg.

    # One Mac image per site, as with the installers: the older previews
    # and their .sha256 leave now that this one is in place. Their source
    # stays on the source site (own lines are never dropped) - harmless,
    # and the record of what was once offered.
    moved=() archive_failed=0
    shopt -s nullglob
    for old in "$RELEASES/$pkg"-*-arm64.dmg "$RELEASES/$pkg"-*-arm64.dmg.sha256; do
        f=${old##*/}
        [[ $f == "$name" || $f == "$name.sha256" ]] && continue
        if archive_to "$old" "$ARCHIVE"; then moved+=("$f"); else archive_failed=1; fi
    done
    shopt -u nullglob
    source_site build || archive_failed=1

    site_build
    echo "published $name ($title $shown, built from $commit) in $RELEASES; the update feed is unchanged"
    echo "published $(basename "$SRC_TARBALL") and the $mac_project manifest on the source site," \
         "$SOURCE_SITE (upload it with the rest of that folder, before the product site)"
    echo "upload order: the source site first, then $name and its .sha256, then the pages (index.html last)"
    if (( ${#moved[@]} )); then
        echo "moved off the site into $ARCHIVE:"
        printf '  %s\n' "${moved[@]}"
        echo "remove from the remote site:"
        printf '  %s\n' "${moved[@]}"
    else
        echo "nothing moved off the site; nothing to remove from the remote site"
    fi
    if (( archive_failed )); then
        echo "$name is published, but something older could not be archived (see above)" >&2
        exit 1
    fi
    exit 0
fi

if [[ ${1:-} == --macos-release ]]; then
    usage="usage: release.sh [nb|ham] --macos-release <${pkg}-<version>-arm64.dmg> --commit <the release commit>"
    dmg=${2:?$usage}
    [[ ${3:-} == --commit && -n ${4:-} ]] || { echo "$usage" >&2; exit 2; }
    name=$(basename "$dmg")
    commit=$(git rev-parse --verify --quiet "${4}^{commit}") \
        || { echo "$4 is not a commit in this repository" >&2; exit 1; }
    git merge-base --is-ancestor "$commit" HEAD \
        || { echo "$commit is not in this branch's history" >&2; exit 1; }
    [[ -z "$(git status --porcelain)" ]] || { echo "uncommitted changes; commit first" >&2; exit 1; }
    ver=$(git show "$commit:$pydir/VERSION" | tr -d ' \t\r\n')
    [[ $(git log -1 --format=%s "$commit") == "$marker $ver" ]] \
        || { echo "$commit is not the release commit \"$marker $ver\"; a release image is built from one" >&2; exit 1; }
    [[ $name == "${pkg}-${ver}-arm64.dmg" ]] \
        || { echo "$name is not ${pkg}-${ver}-arm64.dmg ($pydir/VERSION at $commit is $ver)" >&2; exit 1; }
    [[ -e "$RELEASES/${pkg}_${ver}_all.deb" || -e "$RELEASES/${pkg}_${ver}_amd64.deb" ]] \
        || { echo "release $ver is not in $RELEASES; run release.sh $app $ver first" >&2; exit 1; }
    [[ ! -e "$RELEASES/$name" ]] || { echo "$name is already published; a fix is a new version" >&2; exit 1; }
    [[ -f "$dmg.sha256" ]] || { echo "no $dmg.sha256 beside it (build-macos.sh writes one)" >&2; exit 1; }
    ( cd "$(dirname "$dmg")" && sha256sum -c --quiet "$name.sha256" ) \
        || { echo "$name does not match its .sha256" >&2; exit 1; }
    BUILDS=${BUILDS:-${RELEASES%/}-build}
    # The release's own source tarball, made by the release step from this
    # same commit: the image's program source is exactly that tree.
    SRC_TARBALL="$BUILDS/${pkg}-${ver}-src.tar.gz"
    [[ -f $SRC_TARBALL ]] || { echo "no $SRC_TARBALL (release.sh $app $ver makes it); not publishing $name" >&2; exit 1; }
    mac_project="${pkg}-macos" mac_title="$title for macOS"
    source_site publish-own "$mac_project" "$SRC_TARBALL" --licence GPL-3.0-or-later \
            --carried "$word $ver for macOS: its .dmg" \
            --covers "$title $ver for macOS itself - the whole repository at commit $commit, which the .dmg was built from" \
            --title "$mac_title" --home "$home" \
        || { echo "the source of $name could not be published on the source site ($SOURCE_SITE); not publishing it" >&2; exit 1; }
    tmp_list=$(mktemp -d)
    trap 'rm -rf "$tmp_list"' EXIT
    git show "$commit:packaging/macos/sources.txt" > "$tmp_list/sources.txt" \
        || { echo "$commit has no packaging/macos/sources.txt; not publishing $name" >&2; exit 1; }
    source_site publish "$mac_project" "$tmp_list/sources.txt" --carried-by "$word" \
            --title "$mac_title" --home "$home" \
        || { echo "the source for $name's third-party components is not complete on the source site" \
                  "($SOURCE_SITE); not publishing it (tools/source-site.py says why above)" >&2; exit 1; }
    cp "$dmg" "$dmg.sha256" "$RELEASES/"
    feed_write "$ver" \
        || { echo "$name is in $RELEASES but the update feed could not be signed (above)" >&2; exit 1; }
    # One Mac image per site: the older ones, previews included, leave now.
    moved=() archive_failed=0
    shopt -s nullglob
    for old in "$RELEASES/$pkg"-*-arm64.dmg "$RELEASES/$pkg"-*-arm64.dmg.sha256; do
        f=${old##*/}
        [[ $f == "$name" || $f == "$name.sha256" ]] && continue
        if archive_to "$old" "$ARCHIVE"; then moved+=("$f"); else archive_failed=1; fi
    done
    shopt -u nullglob
    source_site build || archive_failed=1
    site_build
    echo "published $name ($title $ver for macOS, built from $commit) in $RELEASES"
    upload_order
    if (( ${#moved[@]} )); then
        echo "moved off the site into $ARCHIVE:"
        printf '  %s\n' "${moved[@]}"
        echo "remove from the remote site:"
        printf '  %s\n' "${moved[@]}"
    else
        echo "nothing moved off the site; nothing to remove from the remote site"
    fi
    (( ! archive_failed )) || { echo "$name is published, but something older could not be archived (see above)" >&2; exit 1; }
    exit 0
fi

ver=${1:?usage: release.sh [nb|ham] <version> [--commit-only] | release.sh [nb|ham] --windows <setup.exe> | release.sh [nb|ham] --macos <dmg> --commit <sha> | release.sh [nb|ham] --macos-release <dmg> --commit <sha>}
commit_only=0
[[ ${2:-} == --commit-only ]] && commit_only=1

[[ -z "$(git status --porcelain)" ]] || { echo "uncommitted changes; commit first" >&2; exit 1; }

# The suite was run by the caller (tools/release-all.sh) on the tree
# $RELEASE_SUITE_PROVED: that is proof for this tree only if the two differ
# in nothing but the VERSION files the release commits write. Anything
# else and the suite runs here as it always has.
suite_proved() {
    local t=${RELEASE_SUITE_PROVED:-} other
    [[ -n $t ]] || return 1
    if ! git cat-file -e "$t^{tree}" 2>/dev/null; then
        echo "RELEASE_SUITE_PROVED=$t is not a tree in this repository; running the suite" >&2
        return 1
    fi
    other=$(git diff --name-only "$t" HEAD -- . ':(exclude)ohsnb/VERSION' ':(exclude)ohsradio/VERSION')
    if [[ -n $other ]]; then
        echo "the suite was proved on $t, but this tree differs from it in more than VERSION; running it:" >&2
        sed 's/^/  /' <<< "$other" >&2
        return 1
    fi
    echo "suite: proved green on tree ${t:0:12} by the caller; not run again"
}

release_commit() {
    # Already made (by --commit-only, before the platforms were built from
    # it): used as it is, so every platform's package names one commit.
    if [[ $(git log -1 --format=%s) == "$marker $ver" && $(tr -d ' \t\r\n' < "$pydir/VERSION") == "$ver" ]]; then
        echo "HEAD $(git rev-parse --short HEAD) is already \"$marker $ver\"; using it as the release commit"
        return 0
    fi
    if ! suite_proved; then
    # Every test, by discovery rather than a hand-kept list: a list can go
    # stale and quietly stop running a suite before a release. Both apps'
    # tests, whichever is being released: they share ohscore, so a core change
    # must not ship in one having broken the other unnoticed.
    # One interpreter per module (tools/run-suite-split.sh), not one for the
    # whole of `unittest discover`: by NB 0.1.22 (2,352 tests) the single
    # interpreter grew past 14 GB on the release host and then aborted with no summary at
    # all - a Qt timer left by one module's window fired after that module's
    # scratch home was gone, and PyQt6 aborts on an exception in a slot - so
    # the release refused itself with no failing test to show. Per module,
    # each module's memory and timers end with it, and a crash costs one line.
    # SUITE_JOBS runs that many modules at once (default 1; the UI modules are
    # heavy, so only raise it on a machine with the memory for it). Red
    # modules are run again alone, up to SUITE_RERUNS times (default 2; RERUN_RED
    # in run-suite-split.sh says why): on 18/10 a loaded host left a different
    # three or four timing-paced modules red after a single rerun, every one
    # of which passed alone. One that fails every time stops the release.
    if ! out=$(RERUN_RED=${SUITE_RERUNS:-2} "$here/tools/run-suite-split.sh" -j "${SUITE_JOBS:-1}" 2>&1); then
        echo "tests fail; not releasing" >&2
        echo "$out" >&2
        exit 1
    fi
    fi
    echo "$ver" > "$pydir/VERSION"
    git add "$pydir/VERSION"
    git commit -q --allow-empty -m "$marker $ver"
}

if (( commit_only )); then
    release_commit
    echo "release commit $(git rev-parse HEAD)"
    exit 0
fi

DEB_ARCHES=(amd64 arm64 all)
for a in "${DEB_ARCHES[@]}"; do
    [[ ! -e "$RELEASES/${pkg}_${ver}_${a}.deb" ]] \
        || { echo "${pkg}_${ver}_${a}.deb is already published; use a new version" >&2; exit 1; }
done

# Everything this run will write must be writable before the release
# commit is made: a folder it cannot create (the -build folder under /srv,
# which is root's) used to fail after "Release <v>" was committed, leaving
# a release commit with no packages behind it.
BUILDS=${BUILDS:-${RELEASES%/}-build}
# Checked without creating anything, so a refused run leaves no trace: the
# folder itself if it exists, else the nearest parent that does.
for d in "$RELEASES" "$BUILDS" "$SOURCE_SITE"; do
    t=$d
    while [[ ! -e "$t" ]]; do t=$(dirname "$t"); done
    [[ -w "$t" ]] \
        || { echo "cannot write $d (create it: sudo install -d -o $USER $d); not releasing" >&2; exit 1; }
done

# The release key, before anything is committed: a release is not out
# until its feed is signed, and a feed signed by a key the apps do not
# trust would be refused by every installed copy (update-feed.py pubkey
# fails unless ohscore/update.py lists the key; docs/update-feed.md says how
# to make one).
update_feed pubkey >/dev/null \
    || { update_feed pubkey >&2 || true; echo "no usable release key; not releasing" >&2; exit 1; }

release_commit

# The program's own source, published before any binary of it exists: the
# apps are PyQt6 programs (GPL) whose Windows installers ship only
# bytecode, and from NB 0.1.5 / HAM 0.1.6 every package carries ohsdigi,
# compiled from a port of WSJT-X (GPL). The repository is private, so the
# release commit's whole tree goes up as a tarball on the shared source
# site, in this app's section, and stays there for as long as any of this
# version's packages is offered - which, since every .deb stays, is for
# ever. Made reproducibly (tools/source-site.py tarball: the same commit
# always gives the same bytes) into this release's build folder, beside
# the ohsdigi binaries, and kept there. packaging/source-scrub.txt is
# applied as it is made, and refuses the tarball if an internal host name,
# address or account has crept back into the tree: the run then stops
# here, with the release commit made - reword the source, undo the
# commit and run again. If it cannot be published, nothing is: no
# package of a version may be offered without its source.
SRC_TARBALL=$(source_site tarball "$here" HEAD "${pkg}-${ver}" --out "$BUILDS") \
    && source_site publish-own "$pkg" "$SRC_TARBALL" --licence GPL-3.0-or-later \
           --carried "$word $ver: every package and installer of it" \
           --covers "$title $ver itself - the whole repository at its release commit $(git rev-parse HEAD)" \
           --title "$title" --home "$home" \
    || { echo "${pkg}-${ver}'s own source could not be published on the source site ($SOURCE_SITE;" \
              "tools/source-site.py says why above), so nothing of $ver is published. The commit" \
              "\"$marker $ver\" is made: once the cause is fixed, undo it (git reset --hard HEAD^)" \
              "and run release.sh again" >&2; exit 1; }

# ohsdigi for every platform, from the commit just made: Linux amd64 (which
# build-ohsdigi.sh also loads and encodes with in bookworm's Python 3.11),
# Linux arm64, and the Windows .pyd. Into a folder of this release's own
# beside the site and not part of it ($BUILDS, default ${RELEASES}-build),
# so no earlier or developer build can end up in the packages, and the
# exact binaries each package carries - and the .pyd the Windows build
# must take - are kept with their SHA256SUMS.
OHSDIGI_DIST="$BUILDS/${pkg}-${ver}-ohsdigi"
rm -rf "$OHSDIGI_DIST"
mkdir -p "$OHSDIGI_DIST"
"$here/tools/build-ohsdigi.sh" --out "$OHSDIGI_DIST"

mkdir -p "$RELEASES"
for a in "${DEB_ARCHES[@]}"; do
    if [[ $app == nb ]]; then
        ( cd "$RELEASES" && OHSDIGI_DIST="$OHSDIGI_DIST" "$here/tools/build-deb.sh" --arch "$a" "$ver" )
    else
        ( cd "$RELEASES" && OHSDIGI_DIST="$OHSDIGI_DIST" "$here/tools/build-deb.sh" "$app" --arch "$a" "$ver" )
    fi
    ( cd "$RELEASES" && sha256sum "${pkg}_${ver}_${a}.deb" > "${pkg}_${ver}_${a}.deb.sha256" )
done

site_build
# Last, once every file it names is in the folder.
feed_write "$ver" \
    || { echo "${pkg} $ver is built but its update feed could not be signed (above); run" \
              "tools/update-feed.py write --app $app --version $ver once the cause is fixed" >&2; exit 1; }
echo "published ${pkg}_${ver}_{amd64,arm64,all}.deb in $RELEASES"
echo "published $(basename "$SRC_TARBALL") on the source site, $SOURCE_SITE (upload it with the rest of that folder)"
echo "the Windows build takes $OHSDIGI_DIST/windows-amd64/ohsdigi.pyd (build-windows.ps1 -Ohsdigi)"
upload_order
