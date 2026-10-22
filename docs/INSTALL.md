# Installing OpenHamShack QO-100 NB

OpenHamShack QO-100 NB ships as a `.deb` per architecture, built with plain
`dpkg-deb` -- no debhelper build, and no post-install step that does
anything beyond refreshing desktop/icon caches:

| Package | For | FT8/FT4 decoding and encoding |
| --- | --- | --- |
| `openhamshack-nb_<version>_amd64.deb` | PCs and laptops (64-bit Intel/AMD) | ohsdigi, built in |
| `openhamshack-nb_<version>_arm64.deb` | Raspberry Pi 4/400/5/500, 64-bit Pi OS | ohsdigi, built in |
| `openhamshack-nb_<version>_all.deb` | anything else (32-bit Pi OS, ...) | WSJT-X's `jt9`, `ft8code`/`ft4code` (install `wsjtx`) |

`dpkg --print-architecture` says which one a machine takes. The three are
otherwise identical: Python, plus, in the first two, ohsdigi - our own
FT8/FT4/Q65 decoder and encoder, a Rust port of WSJT-X 2.7.0's (`rust/ohsdigi`,
`docs/digimodes-rust.md`) - as one prebuilt module,
`/usr/lib/openhamshack-nb/ohscore/ohsdigi.abi3.so`. Releases before ohsdigi were
`_all.deb` only.

## Building the package

```
tools/build-ohsdigi.sh                      # ohsdigi for every platform, in a bookworm container
tools/build-deb.sh --arch amd64            # version comes from ohsnb/VERSION
tools/build-deb.sh --arch arm64 0.2.0      # or override it explicitly
tools/build-deb.sh 0.2.0                   # --arch all (the default): no ohsdigi
```

`build-ohsdigi.sh` needs podman (it builds in `rust/build.Containerfile`:
Debian bookworm, so the module needs glibc 2.34 at most and loads on Pi OS
bookworm, with the Rust toolchain pinned by image digest) and writes
`rust/dist/<target>/` with a `SHA256SUMS`; two builds of one commit give
identical bytes. `build-deb.sh --arch` takes the module from there and
refuses one built for another architecture. `tools/release.sh` does all of
this from the release commit. For running from source,
`tools/build-ohsdigi.sh --host --install` builds with the host's own cargo
and puts the module in `ohscore/`; without it, FT8/FT4 encode with
`ft8code`/`ft4code` as the `all` package does.

The `.deb` is written to the current directory, not the repository, so
build from a scratch directory if you don't want it in your working tree.

## Installing

```
sudo apt install ./openhamshack-nb_<version>_amd64.deb     # or _arm64 / _all
```

Using `apt install ./...` rather than `dpkg -i` lets apt pull in the
`Depends` from your normal repositories in the same step. Optional
features (digital modes, hardware SDR support) come from `Recommends`
and `Suggests` below -- apt installs `Recommends` by default; add
anything from `Suggests` yourself if you want it.

## Upgrading OpenHamShack Radio from before 17/10/2026

Until 17/10/2026 OpenHamShack Radio's package was `openhamshack-ham`
(NB's package name, `openhamshack-nb`, has never changed). The new
`openhamshack-radio` package does not Conflict with or Replace the old
one - apt installs it as a separate package - so remove `openhamshack-ham`
yourself once `openhamshack-radio` is in (`sudo apt remove openhamshack-ham`).
Settings, the logbook and recordings stay in their own folders under the
old name and are not moved: copy `~/.config/openhamshack-ham` and
`~/.local/share/openhamshack-ham` across by hand if you want them under
`openhamshack-radio`. `$OHSNB_CONF` and `$OHSNB_DATA` (and `$OHSRADIO_*`)
are still read when the new `$OHS_NB_CONF`/`$OHS_NB_DATA` (`$OHS_RADIO_*`)
are not set.

## What runs where

The engine (`ohsnb/` and the `ohscore/` it is built on) only needs NumPy; the window needs PyQt6; audio
needs PortAudio via `pyaudio`. Everything else -- the SDR backends, FT8/FT4
decoding, FreeDV -- is optional: a missing optional package disables that
one feature with a sentence telling you which package to install, and
never stops the program.

| Package | Why | Required? |
| --- | --- | --- |
| `python3` (>= 3.11) | the interpreter | yes |
| `python3-numpy` | the DSP, block-vectorised | yes |
| `python3-pyqt6` | the window | yes |
| `python3-pyaudio` | PortAudio bindings, mic/speaker | yes |
| `python3-libiio` | talk to the Pluto family (TX+RX) | recommended |
| `avahi-daemon` | Pluto discovery by mDNS (Settings → Radio → Find) | recommended |
| `wsjtx` | for the `all` package, which has no ohsdigi: `jt9` decodes FT8/FT4/Q65 and `ft8code`/`ft4code`/`q65code` encode them. For `amd64`/`arm64` only the fallback decoder and the shadow check | recommended for `all`; suggested otherwise |
| `libcodec2-1.2` or `libcodec2-1.0` | FreeDV | recommended |
| `python3-soapysdr` | any SoapySDR receive-only SDR | recommended |
| `soapysdr-module-rtlsdr` | RTL-SDR support for the above | suggested |
| `soapysdr-module-airspy` | Airspy support for the above | suggested |
| `js8call` | `js8`, decodes JS8 Normal (receive only - there is no encoder here yet, ohscore/modes/js8.py) | suggested |

## Package name differences across distributions

Checked by hand against `apt-cache show` on this host (Debian 13,
"trixie") and against packages.debian.org / packages.ubuntu.com for the
others, since none of `bookworm`, Ubuntu or Raspberry Pi OS was available
to query directly from here.

- **`libcodec2-1.2` vs `libcodec2-1.0`** -- the one real split. Debian
  13 (trixie) and Ubuntu 24.04 (noble) ship codec2 1.2.x as
  `libcodec2-1.2`; Debian 12 (bookworm) ships codec2 1.0.x as
  `libcodec2-1.0` (1.0.5-1). The control file already lists both as
  alternatives (`libcodec2-1.2 | libcodec2-1.0`) so apt picks whichever
  exists. Older still (bullseye) used `libcodec2-0.9`, not covered here
  since bullseye is out of scope.
- **Everything else above keeps the same name** on bookworm, trixie,
  Ubuntu 24.04+, and Mint (which tracks Ubuntu's LTS bases, so a Mint
  release built on noble or newer matches noble's names). Versions
  differ -- e.g. `python3-libiio` is 0.25-4build2 on Ubuntu noble and
  0.26-2 on trixie -- but `apt`/`dpkg` resolve that from the `Depends`
  line without any name change needed.
- **Raspberry Pi OS** (bookworm and trixie, arm64) draws these specific
  packages straight from the matching Debian suite rather than a
  Raspberry Pi-specific overlay, so bookworm-image Pis need the
  `libcodec2-1.0` side of the alternative and trixie-image Pis need
  `libcodec2-1.2`, exactly as on a laptop running the same suite.
- `wsjtx` is built for `arm64` in both bookworm and trixie, so it
  installs on a Pi 400/500 the same way it does on a laptop.
- `python3-pyqt6` is in Debian's **main** archive from bookworm onward
  (6.4.2-1 in bookworm, 6.9.0-2 in trixie) and in Ubuntu's main from
  noble onward -- no PPA or backport needed on any of the four targets.
- `python3-soapysdr`, `soapysdr-module-rtlsdr` and
  `soapysdr-module-airspy` live in Debian's `hamradio` section / Ubuntu's
  `universe`, present under the same names on all four targets. One
  wrinkle worth knowing if a build ever breaks on bookworm specifically:
  bookworm's SoapySDR ABI generation briefly produced a parallel
  `soapysdr0.8-module-airspy` package alongside the plain-named one; the
  plain name resolves correctly on bookworm today, which is what the
  `Suggests` line uses throughout.

## Pluto discovery needs avahi-daemon

Settings → Radio → Find (`ohscore.devices.pluto.discover()`) asks libiio for
every Pluto-family radio it can see. On libiio 0.26, if `avahi-daemon`
isn't installed and running, libiio's combined scan fails outright --
not just the mDNS/network half of it, the USB half too -- so a Pluto that
is plugged in and working (`iio_info -u usb:...` succeeds) can be reported
as not found. `discover()` works around this: it falls back to a
USB-only scan and to probing a short list of likely IP addresses
directly (`ip:192.168.2.1` always, plus the Pluto's own `.1` address on
any USB-network interface it finds), neither of which needs Avahi. That
fallback is why avahi-daemon is a `Recommends`, not a `Depends`: Find
still works without it, just without resolving the Pluto's `.local`
mDNS name and without the convenience of one scan covering everything.
Installing avahi-daemon restores the full scan and stops libiio printing
"Unable to create Avahi DNS-SD client" to the terminal.

## USB access to a Pluto over libiio

Network access (`ip:192.168.2.1`, the Pluto's default) needs no special
permission -- it's a TCP connection. USB access (`usb:...`) needs the
calling user to have access to the USB device node, which is normally a
udev rule's job.

This package ships **no udev rule of its own**. `libiio0` -- a hard
dependency of `python3-libiio` on every target above -- already installs
one:

```
$ dpkg -L libiio0 | grep udev
/usr/lib/udev/rules.d/90-libiio0.rules
```

```
SUBSYSTEM=="usb", PROGRAM=="/bin/sh -c '/usr/bin/iio_info -S usb=%s{idVendor}:%s{idProduct} | grep %s{idVendor}:%s{idProduct}'", RESULT!="", MODE="666"
```

Two things worth knowing about that rule rather than assuming it just
works:

1. It probes with `iio_info`, which ships in `libiio-utils`, not in
   `python3-libiio`. If `libiio-utils` isn't installed, the rule's
   `PROGRAM` test fails silently and the device node keeps its default
   (root-only) permissions. Install `libiio-utils` if USB access to a
   Pluto, Pluto+, LibreSDR or Pluto nano (Analog Devices `0456:b673`
   or `0456:b672`, all under the same AD936x IIO driver) doesn't work
   out of the box.
2. It grants `MODE="666"` -- world read/write -- rather than scoping
   access to the logged-in session with the `uaccess` tag the way udev
   handles most removable hardware now. That is Debian's choice to make
   in its own package, not ours to override from here, and not a reason
   to ship a second, conflicting rule for the same device: two rules
   matching the same `SUBSYSTEM=="usb"` event is how a device silently
   ends up with whichever rule's permissions ran last.

If a future Debian libiio drops this rule, or you're on a non-Debian
target, the fix is a small `uaccess`-tagged rule for the two Pluto USB
IDs above (`TAG+="uaccess"`), which is what we'd add here at that point
-- not duplicated in advance against a rule that already does the job.

## An IC-9700 as the transmitter (CI-V over USB)

Settings › Transmitter can make an IC-9700 the uplink transmitter
(docs/USERGUIDE.md, "Transmitting with an IC-9700"). Its CI-V link needs
`python3-serial`, which the package Recommends, so apt installs it; the
Hamlib rigctld link needs nothing from us but Hamlib itself
(`sudo apt install libhamlib-utils` for `rigctld`).

The radio's USB port appears as `/dev/ttyUSB0` (or a higher number), and
only members of the `dialout` group may open it:

```
sudo adduser $USER dialout      # then log out and in again
```

`ls /dev/serial/by-id/` gives a name that stays the same whatever order
USB devices are found in; it can be typed into the CI-V port field as it is.

## Verifying the build without installing it

`tests/test_packaging.py` builds the real `.deb`, inspects it with
`dpkg-deb -c`/`-f`/`-I`, extracts it with `dpkg-deb -x` into a throwaway
root, and runs the extracted launcher (`--headless --no-audio --seconds
2`) to prove the engine actually starts -- all without `apt install`ing
anything system-wide. Run it with everything else:

```
python3 -m unittest discover -s tests
```

## Updates: the signed feed

From the release after NB 0.1.8 / HAM 0.1.8, an installed copy updates
itself (Brian, 07/10/2026). Each site carries `update.json`, a small
manifest naming the newest package for each platform with its size and
SHA-256, and `update.json.sig`, its Ed25519 signature by the
"360 Technology OpenHamShack release key" (made as the OpenHamShack release key; the same key). The app checks the signature
against the public key built into it, then the download against the
manifest, and on Linux installs it with `pkexec apt-get install -y` (the
desktop's own password prompt; with no pkexec it shows the command
instead). Windows also checks the installer's Authenticode signer, runs
it unattended once the program has closed, and the installer starts the
program again. The whole contract - fields, signature, key id, rotation,
what a client checks in what order - is `docs/update-feed.md`.

For whoever releases:

- **The key** lives only on the release host, at
  `~/.config/openhamshack-release/ed25519.key` (where it was made; a key at
  `~/.config/openhamshack-release/ed25519.key` is used instead once there is one). `tools/update-feed.py keygen`
  makes it once and prints a line for `RELEASE_KEYS` in
  `ohscore/update.py`; that line must be committed and released before
  any feed it signs is any use. Back the key up offline. Until the key
  exists and is listed, `tools/release.sh` refuses to release at all.
- **`tools/release.sh`** writes and signs the feed after the `.deb`s
  (keeping the previous installer's entry for Windows until the new one
  arrives) and again after `--windows`.
- **Upload the feed last**: packages and installers, then the pages,
  then `update.json.sig`, then `update.json` - release.sh prints this.
  Then `curl` both with `?v=<random>` and compare with the folder.
- `tools/update-feed.py verify [--app ham]` checks a release folder as a
  client would.

Nothing is sent but a plain GET with `User-Agent: openhamshack-nb/<version>`.
The check runs a few seconds after start-up and daily; Settings ›
Station › Check for updates turns it off, and Help › Check for updates…
checks by hand. A copy run from source never checks by itself.

## Tools this process would have used, if installed

Neither `lintian` nor `desktop-file-validate` nor `appstreamcli` is
installed on the host this package was built and tested on, and none
was installed in order to build it (a packaging tool has no business
pulling in packages of its own without being asked). The `.desktop`
file, the AppStream metainfo and the control file were checked by hand
against the relevant specifications instead. If you have `lintian`
available:

```
lintian openhamshack-nb_<version>_all.deb
```

Expected, accepted findings: no `debian/changelog` (this isn't going
through the Debian archive, and fabricating a changelog with invented
history would be worse than not having one) and no `Homepage` field
(the project has no public URL yet).

# Windows 10/11 (64-bit)

The Windows build is `openhamshack-nb-<version>-setup.exe`: an Inno Setup
installer around a PyInstaller bundle (Python 3.13, NumPy, PyQt6,
PortAudio, libiio 0.26 and ohsdigi inside it - nothing else to
install to get the window up on the simulator, to reach a Pluto over the
network, or for FT8), which also offers to install ADI's PlutoSDR USB
drivers. Built by
`tools/build-windows.ps1` on a Windows machine; see
"Building it" below.

What the Windows build covers, and what it does not:

| Feature | Windows |
| --- | --- |
| Window, simulator, all DSP, beacon/TX lock | built in |
| Sound cards (PortAudio, MME devices) | built in; no sound card = runs silent |
| FreeDV | built in (`libcodec2.dll` from FreeDV-GUI 1.9.9.2) |
| FT8 / FT4 / Q65 | built in, both ways: ohsdigi, our own decoder and encoder (below), and our own `cty.dat` for the Country column; no WSJT-X install needed |
| JS8 (receive only) | **not yet**: js8call's own `js8` decoder is not bundled - see "JS8 on Windows" below |
| Pluto family (ADALM-Pluto, Pluto+, LibreSDR, Pluto nano) | built in (libiio 0.26); the installer's **PlutoSDR USB drivers** option for a Pluto on USB (below) |
| SoapySDR receive-only SDRs | **Linux-only for now** |
| An IC-9700 as the transmitter, CI-V over USB | built in (pyserial); install Icom's USB driver for the radio, which then shows as two COM ports |
| An IC-9700 through Hamlib `rigctld` | **install Hamlib separately**: the Windows zip from <https://github.com/Hamlib/Hamlib/releases> (`hamlib-w64-<version>.zip`), then run `bin\rigctld.exe -m 3081 -r COM5 -s 115200` (your port) and leave it running |

Settings and the log live in `%APPDATA%\openhamshack-nb\` (`config.json`,
`ui.json`, and `data\` for the log, recordings and SSTV pictures);
`OHS_NB_CONF` / `OHS_NB_DATA` override them as on Linux. Uninstalling leaves
that folder alone, as removing the .deb leaves `~/.config`.

## FT8 and FT4 on Windows

Both modes, and Q65, are decoded and encoded by ohsdigi,
`_internal\ohscore\ohsdigi.pyd`: our own decoder and encoder, a Rust port of
WSJT-X 2.7.0's, cross-built on Linux (`docs/digimodes-rust.md`). It is
also what lets Windows send FT4 at all: no WSJT-X for Windows ships
`ft4code` (2.7.0 nor 3.0.1).

The installer carries no WSJT-X (since 17/10/2026). From 0.1.4 it had
WSJT-X 2.7.0's `jt9.exe` and `ft8code.exe` and their DLLs in
`_internal\wsjtx\`, as ohsdigi's fallback and as the shadow that checked
every slot; ohsdigi has decoded what `jt9` decodes since then, so they were
dropped. A WSJT-X you install yourself is still used for that check:
`ohscore.host.find_tool` looks on PATH, then in WSJT-X's install folders
(`C:\WSJT\wsjtx\bin`, Program Files). Without one, the log's start-up
facts say `jt9: not installed (optional; ohsdigi decodes)`.

`cty.dat`, AD1C's country file for the FT8 Country column, is
`_internal\ohscore\data\cty.dat`: the same pinned Big CTY edition every
package carries (`ohscore/data/cty-source.txt` names it, with the SHA-256
of its download; `tools/cty-refresh.py` refreshes it before a release).
Looked for in the data folder (`%APPDATA%\openhamshack-nb\data`) first, then
that one, then an installed WSJT-X's.

cty.dat's MIT notice is in `packaging/windows/THIRD-PARTY.txt` and the
installed `_internal\licences\`.

## JS8 on Windows

Not bundled, so JS8 receive (ohscore/modes/js8.py; Linux: the `js8call`
package's `js8` CLI decoder) is unavailable on Windows for now. This is
deliberately left as a follow-up rather than added speculatively: js8call
is its own project (a WSJT-X fork, not a WSJT-X plugin), its own Windows
build of `js8.exe` carries its own Qt 5/FFTW/GCC-runtime DLL set which may
not be the exact versions already pinned in `packaging/windows/sources.txt`
for WSJT-X 2.7.0, and the sources.txt convention here (module docstring,
HANDOVER.md) needs each tarball's provenance checked by hand before it is
added to an installer, which was not done in this session - adding an
unverified entry would be exactly the kind of change that file's own rules
exist to prevent. A future session: find js8call's own upstream release
tarball (not Debian's `+ds`-repackaged source, which strips non-free
pieces before building `js8.exe`'s actual DLL set is confirmed), pin it in
`packaging/windows/sources.txt`, and add `js8.exe` plus its DLLs to
`packaging/windows/openhamshack-nb.spec` (as WSJT-X's `jt9.exe` was until
17/10/2026).

## Source for the third-party parts

The installer carries GPL and LGPL code by others (Qt 6, PyQt6, libiio
and its libraries, codec2, the dfu-util inside ADI's drivers; until
17/10/2026 WSJT-X with Qt 5, FFTW and libquadmath too). The exact source release of each is published on
the source site the OpenHamShack projects share, in each app's section
(<https://openhamshack.com/source/#openhamshack-nb>,
<https://openhamshack.com/source/#openhamshack-radio>), which says which
tarball covers which files; each tarball is stored there once, however many
installers carry it. The list, with a SHA-256 per file, is
`packaging/windows/sources.txt`; `tools/release.sh --windows` publishes
the app's lines of it there with `tools/source-site.py` and will not
publish an installer until every tarball is present and verified.
`docs/source-site.md` is how the site works and how another project joins.

## Signed by 360 Technology

Installers from the next releases on (NB after 0.1.4, HAM after 0.1.5)
are code-signed: the setup program, its uninstaller, `openhamshack-nb.exe`,
`openhamshack-nb-console.exe` and `ohsdigi.pyd` (and HAM's equivalents) carry an Authenticode signature by
**360 Technology** (Kilmarnock, GB), issued through Microsoft's Artifact
Signing and timestamped, so Windows names the publisher where it used to
say "Unknown publisher", and any change to a file after signing shows up as
a broken signature. To check one: right-click -> Properties -> Digital
Signatures, or in PowerShell `Get-AuthenticodeSignature <file>`, which
should say `Valid`. The third-party files inside (Python, Qt, NumPy,
libiio, ADI's drivers) are not re-signed under our name: they keep
whatever signature their own publishers gave them, or none. Earlier
installers are unsigned.

What that changes, and what it does not:

- **SmartScreen** decides by reputation as well as by signature, and a
  publisher's reputation is earned by downloads over weeks. Until then it
  can still show "Windows protected your PC", now naming 360 Technology:
  choose **More info**, then **Run anyway**. It should stop appearing as
  the signed installers are downloaded and run.
- **Smart App Control** (Windows 11; Settings -> Privacy & security ->
  Windows Security -> App & browser control -> Smart App Control) lets a
  validly signed program run when its cloud service has no verdict, which
  is what blocked the unsigned installers outright. It judges every DLL a
  program loads, though, and some third-party libraries in the bundle are
  not signed by their publishers, so it may still refuse something; that
  has not yet been tried on a PC with it On. If it blocks OpenHamShack, it must
  be **Off** - and Windows only lets you turn it back on by resetting
  Windows, so decide that on a test machine, not on someone's daily PC
  without asking.
- **S mode** runs Store apps only; it cannot run this at all, signed or not.

How the signing is set up, where the credential lives and how to renew it:
`packaging/windows/sign.ps1`. `tools/release.sh --windows` refuses an
installer whose signature is missing, invalid, not 360 Technology's or not
timestamped.

## The Pluto on Windows

The program talks to the Pluto through libiio, as on Linux. Both pieces a
Pluto needs come with the installer; nothing has to be fetched from
Analog Devices first.

1. **libiio 0.26 is inside the program** (`_internal\libiio\`:
   `libiio.dll` and the three DLLs it is linked against, `libxml2.dll`,
   `libusb-1.0.dll` and `libserialport-0.dll`, unmodified from ADI's 0.26
   Windows release), beside ADI's pure-Python bindings. When the program
   imports the bindings it puts that folder first on PATH for the moment
   of the import (`ohscore.host.bundled_libiio()`), so the bundled 0.26 is
   used whatever else the machine has. That matters because of **libiio
   1.0** (September 2026): it changed the interface, the bindings speak
   0.26's, and ADI's 1.0 installer puts its `libiio.dll` in
   `C:\Windows\System32` - which is on PATH. A machine with ADI's libiio
   (either version) installed is fine; it is simply not used. ADI's libiio
   installer is no longer needed.
2. **The PlutoSDR USB drivers** are ADI's `PlutoSDR-M2k-USB-Drivers.exe`
   v0.9 (https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win),
   carried inside the installer and run by its ticked-by-default option
   **Install the PlutoSDR USB drivers**. They give the Pluto its USB
   network adapter (RNDIS), so it appears at **`ip:192.168.2.1`** exactly
   as on Linux, plus the WinUSB interface libiio's `usb:` URIs use. Install
   them **before** plugging the Pluto in.
   - Drivers are machine-wide, so this step alone asks for administrator
     permission (UAC); the rest of the install stays per user. Then
     **Windows asks "Would you like to install this device software?"**
     (publisher Analog Devices International UC) - answer **Install**.
     ADI's catalogs are signed with an ordinary code-signing certificate,
     not through Microsoft's hardware programme, so Windows asks unless
     ADI is already a trusted publisher there ("Always trust software from
     Analog Devices" stops it asking again).
   - The option is **not shown when the drivers are already installed**:
     the installer looks for `pluto-rndis.inf_*` and `pluto-usbd.inf_*` in
     `C:\Windows\System32\DriverStore\FileRepository`, which is what
     Windows matches a plugged-in Pluto against (ADI's uninstall entry is
     not trusted for this: it outlives drivers removed in Device Manager).
     The setup log (`/LOG=<file>`) says which way it went.
   - Afterwards it checks the driver store again and says so if the
     drivers did not arrive (UAC refused, or Windows' question answered
     Don't install). OpenHamShack itself is installed either way. ADI's own
     log is left as `plutosdr-drivers-setup.log` in the program's folder,
     and DPInst's in `C:\Windows\DPINST.LOG`.
   - The drivers appear under Settings -> Apps as
     *PlutoSDR-M2k-USB-Win-Drivers*, and stay when OpenHamShack is uninstalled -
     other Pluto software may use them.

   ADI's installer is run as `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART
   /dpinstflags="/F /SW /SE"`: its one step is DPInst, and `/SW` drops
   DPInst's wizard but leaves Windows' trust question. DPInst's fully
   quiet `/S` was tried and is wrong: it suppresses that question too, and
   every driver then fails with 0xE0000242 (publisher not trusted). For
   the same reason the drivers cannot install from a session with no
   desktop (an unattended install over SSH) unless ADI is already a
   trusted publisher.

Without `libad9361` (not needed, and not packaged for Windows here) the
program loads its own x4 FIR for rates below 2.083 MS/s through
`filter_fir_config` - the same fallback a Linux machine without
`libad9361-0` uses, and nothing in it is Linux-specific. Like the rest of
the Pluto path it is **not yet verified on hardware**.

Check the Pluto is visible before starting the program (PowerShell):

```
ping 192.168.2.1                  # the Pluto's own address over USB
```

then **Find** in Settings -> Radio lists every Pluto libiio can see. (The
bundle carries the library, not ADI's `iio_info`; with ADI's libiio
installer also run, `iio_info -s` and `iio_info -u ip:192.168.2.1` work as
on Linux.)

In the program: Settings -> Radio -> **Pluto**, URI `ip:192.168.2.1` (or
press **Find** and pick the full `usb:<bus>.<dev>.<intf>` entry it lists -
a bare `usb:` is refused by libiio 0.26 on Windows as a bad URI). With no
Pluto present, choosing it fails within about five seconds with a sentence
("No Pluto at ip:192.168.2.1. ... On Windows, a Pluto on USB needs ADI's
PlutoSDR drivers: run the installer again with "Install the PlutoSDR USB
drivers" ticked.") and the program keeps running. If the bundled libiio
cannot be loaded (a damaged install) it says to reinstall.

Checked on a Windows 11 VM with no radio (05/10/2026): with ADI's
libiio uninstalled and no `libiio.dll` anywhere on the machine, the
installed NB and HAM load libiio 0.26 (`a0eca0d`), and libxml2, libusb and
libserialport, all from `_internal\libiio`, and still do with a wrong
`libiio.dll` placed earlier on PATH; the driver option installs ADI's four
INFs into the driver store, and the next install of either app reports
them already installed and does not offer the option. Windows' trust
question could not be shown over SSH, so for that run ADI's certificate
was trusted beforehand (and removed after). **Not checked**: the
interactive prompt as a user sees it, and anything with a Pluto attached.

## Installing

Double-click `openhamshack-nb-<version>-setup.exe`. It installs for the current
user (no administrator prompt) into `%LOCALAPPDATA%\Programs\OpenHamShack QO-100 NB`,
with Start-menu entries **OpenHamShack QO-100 NB**, **OpenHamShack QO-100 NB (console)** (the
same program with a console window, for reading start-up errors) and an
uninstaller; the wizard offers "all users" / Program Files instead. The
only administrator prompt is the PlutoSDR USB drivers option's, above,
and only when the drivers are not yet installed.

Unattended:

```
openhamshack-nb-<version>-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER [/DIR="C:\somewhere"] [/MERGETASKS="!plutodrivers"]
"%LOCALAPPDATA%\Programs\OpenHamShack QO-100 NB\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

`/MERGETASKS="!plutodrivers"` skips the driver option, which would
otherwise raise a UAC prompt in the middle of an unattended install on a
machine without the drivers. (OpenHamShack Radio's installer takes the same
switches.)

Over an installed OpenHamShack NB (0.1.21 and earlier), the installer is an
upgrade, not a second program: Apps & features keeps one entry, now
called OpenHamShack QO-100 NB. A program in the old default folder,
`%LOCALAPPDATA%\Programs\OpenHamShack NB`, is moved to the new one and the old
folder removed; one installed somewhere chosen by hand stays there. The
old "OpenHamShack NB" Start-menu folder and its shortcuts go. The first start
then moves `%APPDATA%\openhamshack-nb` - settings, logbook, memories and
recordings - to `%APPDATA%\openhamshack-nb`, by renaming it. A shortcut
pinned to the taskbar pointed at the old program and has to be pinned
again.

`openhamshack-nb-console.exe --headless --seconds 10` runs the engine alone on
the configured device, as `python3 -m ohsnb --headless` does on Linux.

## Building it

On Windows 10/11 x64 with a checkout of the repository:

```
powershell -ExecutionPolicy Bypass -File tools\build-windows.ps1 [-Work C:\ohsnb-build] [-Ohsdigi <path>\ohsdigi.pyd] [-NoTests] [-NoSign]
```

It signs as it goes (see "Signed by 360 Technology" above), so it needs
the signing credential and the Artifact Signing account's name in the
build account's environment (`packaging/windows/sign.ps1` says which
variables) - on the Windows build machine they are there - and fails, before anything slow, without it. `-NoSign`
builds unsigned for a local test; such an installer cannot be released.

ohsdigi is not built on Windows: `tools/build-ohsdigi.sh windows-amd64` (or
`tools/release.sh`, from the release commit) cross-builds `ohsdigi.pyd` on
Linux. Copy it and the `SHA256SUMS` beside it to the build machine and
name it with `-Ohsdigi` (default `<Work>\ohsdigi\ohsdigi.pyd`); the build
checks the checksum and refuses to run without it, since an installer
without ohsdigi could not send FT4.

Everything goes under `-Work`: a private Python (python.org's NuGet zip,
unpacked, not installed), a virtualenv with `packaging/windows/requirements.txt`,
a download cache, PyInstaller's folders, Inno Setup in portable mode if it
is not already installed, and `out\openhamshack-nb-<version>-setup.exe` with its
`.sha256`. Nothing touches PATH or the registry, so it can run on a
working PC and be removed by deleting the folder. Every download that ends
up in the installer (FreeDV's codec2 DLLs, libiio 0.26 and its DLLs, ADI's
PlutoSDR driver installer, the licence texts, 7-Zip used to unpack
FreeDV's installer, Inno Setup, Python) is pinned by SHA-256 in the
script. The licences of everything carried are in
`packaging/windows/THIRD-PARTY.txt`, and their texts in the bundle's
`licences/`: the C libraries' fetched by the script, the Python
packages' taken from the wheels PyInstaller actually collected
(`packaging/windows/bundle_licences.py`). The two must agree both ways -
every text the file names is shipped, every shipped text is named - or
the freeze stops, so a new dependency cannot arrive without its entry.

It runs the test suite under the build's Python (the .deb and release.sh
suites skip themselves there; `tests/test_ohsdigi.py` runs the WSJT-X
corpus through the very `ohsdigi.pyd` being shipped), checks the bundled
libiio loads and is 0.26, checks `ohsdigi.pyd` loads and encodes FT4 as
WSJT-X's `ft4code` does, freezes the program, checks the frozen program's
start-up facts name ohsdigi from inside the bundle as its FT8/FT4 encoder, starts the frozen `openhamshack-nb-console.exe
--headless` on the simulator, then once more pointed at a Pluto on
`ip:127.0.0.1` (it must answer "No Pluto at", which only happens once
libiio.dll has loaded), then on the simulator's FT8 for 40 s with any
installed WSJT-X hidden (`SHACK_NO_WSJTX=1`; it must decode: ohsdigi
encodes the simulator's stations and decodes them), and only then makes
the installer. A build machine
with ADI's libiio installed cannot show a DLL missing from the bundle
(System32 would supply it); uninstall ADI's libiio to prove that, as was
done on the Windows test VM.

To publish it with a release: build from the "Release x.y.z" commit, copy
the `.exe` and its `.sha256` to the release host, and run
`tools/release.sh --windows <path>/openhamshack-nb-x.y.z-setup.exe`; the site's
Download card then offers it under the `.deb`.

# macOS (Apple Silicon)

The Mac build is `openhamshack-nb-<version>-arm64.dmg` (and
`openhamshack-radio-<version>-arm64.dmg`): a disk image holding **OpenHamShack QO-100 NB.app**
beside a link to Applications. Python 3.13, NumPy, PyQt6, PortAudio,
libiio 0.26 with libad9361, codec2 and ohsdigi are inside the app -
nothing else to install for the window, the simulator, sound, FT8 or a
Pluto on the network. It needs an Apple Silicon Mac (M1 or later) with
macOS 14 (Sonoma) or later. Everything in it is native arm64: no Rosetta
2. (Until 17/10/2026 it carried WSJT-X 2.7.0's Intel `jt9`, `ft8code` and
`q65code`, which needed Rosetta; in the notarised app `jt9` crashed on
every run, so ohsdigi was doing all the decoding anyway. A WSJT-X you put
in Applications is still used as the cross-check.) Built by `tools/build-macos.sh` on a Mac; `docs/macos.md` is the
builder's note. It is published on each site as a separate, unsigned
**preview** (`0.1.9+mac-preview.1` from 07/10/2026, built after 0.1.9),
under "macOS (preview)" in the Download card.

| Feature | macOS |
| --- | --- |
| Window, simulator, all DSP, beacon/TX lock | built in |
| Sound (PortAudio, Core Audio devices) | built in; the microphone needs the permission below |
| FreeDV | built in (`libcodec2.dylib`, codec2 1.2.0): 1600, 700C and 700D; not 2020 (no LPCNet in this build) |
| FT8 / FT4 / Q65 | built in: ohsdigi decodes and encodes, our own `cty.dat` for the Country column; no WSJT-X install needed |
| Pluto family over the network (ip:) | built in (libiio 0.26) |
| A Pluto on USB | as `ip:192.168.2.1`: macOS sees the Pluto's USB network interface with no driver. `usb:` URIs do not work (no libusb in this build) |
| SoapySDR receive-only SDRs | **Linux-only for now** |
| An IC-9700 by CI-V; HAM's serial PTT line | built in (pyserial; termios). A USB-serial adapter may need its maker's driver |

Settings live in `~/Library/Application Support/openhamshack-nb/`
(`config.json`, `ui.json`, and `data/` for recordings and SSTV pictures),
the log in `~/Library/Logs/openhamshack-nb/`; `OHS_NB_CONF` / `OHS_NB_DATA`
override them as on Linux (a `OHS_NB_DATA` folder then holds its own
`logs/`). OpenHamShack Radio uses `openhamshack-radio` in the same places. Deleting the
app leaves them.

## Installing an unsigned app

Open the `.dmg` and drag the app onto Applications. The build is not yet
signed with an Apple Developer ID or notarised, so the first start is
refused - "Apple could not verify "OpenHamShack QO-100 NB" is free of malware" - and
macOS has to be told once that you trust it:

- **macOS 15 (Sequoia), 26 and later:** try to open the app once and
  choose **Done**; then open **System Settings › Privacy & Security**,
  scroll to *"OpenHamShack QO-100 NB" was blocked to protect your Mac* and click
  **Open Anyway**, then **Open Anyway** again in the question that
  follows, with your password. From then on it opens normally.
- **macOS 14:** right-click (or Control-click) the app in
  Applications, choose **Open**, then **Open** in the question.

(For a build copied to the Mac some other way than a browser - AirDrop
aside, `scp` or a USB stick - macOS asks nothing, as no quarantine flag
was set.)

## The microphone

The program opens the microphone only when it needs it: the first time
you transmit voice from the microphone, record a voice memory, or press
**Listen to the microphone** in Settings › Audio. That first time macOS
asks **"OpenHamShack QO-100 NB" would like to access the microphone** (or
"OpenHamShack Radio"); the radio keys only after you answer. Starting the
program and listening never ask. Allow it, or transmit audio is silence: macOS gives a
program it has not allowed a stream of zeros, with no error. Changed
later in **System Settings › Privacy & Security › Microphone**. While the
app is unsigned, its permission is tied to that exact build, so a new
version asks again.

## Local network access

The first time the program opens a connection to an address on your LAN -
a Pluto, LibreSDR or (OpenHamShack Radio) Hermes-Lite 2 - macOS asks **"OpenHamShack
QO-100 NB" would like to find and connect to devices on your local network**.
Allow it, or the radio is unreachable with no prompt and no clear error:
libiio's connect fails silently, and what reaches the program is "No
route to host" or "Operation not permitted" with nothing macOS-specific
in it (found live, 07/10/2026, with a LibreSDR that answered ping and a
direct connection from Terminal). From mac-preview.2 the error names the
likely cause when it sees that pattern. Changed later in **System
Settings › Privacy & Security › Local Network**.

## A Pluto or LibreSDR

Over the network as on any system: Settings › Radio, `ip:<address>`
(`ip:pluto.local` once the Pluto's name resolves; a LibreSDR or Pluto+
has its own address), or **Find**, which looks on the network and
through Bonjour. A Pluto on USB appears to macOS as a network interface
(System Settings › Network shows it) at `ip:192.168.2.1`, as on Linux.

## Upgrading from the app's earlier bundle name

The app was **OpenHamShack NB.app** until 17/10/2026, with a different
bundle id. The new one has a different name, so dragging it to
Applications puts it beside the old one rather than over it: start the
new one, then move **OpenHamShack NB.app** to the Bin. Settings, the
logbook and recordings stay in `~/Library/Application Support/openhamshack-nb`
and `~/Library/Logs/openhamshack-nb`, which the new app uses too - the
folder name did not change, only the bundle around it - so nothing needs
copying across. macOS asks for the microphone once more: the bundle's id
changed with its name.

## Updates

Help › Check for updates…, and the daily check, offer a newer .dmg from
the same signed feed as the other systems (`docs/update-feed.md`): it is
downloaded, checked against the signed manifest's size and SHA-256, and
opened in Finder. Quit the program, drag the new app onto Applications
(replace the old one) and start it again. It does not replace itself
while the build is unsigned; `docs/macos.md` says why.

## Building it

On an Apple Silicon Mac with Apple's Command Line Tools
(`xcode-select --install`), from a checkout:

```
/bin/bash tools/build-macos.sh [--app nb|ham|all] [--work ~/openhamshack-mac] [--no-tests]
```

No Homebrew and no administrator: everything it downloads or builds goes
under `--work`, and `out/` there gets each `.dmg` and its `.sha256`.
`docs/macos.md` lists what it builds, what it takes from where, and what
it checks before making the image.
