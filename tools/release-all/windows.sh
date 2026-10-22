#!/bin/bash
# release-all.sh's Windows stage, run on the development VM: for each app,
# the release commit's tree and an ohsdigi.pyd built here from it go to
# the Windows build VM, which builds and signs the installer
# (tools/build-windows.ps1: the Artifact Signing secret is used there and
# never leaves it), installs it over the previous release and checks it
# (win-check.ps1); the signed installer comes back. The steps and scripts
# are the ones NB 0.1.19-0.1.22 were built with by hand.
#   tools/release-all/windows.sh <run dir>
#
# ohsdigi.pyd is built here, not taken from the Linux stage's release.sh,
# so the two stages run at once; it is the same source and the build is
# reproducible (0.1.21's was byte-identical to 0.1.20's), and promote.sh
# refuses the release unless this one's SHA-256 is release.sh's.
#
# Build folders on the VM, <WIN_ROOT>\<version>-<app>, are kept: the
# newest becomes the next one's download cache. win-prep.ps1 keeps the
# newest two per app (this one and the one before) to bound the disk, and
# a folder of the same name (a second run of a version) is reused.
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=lib.sh
source "$here/tools/release-all/lib.sh"
load_run "$1"
: "${WIN_HOST:?no WIN_HOST in the configuration}" "${WIN_ROOT:?no WIN_ROOT}"
W=$RUN_DIR/win
mkdir -p "$W/out"
# scp and PowerShell both take forward slashes on Windows.
wroot=${WIN_ROOT//\\//}
ps() { local s=$1; shift; ra_ssh "$WIN_HOST" "powershell -NoProfile -ExecutionPolicy Bypass -File $wroot/release-all/$s $*" | tr -d '\r'; }

step "windows: ohsdigi.pyd from the release commit"
"$TREE/tools/build-ohsdigi.sh" --out "$W/ohsdigi" windows-amd64
pyd=$W/ohsdigi/windows-amd64/ohsdigi.pyd
sha256sum < "$pyd" | cut -d' ' -f1 > "$W/ohsdigi.sha256"

step "windows: rtlsdr.dll for Radio from the release commit"
"$TREE/tools/build-rtlsdr-windows.sh" --out "$W/rtlsdr"

step "windows: the scripts to the VM"
ra_ssh "$WIN_HOST" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '$wroot/release-all' | Out-Null\""
ra_scp "$TREE/tools/release-all/win-prep.ps1" "$TREE/tools/release-all/win-build.ps1" \
    "$TREE/tools/release-all/win-check.ps1" "$WIN_HOST:$wroot/release-all/"

for a in $APPS; do
    v=$(ver_of "$a") c=$(commit_of "$a") pkg=$(app_pkg "$a")
    step "windows $a $v: source and ohsdigi to the VM"
    git -C "$TREE" archive --format=tar.gz -o "$W/$a-src.tar.gz" "$c"
    ra_scp "$W/$a-src.tar.gz" "$WIN_HOST:$wroot/release-all/rel-$v-$a-src.tar.gz"
    ra_scp "$pyd" "$WIN_HOST:$wroot/release-all/rel-$v-$a-ohsdigi.pyd"
    ra_scp "$W/ohsdigi/windows-amd64/SHA256SUMS" "$WIN_HOST:$wroot/release-all/rel-$v-$a-SHA256SUMS"
    if [ "$a" = ham ]; then
        ra_scp "$W/rtlsdr/rtlsdr.dll" "$WIN_HOST:$wroot/release-all/rel-$v-$a-rtlsdr.dll"
        ra_scp "$W/rtlsdr/SHA256SUMS" "$WIN_HOST:$wroot/release-all/rel-$v-$a-rtlsdr-SHA256SUMS"
    fi

    step "windows $a $v: prepare the build folder"
    ps win-prep.ps1 -Root "$wroot" -App "$a" -V "$v" | tee "$W/$a-prep.out"
    grep -q '^PREP PASS' "$W/$a-prep.out" || die "win-prep.ps1 did not pass"

    step "windows $a $v: build and sign"
    ps win-build.ps1 -Root "$wroot" -App "$a" -V "$v" | tee "$W/$a-build.out"
    grep -q '^BUILD PASS' "$W/$a-build.out" || die "the Windows build did not pass (its log: $WIN_ROOT\\$v-$a\\build-$a.log)"

    step "windows $a $v: install over the previous release and check"
    ps win-check.ps1 -Root "$wroot" -App "$a" -V "$v" | tee "$W/$a-check.out"
    grep -q '^WINCHECK PASS' "$W/$a-check.out" || die "win-check.ps1 did not pass"

    step "windows $a $v: the signed installer back"
    ra_scp "$WIN_HOST:$wroot/$v-$a/out/$pkg-$v-setup.exe" "$WIN_HOST:$wroot/$v-$a/out/$pkg-$v-setup.exe.sha256" "$W/out/"
    ( cd "$W/out" && sha256sum -c --quiet "$pkg-$v-setup.exe.sha256" ) || die "$pkg-$v-setup.exe did not arrive whole"
done
echo "windows: PASS"
