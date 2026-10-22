"""What differs between the systems OpenHamShack runs on, kept in one place.

The program was written on Debian and still assumes a Linux desktop in the
places that touch the outside world: where config lives, where an optional
shared library or helper program is found, and which sentence tells the
operator what to install. Windows (a PyInstaller build, see
packaging/windows/) differs in exactly those places and nowhere in the
radio, so every such difference is answered here rather than as an
`if sys.platform` scattered through the engine. On Linux each function
returns precisely what the code did before this module existed - the .deb
must not notice it.

macOS (an unsigned .app from PyInstaller: packaging/macos/, docs/macos.md)
joined on 07/10/2026 and differs in the same places, with its own
answers: Apple's folders under ~/Library, .dylib libraries, WSJT-X as an
.app in /Applications, and nothing to say about apt. Whatever a Mac shares
with Linux - POSIX serial lines, no console windows - keeps the Linux
answer. WINDOWS and MACOS are never both true; Linux is "neither", which
is why the tests that pin Linux's answers patch both.
"""
from __future__ import annotations

import contextlib
import ctypes.util
import ipaddress
import os
import shutil
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
# The store form: the app's container image on an OpenHamShack controller,
# whose Containerfile sets SHACK_FORM=store. Nothing can be installed into
# that image by the operator, so a "sudo apt install" sentence is wrong
# there; hint() says what the image does and does not carry instead.
STORE = os.environ.get("SHACK_FORM") == "store"

# Where the WSJT-X installer puts jt9 and friends: C:\WSJT\wsjtx is its
# default, Program Files is where people put it when they change that. WSJT-X
# does not add itself to PATH, so without these FT8 would look uninstalled on
# every Windows machine that has it.
WSJTX_DIRS = (r"C:\WSJT\wsjtx\bin",
              r"%ProgramFiles%\wsjtx\bin", r"%ProgramFiles%\WSJT-X\bin",
              r"%ProgramFiles(x86)%\wsjtx\bin", r"%ProgramFiles(x86)%\WSJT-X\bin")
# WSJT-X for macOS is an .app whose tools (jt9, ft8code, q65code) sit in
# Contents/MacOS and are never on PATH either: /Applications is where its
# .dmg asks to be dragged, ~/Applications where an account without admin
# rights puts it.
MAC_WSJTX_APPS = ("/Applications/wsjtx.app", "~/Applications/wsjtx.app")


def bundle_dir() -> Path | None:
    """The folder a frozen build runs from (PyInstaller's sys._MEIPASS, which
    for a onedir build is the _internal folder beside the .exe, and in a
    macOS .app is Contents/Frameworks), or None when running from source or
    from the .deb."""
    if not getattr(sys, "frozen", False):
        return None
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(sys.executable).resolve().parent


def _bundle_dirs() -> list[Path]:
    """Every folder a bundled file may sit in: the unpack folder and the
    folder holding the .exe (the same folder in PyInstaller 5, different
    from 6 on), so a DLL dropped beside the .exe by hand is found too."""
    b = bundle_dir()
    if b is None:
        return []
    out = [b]
    exe = Path(sys.executable).resolve().parent
    if exe != b:
        out.append(exe)
    return out


def _appdata() -> Path:
    env = os.environ.get("APPDATA")
    return Path(env) if env else Path.home() / "AppData" / "Roaming"


def _mac_support() -> Path:
    return Path.home() / "Library" / "Application Support"


def conf_dir(app: str) -> Path:
    """Where app `app` (e.g. "openhamshack-nb") keeps config.json and ui.json
    when its $<ENV>_CONF does not say. On macOS, Application Support: the
    folder Apple gives a program's own files, and the one a Mac user (and
    Time Machine) expects them in; ~/.config means nothing to Finder."""
    if WINDOWS:
        return _appdata() / app
    if MACOS:
        return _mac_support() / app
    return Path.home() / ".config" / app


def data_dir(app: str) -> Path:
    """Log, recordings and SSTV pictures when $<ENV>_DATA does not say. On
    Windows a "data" folder under the config folder rather than the folder
    itself, so the operator who opens %APPDATA%\\openhamshack-nb to find
    their log does not have to pick it out from between config files. macOS
    the same, under Application Support, for the same reason."""
    if WINDOWS or MACOS:
        return conf_dir(app) / "data"
    return Path.home() / ".local" / "share" / app


def mac_logs_dir(app: str) -> Path:
    """~/Library/Logs/<app>."""
    return Path.home() / "Library" / "Logs" / app


def log_dir(app: str, data: Path) -> Path:
    """The program's own log files (ohscore/diag.py): a "logs" folder in the
    data folder - except on a Mac using its default data folder, where it
    is ~/Library/Logs/<app>, because that is where Console.app looks and
    where a Mac user asked for "the log" goes. A data folder named by
    $<ENV>_DATA keeps its logs inside it on every system, so a test run or
    a second installation never writes into the operator's real logs."""
    data = Path(data)
    if MACOS and data == data_dir(app):
        return mac_logs_dir(app)
    return data / "logs"


# Where a Mac's package managers put libraries: Homebrew on Apple Silicon,
# Homebrew on Intel, MacPorts. ctypes.util.find_library on macOS asks only
# dyld's fallback folders, which have /usr/local/lib but not the other two,
# so a run from source with `brew install codec2` would never find it.
MAC_LIB_DIRS = ("/opt/homebrew/lib", "/usr/local/lib", "/opt/local/lib")


def find_library(name: str) -> str | None:
    """A shared library for ctypes: a copy shipped inside a frozen build
    first (the Windows build carries libcodec2.dll, the Mac build
    libcodec2.dylib), then the system's own search. On Windows
    ctypes.util.find_library only looks for <name>.dll on PATH, but the
    MinGW-built libraries everybody ships are lib<name>.dll, so both
    spellings are tried. On macOS a library is always lib<name>.dylib, and
    the package managers' folders (MAC_LIB_DIRS) are tried last."""
    if MACOS:
        names, exts = [f"lib{name}"], (".dylib", ".so")
    else:
        names, exts = ([name, f"lib{name}"] if WINDOWS else [name]), (".dll", ".so")
    for d in _bundle_dirs():
        for n in names:
            for ext in exts:
                cand = d / f"{n}{ext}"
                if cand.is_file():
                    return str(cand)
    for n in ([name] if MACOS else names):
        found = ctypes.util.find_library(n)
        if found:
            return found
    if MACOS:
        for d in MAC_LIB_DIRS:
            cand = Path(d) / f"lib{name}.dylib"
            if cand.is_file():
                return str(cand)
    return None


# The subfolder of a Windows bundle holding libiio 0.26 and the DLLs it
# links against (libxml2, libusb-1.0, libserialport), unmodified from ADI's
# 0.26 Windows release - see packaging/windows/openhamshack-nb.spec. The Mac
# build's folder of the same name holds libiio 0.26 and libad9361, built
# from source by tools/build-macos.sh (libxml2 is the system's own there).
LIBIIO_SUBDIR = "libiio"


def _libiio_file() -> str:
    # The file ADI's iio.py asks the system for: "libiio.dll" on Windows,
    # find_library("iio") elsewhere, which on macOS means libiio.dylib.
    return "libiio.dylib" if MACOS else "libiio.dll"


def libiio_dir() -> Path | None:
    """The folder holding the libiio a Windows or Mac build carries, or None
    (Linux, not frozen, or the bundle lacks it)."""
    if not (WINDOWS or MACOS):
        return None
    for d in _bundle_dirs():
        cand = d / LIBIIO_SUBDIR
        if (cand / _libiio_file()).is_file():
            return cand
    return None


def _library_search_var() -> str:
    """The variable ctypes.util.find_library reads first: PATH on Windows
    (it is a walk along PATH there), DYLD_LIBRARY_PATH on macOS (its dyld
    emulation, ctypes.macholib.dyld, consults it before anything else)."""
    return "DYLD_LIBRARY_PATH" if MACOS else "PATH"


@contextlib.contextmanager
def bundled_libiio():
    """Make `import iio` inside the with-block load the bundled libiio.dll.

    ADI's iio.py finds its DLL with ctypes.util.find_library("libiio.dll"),
    which on Windows is nothing but a walk along PATH - and PATH has
    System32 on it, where ADI's own installers put libiio.dll. Their 1.0
    installer puts a 1.0 DLL there, which these 0.2x bindings cannot use;
    so the bundled folder goes in front of PATH for the length of the
    import, and the bundle's 0.26 is the one found whatever else the
    machine has. ctypes then loads it by full path, and Windows resolves
    its imports (libxml2.dll, libusb-1.0.dll...) from the folder it was
    loaded from first, so the whole set comes from the bundle too.

    PATH is put back afterwards: the DLL is loaded once, at import, and
    leaving the folder on PATH would hand our libusb and libxml2 to every
    child process (jt9, rigctld) as well. Patching iio.py instead was
    rejected: it is ADI's file, shipped unmodified, and a copy we had
    edited would be ours to keep in step with every libiio we pin.

    On macOS the same, with DYLD_LIBRARY_PATH: iio.py's find_library("iio")
    searches that variable first, then dyld's fallback folders, where a
    libiio 1.0 from Homebrew or ADI's .pkg may sit. Set inside the running
    process it changes only what Python's own search finds - dyld read its
    copy at start-up - which is exactly the part wanted: iio.py then loads
    the bundle's libiio.dylib by its full path, and that needs nothing
    beyond the system's own libraries.

    Yields the folder, or None when there is no bundled copy (Linux, a run
    from source, a damaged install) - then nothing changes and the system's
    libiio is used, as before."""
    d = libiio_dir()
    if d is None:
        yield None
        return
    var = _library_search_var()
    old = os.environ.get(var)
    os.environ[var] = str(d) + (os.pathsep + old if old else "")
    try:
        yield d
    finally:
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old


# No build carries WSJT-X any more (Brian, 17/10/2026). From NB/HAM 0.1.4
# to 0.1.21 the Windows and Mac builds had its jt9, ft8code (and on the Mac
# q65code) in a "wsjtx" folder, looked in first. ohsdigi, our port of WSJT-X
# 2.7.0's decoders and encoders, has decoded and encoded every slot mode
# since 10/10, so those copies were only the fallback and the shadow - and
# on the Mac they were Intel programs under Rosetta 2, which Apple is
# retiring, and they did not even run once the app was notarised (the
# hardened runtime refuses gfortran's executable stack; see
# ohscore/modes/ft8.py run_decoder_tool). A bundle's own "wsjtx" folder is
# therefore not looked in, even if an old install left one behind: only a
# WSJT-X the operator installed is used.


def find_tool(name: str) -> str | None:
    """A WSJT-X program (jt9, ft8code...) the operator installed, or None:
    PATH, then on Windows and macOS the places WSJT-X installs to, since it
    never adds itself to PATH. Linux: PATH only, as it always was. None is
    the normal case now - ohsdigi decodes and encodes; an installed WSJT-X
    only adds jt9 as the fallback and the shadow.

    SHACK_NO_WSJTX=1 makes it find nothing: the macOS and Windows builds'
    test suite and smoke tests set it so they check what ships (ohsdigi
    alone), not whichever WSJT-X the build machine has - the Mac mini has
    WSJT-X 3.0.2, which does not read one of ohsdigi's 2.7.0 messages back."""
    if os.environ.get("SHACK_NO_WSJTX") == "1":
        return None
    exe = ".exe" if WINDOWS else ""
    found = shutil.which(name)
    if found or not (WINDOWS or MACOS):
        return found
    if WINDOWS:
        dirs = [Path(os.path.expandvars(d)) for d in WSJTX_DIRS]
    else:
        dirs = [Path(a).expanduser() / "Contents" / "MacOS" for a in MAC_WSJTX_APPS]
    for d in dirs:
        cand = d / f"{name}{exe}"
        if cand.is_file():
            return str(cand)
    return None


def wsjtx_cty_files() -> list[Path]:
    """Where an installed WSJT-X's cty.dat may be on this system, for
    ohscore/dxcc.py, which puts the operator's own and ohscore's bundled copy
    in front. The Windows and macOS builds carried WSJT-X 2.7.0's copy in
    their wsjtx folder until 0.1.10; they now carry ours in ohscore/data, as
    the .deb does, and a copy an older installer left behind is not looked
    for."""
    if WINDOWS:
        return [Path(os.path.expandvars(d)).parent / "share" / "wsjtx" / "cty.dat" for d in WSJTX_DIRS]
    if MACOS:
        # Inside WSJT-X's .app, where its own program reads it.
        return [Path(a).expanduser() / "Contents" / "Resources" / "wsjtx" / "cty.dat" for a in MAC_WSJTX_APPS]
    return [Path("/usr/share/wsjtx/cty.dat"), Path("/usr/share/hamradio-files/cty.dat"),
            Path("/usr/local/share/wsjtx/cty.dat")]


# What PortAudio's ALSA host API calls the sound server's own device on a
# Linux desktop: the default it reports is one of these, which names the
# route ("through PipeWire") and not the speaker or microphone at its end.
SOUND_SERVER_ALIASES = ("default", "pulse", "pipewire", "sysdefault")


def _pactl_description(listing: str, name: str) -> str | None:
    """The Description: of the sink or source called `name` in `pactl list
    sinks|sources` output (read in the C locale, so the field names are
    English), or None."""
    current = None
    for line in listing.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            current = s[5:].strip()
        elif s.startswith("Description:") and current == name:
            return s[12:].strip() or None
    return None


def sound_server_default(output: bool) -> str | None:
    """The real device behind the sound server's default, by its own
    description ("Tiger Lake-LP ... Speaker", "USB Audio CODEC Analog
    Stereo"), when PortAudio could only say "default" or "pulse". Linux
    only, through pactl, which PulseAudio and PipeWire (pipewire-pulse)
    both answer; None when there is no pactl, no server, or no answer
    within a couple of seconds - the caller then shows PortAudio's own
    word rather than a guess. Windows and macOS name their defaults
    themselves (see audio.default_devices)."""
    if WINDOWS or MACOS:
        return None
    pactl = shutil.which("pactl")
    if not pactl:
        return None
    import subprocess
    env = dict(os.environ, LC_ALL="C")
    kind = "sink" if output else "source"
    try:
        # `pactl info`, not `get-default-sink`: that arrived in PulseAudio
        # 15, and Pi OS and older Debian still ship pactl without it.
        info = subprocess.run([pactl, "info"], capture_output=True, text=True, timeout=2, env=env,
                              check=True).stdout
        field = f"Default {kind.title()}:"
        name = next((s.strip()[len(field):].strip() for s in info.splitlines() if s.strip().startswith(field)), "")
        if not name:
            return None
        listing = subprocess.run([pactl, "list", f"{kind}s"], capture_output=True, text=True, timeout=2,
                                 env=env, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return _pactl_description(listing, name) or name


def no_console() -> dict:
    """subprocess keyword arguments that stop a console window flashing up
    over the radio for every jt9 run: the Windows build is a GUI program,
    so each console child would otherwise get a window of its own, four
    times a minute in FT8. Nothing on Linux."""
    if WINDOWS:
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}


# One sentence per optional piece, in the vocabulary of the system it is
# read on: an apt command means nothing on Windows or a Mac. The Windows installer
# carries libiio 0.26 itself, so reaching this sentence there means the
# bundled copy is missing or damaged, or the program is being run from
# source; "install libiio" alone would not do for the latter, because the
# 1.0 series ADI now offers first speaks a different interface from the
# 0.2x one these bindings expect.
#
# Each entry is (Linux, Windows, macOS). The Mac app carries libiio, ohsdigi
# and pyserial as the Windows installer does, so its sentences say the same in
# a Mac's words: the .app is replaced by dragging it out of its .dmg again.
_HINTS = {
    "libiio": ("The Pluto needs libiio: sudo apt install python3-libiio",
               "The Pluto needs libiio 0.26, which the Windows installer carries: reinstall the program "
               "(running from source, install ADI's libiio 0.26, not 1.0); see docs/INSTALL.md",
               "The Pluto needs libiio 0.26, which the Mac app carries: copy the app from its .dmg again "
               "(running from source, build libiio 0.26 - not 1.0 - as tools/build-macos.sh does); "
               "see docs/INSTALL.md"),
    "soapysdr": ("Receive-only SDRs need SoapySDR: sudo apt install python3-soapysdr "
                 "and the module for your radio (e.g. soapysdr-module-rtlsdr)",
                 "Receive-only SDRs through SoapySDR are Linux-only for now; the Windows build "
                 "supports the simulator and the Pluto family",
                 "Receive-only SDRs through SoapySDR are Linux-only for now; the Mac build "
                 "supports the simulator and the Pluto family"),
    # Said only where FT8/FT4 cannot be received at all: ohsdigi did not
    # load and no WSJT-X is installed. The Windows and Mac builds carry
    # ohsdigi (and, since 17/10/2026, never WSJT-X), so there it means a
    # damaged install or a run from source.
    "wsjtx": ("ohsdigi, OpenHamShack's FT8, FT4 and Q65 decoder, did not load: reinstall the package "
              "(running from source, tools/build-ohsdigi.sh --host --install), or install wsjtx for its jt9",
              "ohsdigi, OpenHamShack's FT8, FT4 and Q65 decoder, did not load, though the Windows installer carries "
              "it: reinstall the program (running from source, build ohsdigi, or install WSJT-X for its jt9)",
              "ohsdigi, OpenHamShack's FT8, FT4 and Q65 decoder, did not load, though the Mac app carries it: copy "
              "the app from its .dmg again (running from source, build ohsdigi, or put WSJT-X in Applications "
              "for its jt9)"),
    "pyserial": ("A CI-V link needs pyserial: sudo apt install python3-serial",
                 "A CI-V link needs pyserial, which this installation is missing; reinstall OpenHamShack QO-100 NB",
                 "A CI-V link needs pyserial, which this installation is missing; copy OpenHamShack QO-100 NB from "
                 "its .dmg again"),
    # JS8 decodes with ohsdigi everywhere (ohscore/modes/js8.py); js8call's
    # js8 is only the fallback, so this follows the sentence about ohsdigi
    # not loading. The Windows and Mac builds carry ohsdigi, never js8.
    "js8": ("Without it, JS8 can decode with JS8Call's js8: sudo apt install js8call",
            "Reinstall the program: its installer carries ohsdigi",
            "Copy the app from its .dmg again: it carries ohsdigi"),
}


# The store form's own sentences, for programs its image deliberately does
# not carry (store/<app>/Containerfile says why), each naming the mode it
# costs. None at present: since 10/10/2026 ohsdigi decodes every slot mode
# there (FT8, FT4, Q65, JS8), and each says itself when ohsdigi is missing.
_STORE_HINTS: dict[str, str] = {}


def hint(what: str) -> str:
    if STORE and what in _STORE_HINTS:
        return _STORE_HINTS[what]
    linux, windows, macos = _HINTS[what]
    return windows if WINDOWS else macos if MACOS else linux


def local_network_hint(errno: int, addr: str) -> str:
    """A clause to append to a radio connection failure, naming macOS's
    Local Network privacy (macOS 15 and later) as the likely cause - found
    07/10/2026 on Brian's Mac: a LibreSDR at a 192.168.x address gave "No
    route to host" (errno 65) although ping and the TCP port both worked
    from Terminal, because the app's Info.plist had no
    NSLocalNetworkUsageDescription (packaging/macos/openhamshack-nb.spec now
    carries one) and macOS silently refused the socket rather than asking.
    EPERM (1) is the other errno seen for the same refusal.

    Empty on any other system, for any other errno, or for an address that
    is not on a private network: a timeout or refusal reaching the public
    internet is never this. Loopback is excluded too - it never crosses
    the boundary Local Network privacy guards, so the hint would be
    pointing at the wrong setting."""
    if not MACOS or errno not in (1, 65):
        return ""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return ""
    if not ip.is_private or ip.is_loopback:
        return ""
    return (" macOS may be blocking local network access: System Settings › Privacy & Security › "
            "Local Network › allow this program.")


def system_name() -> str:
    """"windows", "macos" or "linux": the names the update feed gives the
    three (ohscore/update.py, docs/update-feed.md)."""
    return "windows" if WINDOWS else "macos" if MACOS else "linux"


# Characters no Windows file name may hold, and the device names it
# reserves whatever the extension. A recording made on Linux is sent to
# someone who may open it on Windows (and the other way round), so a name
# the program makes is held to Windows' rules on both.
_BAD_NAME_CHARS = set('<>:"/\\|?*') | {chr(i) for i in range(32)}
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str) -> str:
    """`name` made into a file name every system accepts: Windows' reserved
    characters become "-", trailing dots and spaces (which Windows drops
    silently, so the file is not where the program thinks) are removed,
    and a reserved device name gets a "_" in front."""
    out = "".join("-" if ch in _BAD_NAME_CHARS else ch for ch in name).rstrip(". ")
    if out.split(".", 1)[0].upper() in _RESERVED_NAMES:
        out = "_" + out
    return out or "_"


def recordings_dir(data_dir: Path) -> Path:
    """Where IQ recordings go: a "recordings" folder in the app's data
    folder - ~/.local/share/<app>/recordings on Linux,
    %APPDATA%\\<app>\\data\\recordings on Windows, and
    ~/Library/Application Support/<app>/data/recordings on macOS
    (data_dir above)."""
    return Path(data_dir) / "recordings"


def keyer_dir(data_dir: Path) -> Path:
    """The voice keyer's recordings (ohscore/keyer.py): a "keyer" folder in
    the app's data folder, beside "recordings" - kept apart from the IQ
    recordings, which are gigabytes and get cleared out; these are the
    operator's own voice and are meant to stay."""
    return Path(data_dir) / "keyer"


def free_bytes(path: Path) -> int | None:
    """Free space on the disk that holds `path`, or the nearest folder above
    it that exists (a recordings folder not made yet); None if unknown."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None
