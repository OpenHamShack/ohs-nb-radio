#!/usr/bin/env bash
# Build openhamshack-nb_<version>_<arch>.deb or openhamshack-radio_<version>_<arch>.deb
# with plain dpkg-deb.
#
# No debhelper: the payload is Python and one prebuilt module, and small,
# so debhelper's rules/control machinery would be pure ceremony for one
# launcher, one desktop entry, one icon, one metainfo file and one man
# page. This script does by hand exactly what debhelper would generate.
#
# Usage: tools/build-deb.sh [nb|ham] [--arch amd64|arm64|all] [version]
#   app       nb (the default: OpenHamShack QO-100 NB) or ham (OpenHamShack Radio)
#   --arch    all (the default) is pure Python, for any machine: FT8/FT4
#             decode and encode with WSJT-X's jt9/ft8code/ft4code. amd64 and
#             arm64 also carry ohsdigi, the Rust decoder and encoder (rust/ohsdigi), built
#             for that architecture by tools/build-ohsdigi.sh into
#             rust/dist/linux-<arch>/ ($OHSDIGI_DIST overrides rust/dist);
#             the package is then Architecture: <arch>. Per-architecture
#             packages rather than one with every binary inside: dpkg then
#             refuses the wrong one outright instead of the program
#             silently falling back, and each download stays small.
#   version   defaults to the contents of <package>/VERSION (ohsnb/VERSION,
#             ohsradio/VERSION; created as 0.1.0 if missing). A first
#             argument that is neither nb nor ham is taken as NB's version,
#             as the script has always been called.
#
# The .deb is written to the CURRENT directory, not the repo, so running
# this from a scratch/temp dir (as the packaging tests do) never leaves a
# build artefact in the tree.
set -euo pipefail

script_dir="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
pkg_src="$repo_root/packaging"

app="nb"
if [ "${1:-}" = "nb" ] || [ "${1:-}" = "ham" ]; then
    app="$1"
    shift
fi
arch="all"
if [ "${1:-}" = "--arch" ]; then
    arch="${2:?--arch needs amd64, arm64 or all}"
    shift 2
fi
case "$arch" in
    all) ;;
    amd64) elf_machine="x86-64" ;;      # readelf -h, lower-cased
    arm64) elf_machine="aarch64" ;;
    *) echo "build-deb.sh: --arch must be amd64, arm64 or all, not $arch" >&2; exit 1 ;;
esac
case "$app" in
    nb)  pkgname="openhamshack-nb";    pydir="ohsnb";    depends_extra="";                 recommends_extra="" ;;
    ham) pkgname="openhamshack-radio"; pydir="ohsradio"; depends_extra=", python3-paramiko"; recommends_extra=", librtlsdr0" ;;
esac

version="${1:-}"
if [ -z "$version" ]; then
    version_file="$repo_root/$pydir/VERSION"
    if [ ! -f "$version_file" ]; then
        echo "0.1.0" > "$version_file"
    fi
    version="$(tr -d ' \t\r\n' < "$version_file")"
fi
if [ -z "$version" ]; then
    echo "build-deb.sh: version is empty (check $pydir/VERSION)" >&2
    exit 1
fi

out_deb="$(pwd)/${pkgname}_${version}_${arch}.deb"

# The prebuilt module, checked before anything is assembled: it must exist
# and be built for the package's architecture (a .so for the wrong machine
# would install cleanly and then never load).
ohsdigi_so=""
if [ "$arch" != "all" ]; then
    ohsdigi_so="${OHSDIGI_DIST:-$repo_root/rust/dist}/linux-$arch/ohsdigi.abi3.so"
    if [ ! -f "$ohsdigi_so" ]; then
        echo "build-deb.sh: no $ohsdigi_so; run tools/build-ohsdigi.sh linux-$arch first" >&2
        exit 1
    fi
    machine="$(LC_ALL=C readelf -h "$ohsdigi_so" | sed -n 's/^ *Machine: *//p')"
    case "${machine,,}" in
        *"$elf_machine"*) ;;
        *) echo "build-deb.sh: $ohsdigi_so is not built for $arch (it is for $machine)" >&2; exit 1 ;;
    esac
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/${pkgname}-build.XXXXXX")"
trap 'rm -rf "$work"' EXIT

root="$work/pkgroot"
lib="$root/usr/lib/$pkgname"
mkdir -p \
    "$root/DEBIAN" \
    "$lib" \
    "$root/usr/bin" \
    "$root/usr/share/applications" \
    "$root/usr/share/icons/hicolor/scalable/apps" \
    "$root/usr/share/metainfo" \
    "$root/usr/share/man/man1" \
    "$root/usr/share/doc/$pkgname"

# --- payload: the app's package and its private copy of ohscore ---------------
# Plain copy, not a build step -- both are pure Python, nothing to compile.
# ohscore (the engine, DSP, modes and UI the two apps share) goes beside the
# app in /usr/lib/<pkgname> rather than into a package of its own: each
# app's .deb carries the core it was cut with, so the two apps never ship
# the same path, install side by side, and never need a version lockstep
# between our own packages (docs/ham/DESIGN-HAM.md section 2.6). Only the
# app's own package goes in: NB's .deb has no ohsradio and HAM's no ohsnb.
# Caches and in-tree dev notes are stripped; nothing else is touched -
# ohscore/data (AD1C's cty.dat and its MIT notice, for the FT8 Country
# column; ohscore/dxcc.py) comes along with the rest of ohscore.
cp -a "$repo_root/$pydir" "$lib/$pydir"
cp -a "$repo_root/ohscore" "$lib/ohscore"
find "$lib/$pydir" "$lib/ohscore" -depth -name '__pycache__' -type d -exec rm -rf {} +
find "$lib/$pydir" "$lib/ohscore" -name '*.py[co]' -delete
rm -f "$lib/ohscore/modes/PERF.md"
# A developer's own build of ohsdigi (tools/build-ohsdigi.sh --install puts
# one in ohscore/, linked against this machine's glibc) is never shipped:
# only the one built for the package's architecture, in the bookworm
# container, goes in.
rm -f "$lib/ohscore/"ohsdigi*.so "$lib/ohscore/"ohsdigi*.pyd
if [ -n "$ohsdigi_so" ]; then
    install -m 644 "$ohsdigi_so" "$lib/ohscore/ohsdigi.abi3.so"
fi

# The shared OpenHamShack libraries (shack_bandplan, shack_client, shack_cw,
# shack_pad, shack_sdr) beside ohscore, exactly the wheels
# tools/vendor/requirements.lock and shack-sdr.lock pin, hash-checked
# (packaging/shack_vendor.py): the band limits, the shared logbook, the
# pad, the CW decoder and the decoder host (RTTY, the codec loader, the
# RTL-SDR and SDRplay sources) need them at run time. shack_sdr is native,
# so an amd64 or arm64 package carries that architecture's wheel and the
# "all" package none: there RTTY and the two receivers are listed with the
# sentence saying why (ohscore/decoders.py), as FT8 falls back to jt9 there.
case "$arch" in
    amd64) shack_platform=linux_x86_64 ;;
    arm64) shack_platform=linux_aarch64 ;;
    all) shack_platform=pure ;;
esac
python3 "$repo_root/packaging/shack_vendor.py" "$lib" "$shack_platform"
find "$lib" -maxdepth 1 -name '*.dist-info' -type d -exec rm -rf {} +
# shack_pad's udev rule is the controller's (group shack-input, its input
# host service), so the copy inside the library would only mislead. The
# desktop's own rule is below.
rm -rf "$lib/shack_pad/udev"

# --- the controller pad's udev rule -----------------------------------------
# Without it a normal user cannot open the AKP03E's hidraw node and the pad
# silently does nothing (Settings › Control pad then says "no permission").
# One per package, named after it, so NB and Radio install side by side;
# the Pluto's rule stays libiio-utils' (90-libiio0.rules), never ours.
install -d "$root/usr/lib/udev/rules.d"
install -m 644 "$pkg_src/openhamshack-pad.rules" "$root/usr/lib/udev/rules.d/60-$pkgname-pad.rules"

# --- launcher ---------------------------------------------------------------
install -m 755 "$pkg_src/$pkgname" "$root/usr/bin/$pkgname"

# --- desktop integration -----------------------------------------------------
install -m 644 "$pkg_src/$pkgname.desktop" "$root/usr/share/applications/$pkgname.desktop"
install -m 644 "$pkg_src/$pkgname.svg" "$root/usr/share/icons/hicolor/scalable/apps/$pkgname.svg"
# An "Amateur Radio" submenu (packaging/hamradio.menu.in says why). Menu
# files are only read from the XDG config dirs, so it lives in /etc and is
# a conffile; each package's copy has its own name so the two never collide.
install -d "$root/etc/xdg/menus/applications-merged" "$root/usr/share/desktop-directories"
sed "s/@PKG@/$pkgname/g" "$pkg_src/hamradio.menu.in" \
    > "$root/etc/xdg/menus/applications-merged/$pkgname.menu"
sed "s/@PKG@/$pkgname/g" "$pkg_src/hamradio.directory.in" \
    > "$root/usr/share/desktop-directories/$pkgname-hamradio.directory"
chmod 644 "$root/etc/xdg/menus/applications-merged/$pkgname.menu" \
    "$root/usr/share/desktop-directories/$pkgname-hamradio.directory"
echo "/etc/xdg/menus/applications-merged/$pkgname.menu" > "$root/DEBIAN/conffiles"
chmod 644 "$root/DEBIAN/conffiles"
sed "s/@VERSION@/$version/" "$pkg_src/$pkgname.metainfo.xml" \
    > "$root/usr/share/metainfo/$pkgname.metainfo.xml"
chmod 644 "$root/usr/share/metainfo/$pkgname.metainfo.xml"

# --- man page (compressed, as Debian policy expects) -------------------------
gzip -n -9 -c "$pkg_src/$pkgname.1" > "$root/usr/share/man/man1/$pkgname.1.gz"
chmod 644 "$root/usr/share/man/man1/$pkgname.1.gz"

# --- doc/copyright ------------------------------------------------------------
sed "s/^Upstream-Name: .*/Upstream-Name: $pkgname/" "$pkg_src/copyright" > "$root/usr/share/doc/$pkgname/copyright"
chmod 644 "$root/usr/share/doc/$pkgname/copyright"

# --- maintainer scripts (the same cache refreshes for both apps) ----------------
install -m 755 "$pkg_src/postinst" "$root/DEBIAN/postinst"
install -m 755 "$pkg_src/postrm" "$root/DEBIAN/postrm"

# --- permissions, belt and braces ---------------------------------------------
# install(1) above already set the right modes; this just guarantees that
# *everything* under usr/ ends up world-readable regardless of the current
# umask, which cp -a does not promise.
find "$root/usr" -type d -exec chmod 755 {} +
find "$root/usr" -type f -exec chmod 644 {} +
chmod 755 "$root/usr/bin/$pkgname"

# --- Installed-Size (KiB), only the files actually installed -----------------
installed_size="$(du -sk "$root/usr" | cut -f1)"

case "$app" in
nb)
    summary="QO-100 narrowband transceiver"
    long=" OpenHamShack QO-100 NB is a native PyQt6 desktop transceiver for the QO-100 amateur
 satellite's narrowband segment. One process owns a software-defined
 radio (the ADALM-Pluto family, or any SoapySDR receive-only device)
 and the whole user interface: a bandscope and waterfall across the
 transponder, beacon and transmit frequency locking, and CW, SSB, FT8,
 FT4, PSK31/63/125, RTTY, FreeDV and SSTV receive modes. A simulated
 transponder lets it run, and be tested, with no radio attached."
    ;;
ham)
    summary="all-band amateur radio SDR transceiver"
    long=" OpenHamShack Radio is a native PyQt6 desktop transceiver for the amateur
 bands, 160 m to 6 cm. One process owns a software-defined radio (the
 ADALM-Pluto family on VHF and up, the Hermes-Lite 2 on HF, or any
 SoapySDR receive-only device) and the whole user interface: a
 bandscope and waterfall with the band plan drawn on it, band stacks,
 SSB, CW, AM, FM with CTCSS and repeater shifts, FT8, FT4, PSK, RTTY,
 FreeDV and SSTV. It holds every transmission inside the UK licence
 class set in Settings and warns when one leaves the RSGB band plan.
 Simulated bands let it run, and be tested, with no radio attached."
    ;;
esac

# avahi-daemon is Recommends, not Depends: without it, libiio 0.26's
# combined scan (what Settings' Pluto "Find" used to rely on alone) fails
# outright rather than just skipping mDNS - discover() in
# ohscore/devices/pluto.py falls back to a USB-only scan and direct IP probes
# so "Find" still works without it, but installing it restores full
# scanning (the Pluto's .local name) and stops libiio's error noise.
# libad9361-0 sets the Pluto's low sample rates with ADI's own FIR (the
# fallback to 2.4 MS/s and software decimation still covers its absence);
# libiio-utils carries the udev rule that lets a user open the Pluto on usb:.
# python3-serial is NB's CI-V link to an IC-9700 used as the transmitter
# (ohscore/rig/civ.py); Recommends, so apt installs it, but nothing else
# needs it and the Hamlib rigctld link works without it.
# python3-paramiko is HAM's SSH client for the Pluto's AD9364 setting
# (ohsradio/plutofix.py). Depends rather than Recommends: the fix is offered
# exactly when a tester's radio cannot reach 2 m, and a missing library
# then would leave them with a button that only says what to install.
# python3-cryptography checks the Ed25519 signature on the update feed
# (ohscore/update.py) before anything in it is believed. Depends: an app
# that cannot check signatures can never update itself, and says so only
# in Help › Check for updates…. It is in every Debian release we support
# and already on most desktops (HAM's paramiko needs it too).
# ohsdigi's own needs (readelf -d / -V): glibc 2.34 at most, as it was
# built on bookworm, and libgcc_s for unwinding. Both are on every system
# that has python3, but a package that carries a binary says so.
# python3-pil: the pad (NB's and Radio's on-screen keys) draws its key faces
# with Pillow; without it the keys come up blank. Recommends, not Depends:
# everything else works and the rest of the window is usable without it, but
# apt installs it by default so nobody meets the blank pad.
# librtlsdr0 (Radio's): the RTL-SDR receiver (shack_sdr.sources, over
# ctypes) and, in the same package, its udev rule and the blacklist that
# keeps the kernel's DVB driver off the dongle. Recommends: only an RTL
# owner needs it. NB offers no RTL-SDR.
# python3-zeroconf: Settings › Controller's "Find controllers" (Bonjour);
# without it the controller's address is typed instead.
# js8call: JS8 receive (ohscore/modes/js8.py), its own package, not wsjtx's.
# Suggests rather than Recommends: one receive-only mode, not the three
# (FT8/FT4/Q65) wsjtx already covers, and js8call is a bigger install (its
# own full Qt GUI) for that one mode - an operator who wants it asks for it.
# wsjtx: an amd64 or arm64 package carries ohsdigi, which decodes and
# encodes FT8, FT4 and Q65, so WSJT-X only adds jt9 as the fallback and the
# shadow - a Suggests, as the Windows and Mac builds stopped carrying it
# (17/10/2026). The "all" package has no ohsdigi, so jt9 is its only
# decoder and it stays a Recommends there.
depends_arch=""
wsjtx_rec=", wsjtx"
wsjtx_sug=""
if [ "$arch" != "all" ]; then
    depends_arch=", libc6 (>= 2.34), libgcc-s1"
    wsjtx_rec=""
    wsjtx_sug=", wsjtx"
fi
cat > "$root/DEBIAN/control" <<EOF
Package: $pkgname
Version: $version
Section: hamradio
Priority: optional
Architecture: $arch
Installed-Size: $installed_size
Depends: python3 (>= 3.11), python3-numpy, python3-pyqt6, python3-pyaudio, python3-cryptography$depends_extra$depends_arch
Recommends: python3-libiio, libiio-utils, libad9361-0, avahi-daemon$wsjtx_rec, libcodec2-1.2 | libcodec2-1.0, python3-soapysdr$recommends_extra, python3-serial, python3-zeroconf, python3-pil
Suggests: soapysdr-module-rtlsdr, soapysdr-module-airspy, js8call$wsjtx_sug
Maintainer: Brian Henderson <noreply@openhamshack.com>
Description: $summary
$long
EOF

# --- md5sums, relative to the package root, usr/ only (DEBIAN/ is metadata) --
( cd "$root" && find usr -type f -exec md5sum {} + ) > "$root/DEBIAN/md5sums"
chmod 644 "$root/DEBIAN/md5sums"

dpkg-deb --build --root-owner-group "$root" "$out_deb" >/dev/null

# Nothing encumbered inside (RADIO-SDR-PLAN 5.5): no AAC or AMBE codec or
# SDRplay's API carried, linked or defined by anything in the package. The
# check is ohs-libs' own, vendored and hash-checked; a finding deletes the
# package, so a failed build leaves nothing that could be published.
if ! python3 "$repo_root/packaging/shack_vendor.py" --check-encumbered "$out_deb" >/dev/null; then
    python3 "$repo_root/packaging/shack_vendor.py" --check-encumbered "$out_deb" >&2 || true
    rm -f "$out_deb"
    echo "build-deb.sh: the package failed the encumbered check" >&2
    exit 1
fi

echo "built $out_deb"
