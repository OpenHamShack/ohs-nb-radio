"""Every test runs against a throw-away home, never the operator's.

Importing this module points both apps' config and data variables
($OHS_NB_CONF, $OHS_NB_DATA, $OHS_NB_UI_CONF, the $OHS_RADIO_ ones, and
the $OHSNB_ and $OHSRADIO_ ones they were called before the rename), and the
folders ohscore.host falls back to when they are unset (HOME, which
~/.config and ~/.local/share hang off on Linux; APPDATA on Windows), at a
temporary folder removed when the run ends. Child processes the tests
start inherit the environment, so a headless run or an installed .deb's
launcher is caught as well as an in-process Radio.

Before this existed the suite relied on whoever ran it exporting the four
variables by hand; on 04/10 nobody had, and the simulator's beacon-lock
corrections were saved into the development machine's real ~/.config/openhamshack-nb. Setting
them per test was not enough either: a test that forgets is silent, and
the damage only shows when the real radio next starts from a nonsense
correction.

Why a module every test file imports first rather than tests/__init__.py:
`python3 -m unittest discover -s tests` (the command release.sh and the
Windows build run) makes tests/ the top-level directory, so its test files
are imported as top-level modules and an __init__.py there is never
executed. An import is the one thing that runs first however a test is
started - discovery, `python3 -m unittest test_lock`, or a file run
directly. test_scratch_home.py imports each test file alone in a fresh
interpreter and fails for any that forgot.

Values are overwritten, not defaulted: an operator who exports $OHSNB_CONF
for their own use must not have the suite write into it.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

WINDOWS = sys.platform == "win32"

# Each app's folder name and variable prefix, now and before the
# OpenHamShack rename (17/10/2026). The apps still read the old variable
# prefix (ohscore/config.py AppId.former_env), so both are scratched: a
# test that set only the new variables would leave an inherited $OHSNB_CONF
# live.
APPS = {"openhamshack-nb": ("OHS_NB", "OHSNB"), "openhamshack-radio": ("OHS_RADIO", "OHSRADIO")}

# The home the operator really has, remembered across nested runs: a test
# that starts another Python which imports this module again must still
# know which folders are the real ones, not mistake the scratch home for it.
os.environ.setdefault("OHSTEST_REAL_HOME", str(Path.home()))
if WINDOWS:
    os.environ.setdefault("OHSTEST_REAL_APPDATA", os.environ.get("APPDATA", ""))


def real_dirs() -> list[Path]:
    """The folders the apps would use on this machine with nothing set:
    the ones no test may ever write to."""
    out = []
    for app in APPS:
        if WINDOWS:
            base = Path(os.environ["OHSTEST_REAL_APPDATA"] or Path(os.environ["OHSTEST_REAL_HOME"]) / "AppData" / "Roaming")
            out.append(base / app)
        elif sys.platform == "darwin":
            # ohscore.host's macOS folders: config and data under Application
            # Support, logs under ~/Library/Logs. All hang off HOME, which is
            # moved below, as on Linux.
            home = Path(os.environ["OHSTEST_REAL_HOME"]) / "Library"
            out += [home / "Application Support" / app, home / "Logs" / app]
        else:
            home = Path(os.environ["OHSTEST_REAL_HOME"])
            out += [home / ".config" / app, home / ".local" / "share" / app]
    return out


ROOT = Path(tempfile.mkdtemp(prefix="ohstest-home-"))
atexit.register(shutil.rmtree, ROOT, True)

# HOME (Linux, macOS) and APPDATA (Windows) are what ohscore.host builds the
# default folders from, so a path the app variables do not cover - a new
# file kept beside config.json, or a third app - still lands in scratch.
# Only the platform's own one is moved: on Windows git and Qt read HOME
# when it is set, and nothing there needs it. host.py does not read
# XDG_CONFIG_HOME or XDG_DATA_HOME, so there is no XDG variable to move;
# if it ever starts to, they belong here too.
if WINDOWS:
    os.environ["APPDATA"] = str(ROOT / "AppData" / "Roaming")
else:
    os.environ["HOME"] = str(ROOT)
for app, envs in APPS.items():
    for env in envs:
        os.environ[f"{env}_CONF"] = str(ROOT / app / "config.json")
        os.environ[f"{env}_UI_CONF"] = str(ROOT / app / "ui.json")
        os.environ[f"{env}_DATA"] = str(ROOT / app / "data")

# The station's shared logbook and profile (ohscore/station.py, ohs-libs
# shack_client): one store per user per machine, at
# $XDG_DATA_HOME/openhamshack (Linux), %LOCALAPPDATA%\OpenHamShack
# (Windows) or under ~/Library (macOS, covered by HOME). An engine given
# its own data folder keeps its store there, but a window or a tool that
# opens the default store must find the scratch one, never the
# operator's real log - and SHACK_STATION_DB, if the operator exported
# it, must not leak in either.
os.environ["XDG_DATA_HOME"] = str(ROOT / ".local" / "share")
os.environ["LOCALAPPDATA"] = str(ROOT / "AppData" / "Local")
os.environ.pop("SHACK_STATION_DB", None)
os.environ["XDG_CACHE_HOME"] = str(ROOT / ".cache")

# The shared source site (tools/source-site.py, which release.sh --windows
# runs) is /srv/source-site on the release host, and the operator can write to it: a
# release test that forgot to point it elsewhere would publish its stand-in
# tarballs onto the real site, to be uploaded with it. Its public address
# is pointed nowhere, so a --live check that a test forgot to aim fails
# rather than asking the real site.
os.environ["SOURCE_SITE"] = str(ROOT / "source-site")
os.environ["SOURCE_SITE_ARCHIVE"] = str(ROOT / "source-site-archive")
os.environ["SOURCE_SITE_URL"] = "http://source-site.invalid/"

# PSKReporter (ohscore/pskreporter.py): a test that turns spotting on and
# forgets to give the spotter its own socket must not report simulated
# stations to the real server as heard. The discard port on this machine
# takes them; the tests that check the packets bind their own.
os.environ["OHS_PSKREPORTER"] = os.environ["OPENHAMSHACK_PSKREPORTER"] = "127.0.0.1:9"
