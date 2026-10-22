# OpenHamShack QO-100 NB and HAM on macOS

First built 07/10/2026: "OpenHamShack QO-100 NB.app" and "OpenHamShack Radio.app" for Apple
Silicon, **unsigned** (ad-hoc signature only). Published the same day,
by Brian's decision, as a separate **macOS preview** on each site
(`0.1.9+mac-preview.1`, built from main after 0.1.9; `release.sh --macos`
below) - not in the update feed, and not a release. This
note is the handover for whoever takes the Mac build further: what is in
it, where each part is pinned, how to build it, how it was proven, and
what signing and notarisation will need. Installing it as a user is in
`docs/INSTALL.md` ("macOS").

## What it is

A PyInstaller `.app` per program, each in a `.dmg` with a link to
Applications, built by `tools/build-macos.sh` on the Mac itself (there is
no cross-build). Bundle ids `com.openhamshack.qo100nb` and
`com.openhamshack.radio` (until 17/10/2026 `com.openhamshack-nb`
and `com.openhamshack-ham`, in bundles named "OpenHamShack NB.app" and
"OpenHamShack HAM.app": an update dragged into Applications lands beside such an
old copy, which the operator then bins; docs/names.md); `Info.plist` carries
`NSMicrophoneUsageDescription` (without it macOS hands the program silence
for a microphone, with no prompt and no error), `NSLocalNetworkUsageDescription`
and `NSBonjourServices` (below), and `LSMinimumSystemVersion`
14.0 - NumPy 2.5's arm64 wheels need macOS 14 (PyQt6 6.11's Qt needs 13),
and the build fails if any binary in the bundle needs later than the plist
says (it said 12.0 until that check found NumPy). Everything that differs from Linux is answered in `ohscore/host.py`
(`MACOS`); the self-update side is in `ohscore/update.py` (`macos`/`dmg`).

**Local Network privacy (macOS 15 and later).** Found live, 07/10/2026,
mac-preview.1: a LibreSDR on a tester's LAN gave libiio "No route to host"
(errno 65) although ping and a direct TCP connect to its port both worked
from the same Mac's Terminal - `Info.plist` had no
`NSLocalNetworkUsageDescription`, so macOS refused the socket with no
prompt and no error, and NB fell back to the simulator rather than saying
why. Both specs now carry it, worded per app (NB has no Hermes-Lite 2;
HAM does). `NSBonjourServices` names `_iio._tcp` - libiio 0.26's own mDNS
service type, confirmed in its source (`iiod/dns-sd.c`, `dns_sd_avahi.c`,
`dns_sd_windows.c` all register or browse exactly that string; the Mac
build's own backend, `dns_sd_bonjour.c`, does the same through
`CFNetServiceBrowser`) - needed because `HAVE_DNS_SD` defaults on for
`APPLE` in libiio's CMakeLists and `tools/build-macos.sh` never turns it
off. HAM's Hermes-Lite 2 discovery (`ohscore/devices/hl2.py`) needs no
Bonjour entry of its own: it is a plain UDP broadcast to port 1024/1025,
never a `dns_sd` browse, and Local Network privacy gates a UDP socket to a
private or broadcast address the same way regardless of protocol - the one
key above is enough. `tests/test_macos_bundle.py` fails the build if
either key is missing from a spec. The error itself: a radio open that
fails on macOS with errno 65 (`EHOSTUNREACH`) or 1 (`EPERM`) to a private,
non-loopback address now gets a clause naming System Settings' Local
Network page (`ohscore/host.py`'s `local_network_hint`, `tests/test_host.py`).

| Where in the .app | What | From |
| --- | --- | --- |
| `Contents/MacOS/openhamshack-nb` | the program (PyInstaller bootloader + Python 3.13.16) | python-build-standalone 20261003, the build uv installs |
| `Contents/Frameworks/PyQt6`, numpy, cryptography... | Python packages | wheels pinned in `packaging/macos/requirements.txt` (= Windows' pins) |
| `.../pyaudio/_portaudio*.so` | PyAudio 0.2.14 with PortAudio v19.7.0 linked in statically | both built from source: PyPI has no Mac wheel of PyAudio |
| `Contents/Frameworks/libiio/libiio.dylib`, `iio.py` | libiio 0.26, network + XML backends, system libxml2 | built from the v0.26 tarball |
| `Contents/Frameworks/libad9361.dylib` | libad9361-iio v0.3 (the Pluto's FIR below 2.1 MS/s) | built from the v0.3 tarball |
| `Contents/Frameworks/libcodec2.dylib` | codec2 1.2.0 (FreeDV) | built from the 1.2.0 tarball |
| `Contents/Frameworks/ohscore/ohsdigi.abi3.so` | ohsdigi, our FT8/FT4/Q65/JS8 decoder and encoder | `rust/ohsdigi`, Rust 1.98.1 |
| `Contents/Resources/ohscore/data/cty.dat` (linked from `Contents/Frameworks/ohscore/data`) | AD1C's country file, Big CTY | `ohscore/data` in the repository, pinned in `cty-source.txt` there |
| `Contents/Resources/THIRD-PARTY.txt`, `licences/` | every licence | `packaging/macos/THIRD-PARTY.txt` |

Not in it: **SoapySDR** (HAM's receive-only SDRs; Linux-only, as on
Windows), libiio's **USB backend** (a Pluto on USB is a CDC-ECM network
interface to macOS, so `ip:192.168.2.1` reaches it with no driver; a
`usb:` URI does not work), **JS8** (left out: no cheap way in for a first build), **FreeDV 2020**
(codec2 is built without LPCNet; 1600, 700C and 700D work), and **WSJT-X**.

### Why there is no WSJT-X in it (17/10/2026)

Until then the app carried WSJT-X 2.7.0's `jt9`, `ft8code` and `q65code`
with their libraries (QtCore 5.15.2, FFTW 3.3.8, Boost, the GCC 8.2.0
runtime), unmodified from `wsjtx-2.7.0-Darwin.dmg`, as ohsdigi's fallback
and shadow. Brian dropped them on every platform. On the Mac two things
were wrong with them:

- **They were Intel-only**, so they ran under Rosetta 2, and macOS now
  warns "Support Ending for Intel-Based Apps" for an app that carries any.
- **In the notarised app `jt9` never decoded at all.** Signed with the
  hardened runtime it aborts on every run, in 0.05 s: the crash report
  shows `abort()` from `libgcc_s.1.dylib`, which `jt9` calls for
  `___enable_execute_stack` (gfortran's nested-function trampolines need
  an executable stack, which the hardened runtime refuses). The unsigned
  copy straight from the .dmg decodes; the same files signed ad hoc with
  `--options runtime` abort too. It took days to notice because NB threw
  away jt9's exit status and stderr (the shadow just said "jt9 0" every
  slot) and because the build's "FT8 decoded by the bundle's jt9" smoke
  test actually decoded with the default decoder, ohsdigi. Both are fixed:
  a failing decoder program is logged (`ohscore/modes/ft8.py`
  `run_decoder_tool`), and the smoke test now says ohsdigi and hides any
  installed WSJT-X (`SHACK_NO_WSJTX=1`).

A WSJT-X the operator puts in Applications is still found
(`ohscore/host.py` `find_tool`) and used as the fallback and the shadow: it
runs as its own, unhardened program, so the trampoline problem does not
arise. If an arm64 jt9 is ever wanted inside the app again: WSJT-X 3.0.2's
Mac build is arm64 (the Mac mini has it in /Applications), but its jt9
does not decode one of ohsdigi's 2.7.0 messages back ("TU; W9XYZ K1ABC R
579 MA", an RTTY-contest message; the 2.7.0 jt9 does); an arm64 jt9 built
from `wsjtx-2.7.0.tgz` needs gfortran; and either would need
`com.apple.security.cs.allow-unsigned-executable-memory` (or
`disable-executable-page-protection`) for its trampolines under the
hardened runtime. The build now refuses any Mach-O without an arm64 slice.

## Where things are pinned

All in `tools/build-macos.sh`'s `pin()` table, by SHA-256: uv 0.12.23,
the python-build-standalone 3.13.16 install-only tarball (and the same
release's full `.tar.zst`, read only for the licence texts of what is
linked into libpython: OpenSSL 3.5.9, SQLite, libffi, expat...),
rustup-init 1.29.1 (toolchain 1.98.1, as `rust/build.Containerfile`),
PortAudio `pa_stable_v190700_20210406.tgz`, the PyAudio 0.2.14 sdist,
libiio 0.26, libad9361-iio v0.3, codec2 1.2.0, and each licence text. Python packages: `packaging/macos/requirements.txt`. The
GPL/LGPL source list, in `sources.txt` format: `packaging/macos/sources.txt`
(not wired into `release.sh` yet - see below).

| File | SHA-256 |
| --- | --- |
| `libiio-0.26.tar.gz` | `fb445fb860ef1248759f45d4273a4eff360534480ec87af64c6b8db3b99be7e5` |
| `libad9361-iio-0.3.tar.gz` | `1dc35dd997e1938a97489fa1f349ee16889f9de8901a2c7af46184468dc90598` |
| `codec2-1.2.0.tar.gz` | `cbccae52b2c2ecc5d2757e407da567eb681241ff8dadce39d779a7219dbcf449` |
| `pa_stable_v190700_20210406.tgz` | `47efbf42c77c19a05d22e627d42873e991ec0c1357219c0d74ce6a2948cb2def` |
| `PyAudio-0.2.14.tar.gz` | `78dfff3879b4994d1f4fc6485646a57755c6ee3c19647a491f790a0895bd2f87` |
| `cpython-3.13.16+20261003-aarch64-apple-darwin-install_only.tar.gz` | `d8975d7df4f08f7b1c7aafcdfacbddcec3d366415f2c1a72b2466b6850815933` |

## Building

On an Apple Silicon Mac with Apple's Command Line Tools
(`xcode-select --install`) - nothing else, no Homebrew, no
administrator, no Rosetta 2:

```
git archive --format=tar <commit> | ssh <mac> 'mkdir -p ~/openhamshack-mac/src && tar -xf - -C ~/openhamshack-mac/src'
cd ~/openhamshack-mac/src && /bin/bash tools/build-macos.sh [--app nb|ham|all] [--work ~/openhamshack-mac] [--no-tests] [--preview <label>]
```

`--preview <label>` (e.g. `mac-preview.1`) makes a build that is not a
release: About and the update check say `0.1.9+mac-preview.1`, and the
image is `openhamshack-nb-0.1.9-mac-preview.1-arm64.dmg`. The label is written
into a VERSION file of the build's own (the spec's `OHSMAC_VERSION_FILE`);
`ohsnb/VERSION` and `ohsradio/VERSION` stay as the other platforms ship them.
`ohscore/update.py` orders a "+label" build as the release before the "+"
(`installed_version`), so the next release is offered to it and that one
is not, and the feed never picks the image up (it looks only for
`<package>-<release>-arm64.dmg`). The smoke test checks the frozen app
reports the version it was given.

Everything goes under `--work` (default `~/openhamshack-mac`): `cache/`
(downloads), `tools/` (uv, Python, rustup and cargo homes), `venv/`,
`vendor/` (the built libraries, licence texts), `build/`
(sources, PyInstaller, `dist/` with the .apps, smoke-test folders) and
`out/` (`<package>-<version>-arm64.dmg` and `.sha256`). A second run
reuses what is built. It writes nothing outside the folder, sets no
`PATH` and no shell profile (rustup runs with `--no-modify-path`; uv
with `UV_NO_CONFIG` and no Python downloads of its own). The Mac's
`/bin/bash` is 3.2, and the script is written for it.

What it checks before it makes a .dmg: PyAudio has PortAudio linked in;
the built libiio loads through iio.py and is 0.26; ohsdigi encodes FT4 as
WSJT-X does; the suite passes under the build's Python with any
installed WSJT-X hidden (unless `--no-tests`); no Qt PDF crept in; the licences in the
bundle and `THIRD-PARTY.txt` agree both ways (`bundle_licences.py`, as on
Windows); the signed bundle verifies (`codesign --verify --deep
--strict`); every Mach-O has an arm64 slice; and the frozen program,
started headless with any installed WSJT-X hidden, runs the simulator,
reaches its own libiio ("No Pluto at ip:127.0.0.1"), names ohsdigi,
cty.dat and codec2 from inside the bundle, "jt9: not installed
(optional; ohsdigi decodes)" and "update signatures: ... self-test
passed" in its start-up facts, decodes the simulator's FT8 with ohsdigi
in 40 s, and opens PortAudio on the default output.

## Proven on the Mac mini, 07/10/2026

M4, 16 GB, macOS 26.5.2, no Homebrew, no admin rights, built over SSH
from a `git archive` of the branch:

- The full suite under the build's Python: 1270 tests, OK, 19 skipped
  (Linux-only: dpkg-deb, /proc, loopback broadcast; tools not on a Mac:
  ft4code, ft8sim, osslsigncode, Pillow; FreeDV 2020), twice running.
  Getting there took fixes in the right layers (host.py's macOS branch,
  the HAM sequencer's ioctl numbers, the FreeDV probe) and four tests
  that only passed at the development PC's speed - the M4 runs the
  unpaced simulator 2.7x faster.
- All smoke tests above, both apps.
- Both .apps opened in the logged-in GUI session with `open` (scratch
  config, simulator, `--no-audio` so no microphone prompt was left on
  the screen): NB's main window 1600x986 on screen, beacon lock locked,
  the multimedia beacon received a file; HAM's 1600x983. A first start
  shows the welcome dialog (720x588) first. `screencapture` is refused
  over SSH (no Screen Recording permission), so the windows were seen
  through CGWindowListCopyWindowInfo instead.
- Sound out: PortAudio on the default output at 48 kHz, no underruns,
  from each frozen app. A BlackHole loopback to prove the samples arrive
  could not be read back: capturing audio from an SSH session blocks on
  the microphone permission.
- That block is why the Radio 0.1.10 dmg's install proof (10/10/2026)
  showed no window: starting the radio opened the microphone with the
  speakers, on the main thread before the window was shown, and the
  open waited on a permission prompt nobody was at the screen to answer.
  NB's proof got its window only because its saved settings named a
  Pluto that was not there, so the radio failed to start before reaching
  the sound card. Since then the microphone is opened only for a voice
  over, a recording or Settings' microphone check (ohscore/audio.py).

Not proven: a Pluto or LibreSDR (no radio was opened), transmitting, the
microphone, and a download through a browser (which adds the quarantine
flag Gatekeeper acts on; a build made on the Mac itself has none).

## Self-update on a Mac

The feed has a `macos`/`arm64` entry of kind `dmg`
(`docs/update-feed.md`). A Mac build downloads and proves it like any
other, then only `open`s it: Finder shows the new app beside
Applications, and the banner says to quit, drag it across and restart.
`ohscore/update.py`'s `install_command` says why it does not install by
itself while unsigned. `tools/update-feed.py write` picks up
`<package>-<version>-arm64.dmg` from the release folder. Nothing puts
one there yet: `release.sh --macos` publishes previews only, whose names
carry a label (`openhamshack-nb-0.1.9-mac-preview.1-arm64.dmg`) and are never
picked up, so no Mac is offered an unsigned image by the feed.

## Publishing a preview

```
tools/release.sh nb  --macos <dir>/openhamshack-nb-0.1.9-mac-preview.1-arm64.dmg  --commit <sha>
tools/release.sh ham --macos <dir>/openhamshack-radio-0.1.9-mac-preview.1-arm64.dmg --commit <sha>
```

On main, with a clean tree; `<sha>` is the commit the image was built
from (the Mac builds from an archive of the tree, so nothing in the image
can say). It checks the name against that commit's VERSION, the
`.sha256`, that the release is published and the name is not; then
publishes on the source site, in a section of its own
(`#openhamshack-nb-macos`, `#openhamshack-radio-macos`), the commit's scrubbed tree
as `openhamshack-nb-0.1.9-mac-preview.1-src.tar.gz` and
`packaging/macos/sources.txt` as it was at that commit - and only then
copies the image, moves older previews to the archive, and rebuilds the
site, whose Download card gets a "macOS (preview)" section (unsigned,
Apple Silicon, macOS 14+, Open Anyway, the microphone, ip: only, what is
missing). The update feed is not written. Upload the source
site first.

## Before releasing it

1. Done for the preview (07/10/2026): `release.sh --macos` publishes the
   source, and the site says how to open an unsigned app.
2. Sign and notarise (below); then a release `.dmg` can go into the feed,
   and `release.sh` needs a release (unlabelled) path beside `--macos`.
3. Rosetta 2: done (17/10/2026) by dropping WSJT-X, the only Intel code
   in the app (above).

## What signing and notarisation will need

- **An Apple Developer Program membership** (Brian's, as 360 Technology
  or himself) and a **Developer ID Application** certificate, its private
  key in a keychain on the build Mac (a separate keychain the script
  unlocks, not the login one; the build would get its password from the
  environment, as the Windows build gets its Azure secret).
- **Signing**: the same inside-out list the script signs ad hoc today,
  with `codesign --force --options runtime --timestamp --sign "Developer
  ID Application: …"` - every dylib, `.so`, framework and executable
  (including the Python extension modules PyInstaller already signs), then the .app. The hardened runtime needs
  entitlements: `com.apple.security.device.audio-input` (the microphone,
  or the TCC prompt never comes), and very likely
  `com.apple.security.cs.allow-unsigned-executable-memory` /
  `disable-library-validation` for Python's ctypes and cffi - to be
  found by trying, starting from none. (WSJT-X's jt9 turned out to need
  executable stack memory and aborted without it; it is no longer
  carried.)
- **Notarisation**: `xcrun notarytool submit <dmg> --wait` with an App
  Store Connect API key (issuer id, key id, `.p8`; kept like the Windows
  signing secret, on the build machine only), then `xcrun stapler staple`
  on the .dmg. `xcrun` is in the Command Line Tools.
- **The .dmg** signed too (`codesign --sign … --timestamp <dmg>`).
- **Self-update** can then install: check the downloaded app's Team ID
  (`codesign -dv`, as `check_authenticode` checks Windows' signer),
  replace the .app, relaunch. The microphone permission survives an
  update once the signature's designated requirement is stable (Team ID
  + bundle id), which an ad-hoc signature is not.
