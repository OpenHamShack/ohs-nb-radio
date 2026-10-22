"""ohscore.host: where Linux, Windows and macOS differ - config folders,
bundled libraries, WSJT-X's install folders, the libiio import, the
sound-device list. The other systems are simulated (host.WINDOWS and
host.MACOS patched through systems.system(), a frozen bundle faked with
sys.frozen/sys._MEIPASS and a scratch folder), so these run on any of the
three; the Windows and Mac builds themselves are checked by
tools/build-windows.ps1 and tools/build-macos.sh on those machines. Each
test also pins the Linux answer, which must stay what it was before the
Windows build existed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ohsnb import config
from ohscore import host
from systems import system

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class Frozen:
    """A fake PyInstaller bundle at `path` for the duration of a with-block."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.patches = [mock.patch.object(sys, "frozen", True, create=True),
                        mock.patch.object(sys, "_MEIPASS", str(self.path), create=True)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class Folders(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        for k in ("OHS_NB_CONF", "OHS_NB_DATA", "OHSNB_CONF", "OHSNB_DATA"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_linux_keeps_the_xdg_style_folders(self):
        with system("linux"):
            self.assertEqual(config.conf_path(), Path.home() / ".config" / "openhamshack-nb" / "config.json")
            self.assertEqual(config.data_dir(), Path.home() / ".local" / "share" / "openhamshack-nb")

    def test_windows_uses_appdata(self):
        os.environ["APPDATA"] = "/x/AppData/Roaming"
        with system("windows"):
            self.assertEqual(config.conf_path(), Path("/x/AppData/Roaming/openhamshack-nb/config.json"))
            self.assertEqual(config.data_dir(), Path("/x/AppData/Roaming/openhamshack-nb/data"))

    def test_macos_uses_application_support(self):
        support = Path.home() / "Library" / "Application Support" / "openhamshack-nb"
        with system("macos"):
            self.assertEqual(config.conf_path(), support / "config.json")
            self.assertEqual(config.data_dir(), support / "data")
            self.assertEqual(host.recordings_dir(config.data_dir()), support / "data" / "recordings")

    def test_logs_go_where_each_system_keeps_them(self):
        # A Mac's own logs folder for the default data folder; a data folder
        # given by $OHS_NB_DATA (the tests', a second installation's) keeps
        # its logs inside it everywhere, as Linux and Windows always do.
        from ohscore import diag
        with system("macos"):
            self.assertEqual(diag.log_dir(config.data_dir(), "openhamshack-nb"),
                             Path.home() / "Library" / "Logs" / "openhamshack-nb")
            self.assertEqual(diag.log_dir(Path("/elsewhere/data"), "openhamshack-nb"), Path("/elsewhere/data/logs"))
        for name in ("linux", "windows"):
            with system(name):
                self.assertEqual(diag.log_dir(config.data_dir(), "openhamshack-nb"), config.data_dir() / "logs")

    def test_environment_overrides_win_on_both(self):
        os.environ["OHS_NB_CONF"] = "/elsewhere/c.json"
        os.environ["OHS_NB_DATA"] = "/elsewhere/data"
        for win in (False, True):
            with system("windows" if win else "linux"):
                self.assertEqual(config.conf_path(), Path("/elsewhere/c.json"))
                self.assertEqual(config.data_dir(), Path("/elsewhere/data"))


class Libraries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_frozen_means_no_bundle(self):
        self.assertIsNone(host.bundle_dir())

    def test_a_dll_shipped_in_the_bundle_wins_under_its_lib_name(self):
        (self.dir / "libcodec2.dll").write_bytes(b"MZ")
        with Frozen(self.dir), system("windows"), \
                mock.patch("ctypes.util.find_library", return_value=None):
            self.assertEqual(host.find_library("codec2"), str(self.dir / "libcodec2.dll"))
            self.assertIsNone(host.find_library("ad9361"))

    def test_windows_tries_the_lib_prefixed_name_on_the_system_too(self):
        seen = []

        def fake(name):
            seen.append(name)
            return r"C:\Windows\System32\libad9361.dll" if name == "libad9361" else None
        with system("windows"), mock.patch("ctypes.util.find_library", fake):
            self.assertEqual(host.find_library("ad9361"), r"C:\Windows\System32\libad9361.dll")
        self.assertEqual(seen, ["ad9361", "libad9361"])

    def test_linux_asks_the_system_exactly_once_by_the_plain_name(self):
        seen = []
        with system("linux"), \
                mock.patch("ctypes.util.find_library", lambda n: seen.append(n) or "libcodec2.so.1.2"):
            self.assertEqual(host.find_library("codec2"), "libcodec2.so.1.2")
        self.assertEqual(seen, ["codec2"])

    def test_a_mac_bundle_carries_dylibs_under_their_lib_name(self):
        (self.dir / "libcodec2.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
        with Frozen(self.dir), system("macos"), mock.patch("ctypes.util.find_library", return_value=None), \
                mock.patch.object(host, "MAC_LIB_DIRS", ()):
            self.assertEqual(host.find_library("codec2"), str(self.dir / "libcodec2.dylib"))
            self.assertIsNone(host.find_library("ad9361"))

    def test_a_mac_run_from_source_finds_homebrews_libraries(self):
        # dyld's fallback search (all find_library asks on macOS) has no
        # /opt/homebrew/lib, where `brew install codec2` puts it on Apple Silicon.
        (self.dir / "libcodec2.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
        with system("macos"), mock.patch("ctypes.util.find_library", return_value=None), \
                mock.patch.object(host, "MAC_LIB_DIRS", ("/nowhere", str(self.dir))):
            self.assertEqual(host.find_library("codec2"), str(self.dir / "libcodec2.dylib"))
        with system("macos"), mock.patch("ctypes.util.find_library", return_value="/usr/local/lib/libcodec2.dylib"):
            self.assertEqual(host.find_library("codec2"), "/usr/local/lib/libcodec2.dylib")


class LocalNetworkHint(unittest.TestCase):
    """host.local_network_hint in isolation, pinned here so the errno/address
    rules are visible without reading them back out of a DeviceError (the
    Libiio tests below exercise the same function through PlutoDevice.open,
    which is where an operator actually sees it)."""

    def test_only_the_two_errnos_the_privacy_refusal_uses(self):
        with system("macos"):
            self.assertNotEqual(host.local_network_hint(65, "198.51.100.10"), "")
            self.assertNotEqual(host.local_network_hint(1, "198.51.100.10"), "")
            self.assertEqual(host.local_network_hint(61, "198.51.100.10"), "")

    def test_only_a_private_non_loopback_address(self):
        with system("macos"):
            self.assertNotEqual(host.local_network_hint(65, "10.1.2.3"), "")
            self.assertNotEqual(host.local_network_hint(65, "169.254.1.1"), "")
            self.assertEqual(host.local_network_hint(65, "127.0.0.1"), "")
            self.assertEqual(host.local_network_hint(65, "8.8.8.8"), "")

    def test_not_an_address_at_all_is_silently_no_hint(self):
        # "" (no host could be parsed from the uri, e.g. "usb:") and a
        # hostname (never resolved here) are the same case: say nothing
        # rather than guess.
        with system("macos"):
            self.assertEqual(host.local_network_hint(65, ""), "")
            self.assertEqual(host.local_network_hint(65, "pluto.local"), "")

    def test_never_on_linux_or_windows(self):
        for name in ("linux", "windows"):
            with system(name):
                self.assertEqual(host.local_network_hint(65, "198.51.100.10"), "")


class Tools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name) / "wsjtx" / "bin"
        self.bin.mkdir(parents=True)
        # find_tool honours SHACK_NO_WSJTX (the Mac build exports it for the
        # whole suite); these tests are about its search, so they own the
        # variable and pass under either setting.
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SHACK_NO_WSJTX", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_windows_finds_jt9_in_the_wsjtx_install_folder_off_path(self):
        (self.bin / "jt9.exe").write_bytes(b"MZ")
        with system("windows"), mock.patch("shutil.which", return_value=None), \
                mock.patch.object(host, "WSJTX_DIRS", ("/nowhere/bin", str(self.bin))):
            self.assertEqual(host.find_tool("jt9"), str(self.bin / "jt9.exe"))
            self.assertIsNone(host.find_tool("ft4code"))

    def test_path_wins_and_linux_never_looks_further(self):
        (self.bin / "jt9.exe").write_bytes(b"MZ")
        with mock.patch.object(host, "WSJTX_DIRS", (str(self.bin),)):
            with system("windows"), mock.patch("shutil.which", return_value="/p/jt9"):
                self.assertEqual(host.find_tool("jt9"), "/p/jt9")
            with system("linux"), mock.patch("shutil.which", return_value=None):
                self.assertIsNone(host.find_tool("jt9"))

    def test_a_bundles_own_wsjtx_folder_is_never_used(self):
        # No build carries WSJT-X since 17/10/2026; a "wsjtx" folder an
        # older install left in the bundle (on the Mac, Intel tools that
        # crashed once notarised) must not be picked over an installed
        # WSJT-X, or over nothing.
        bundle = Path(self.tmp.name) / "bundle"
        (bundle / "wsjtx" / "bin").mkdir(parents=True)
        for n in ("jt9.exe", "ft8code.exe", "jt9"):
            (bundle / "wsjtx" / "bin" / n).write_bytes(b"MZ")
        (self.bin / "jt9.exe").write_bytes(b"MZ")
        for name in ("windows", "macos", "linux"):
            with Frozen(bundle), system(name), mock.patch("shutil.which", return_value=None), \
                    mock.patch.object(host, "WSJTX_DIRS", ("/nowhere/bin",)), \
                    mock.patch.object(host, "MAC_WSJTX_APPS", ("/nowhere/wsjtx.app",)):
                self.assertIsNone(host.find_tool("jt9"), name)
                self.assertIsNone(host.find_tool("ft8code"), name)
        with Frozen(bundle), system("windows"), mock.patch("shutil.which", return_value=None), \
                mock.patch.object(host, "WSJTX_DIRS", (str(self.bin),)):
            self.assertEqual(host.find_tool("jt9"), str(self.bin / "jt9.exe"))

    def test_console_children_get_no_window_only_on_windows(self):
        with system("linux"):
            self.assertEqual(host.no_console(), {})
        with system("windows"):
            self.assertEqual(host.no_console(), {"creationflags": 0x08000000})
        with system("macos"):
            self.assertEqual(host.no_console(), {})

    def test_shack_no_wsjtx_hides_every_installed_one(self):
        (self.bin / "jt9.exe").write_bytes(b"MZ")
        for name in ("windows", "linux"):
            with system(name), mock.patch("shutil.which", return_value="/usr/bin/jt9"), \
                    mock.patch.object(host, "WSJTX_DIRS", (str(self.bin),)), \
                    mock.patch.dict(os.environ, {"SHACK_NO_WSJTX": "1"}):
                self.assertIsNone(host.find_tool("jt9"), name)

    def test_the_mac_finds_an_installed_wsjtx_app_after_path(self):
        # Mac tools have no .exe; PATH first, then WSJT-X's .app, which
        # (like Windows' installer) never touches PATH.
        app = Path(self.tmp.name) / "Applications" / "wsjtx.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "MacOS" / "q65code").write_bytes(b"\xcf\xfa\xed\xfe")
        with system("macos"), mock.patch("shutil.which", return_value="/opt/homebrew/bin/jt9"), \
                mock.patch.object(host, "MAC_WSJTX_APPS", (str(app),)):
            self.assertEqual(host.find_tool("jt9"), "/opt/homebrew/bin/jt9")
        with system("macos"), mock.patch("shutil.which", return_value=None), \
                mock.patch.object(host, "MAC_WSJTX_APPS", ("/nowhere/wsjtx.app", str(app))):
            self.assertEqual(host.find_tool("q65code"), str(app / "Contents" / "MacOS" / "q65code"))
            self.assertIsNone(host.find_tool("ft4code"))

    def test_cty_dat_wherever_wsjtx_installs_it_on_each_system_never_the_bundles_wsjtx_folder(self):
        # A Windows or Mac bundle carries ours in ohscore/data (ohscore/dxcc.py
        # looks there before any of these); a cty.dat an installer before
        # 0.1.10 left in its wsjtx folder is WSJT-X 2.7.0's, older than ours.
        bundle = Path(self.tmp.name) / "bundle"
        (bundle / "wsjtx" / "share" / "wsjtx").mkdir(parents=True)
        (bundle / "wsjtx" / "share" / "wsjtx" / "cty.dat").write_text("stale")
        with Frozen(bundle), system("macos"), mock.patch.object(host, "MAC_WSJTX_APPS", ("/A/wsjtx.app",)):
            self.assertEqual(host.wsjtx_cty_files(), [Path("/A/wsjtx.app/Contents/Resources/wsjtx/cty.dat")])
        with Frozen(bundle), system("windows"), mock.patch.object(host, "WSJTX_DIRS", ("/W/wsjtx/bin",)):
            self.assertEqual(host.wsjtx_cty_files(), [Path("/W/wsjtx/share/wsjtx/cty.dat")])
        with Frozen(bundle), system("linux"):
            self.assertEqual(host.wsjtx_cty_files()[0], Path("/usr/share/wsjtx/cty.dat"))


class Libiio(unittest.TestCase):
    """What the operator reads when libiio is missing or the wrong series -
    a DeviceError sentence, never an import traceback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = sys.modules.pop("iio", None)
        sys.path.insert(0, self.tmp.name)

    def tearDown(self):
        sys.path.remove(self.tmp.name)
        sys.modules.pop("iio", None)
        if self.saved is not None:
            sys.modules["iio"] = self.saved
        self.tmp.cleanup()

    def fake_iio(self, body: str):
        Path(self.tmp.name, "iio.py").write_text(body)

    def open_pluto(self):
        from ohscore.devices import DeviceError
        from ohscore.devices.pluto import PlutoDevice
        with self.assertRaises(DeviceError) as cm:
            PlutoDevice("usb:").open()
        return str(cm.exception)

    def test_libiio_1_0_dll_under_0_2x_bindings_says_which_series(self):
        # The 0.2x bindings look their symbols up at import: a 1.0 DLL lacks them.
        self.fake_iio("raise AttributeError('function iio_create_default_context not found')\n")
        with system("windows"):
            msg = self.open_pluto()
        self.assertIn("1.0", msg)
        self.assertIn("libiio 0.26", msg)

    def test_no_dll_at_all_is_a_sentence_not_a_traceback(self):
        self.fake_iio("raise TypeError('expected str, bytes or os.PathLike object, not NoneType')\n")
        with system("windows"):
            msg = self.open_pluto()
        self.assertIn("could not be loaded", msg)

    def test_missing_bindings_on_linux_still_say_apt(self):
        self.fake_iio("raise ImportError('no iio')\n")
        with system("linux"):
            self.assertEqual(self.open_pluto(), "The Pluto needs libiio: sudo apt install python3-libiio")

    def test_no_pluto_on_windows_hides_errno_0_and_names_the_drivers(self):
        # libiio on Windows fails with an OSError whose errno is 0 (its
        # bindings do not read the Win32 last-error) - seen on the test VM.
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(0, 'No error')\n")
        with system("windows"):
            msg = self.open_pluto()
        self.assertTrue(msg.startswith("No Pluto at usb:."), msg)
        self.assertNotIn("Errno", msg)
        self.assertIn("PlutoSDR drivers", msg)

    # ADI's iio.py finds libiio.dll by walking PATH (ctypes.util.find_library
    # on Windows), so what it would find is decided by PATH at import time.
    # The fake records PATH as the import sees it.
    RECORD_PATH = "import os\nPATH_AT_IMPORT = os.environ.get('PATH', '')\n"

    def bundle_with_libiio(self) -> Path:
        bundle = Path(self.tmp.name) / "bundle"
        (bundle / "libiio").mkdir(parents=True)
        (bundle / "libiio" / "libiio.dll").write_bytes(b"MZ")
        return bundle

    def test_a_frozen_windows_build_imports_against_its_own_libiio_first(self):
        self.fake_iio(self.RECORD_PATH)
        bundle = self.bundle_with_libiio()
        before = os.environ.get("PATH")
        from ohscore.devices.pluto import import_iio
        with Frozen(bundle), system("windows"):
            iio = import_iio()
        first = iio.PATH_AT_IMPORT.split(os.pathsep)[0]
        self.assertEqual(Path(first), bundle / "libiio")
        # ...and only for the import: child processes (jt9, rigctld) must not
        # inherit the bundle's libusb and libxml2 on their PATH.
        self.assertEqual(os.environ.get("PATH"), before)

    def test_the_bundled_folder_leaves_path_alone_when_the_dll_is_missing(self):
        # A damaged install (folder there, DLL gone) falls back to the system
        # search rather than pointing the import at an empty folder.
        self.fake_iio(self.RECORD_PATH)
        bundle = self.bundle_with_libiio()
        (bundle / "libiio" / "libiio.dll").unlink()
        from ohscore.devices.pluto import import_iio
        with Frozen(bundle), system("windows"):
            iio = import_iio()
        self.assertEqual(iio.PATH_AT_IMPORT, os.environ.get("PATH", ""))

    def test_linux_and_source_runs_never_touch_path(self):
        self.fake_iio(self.RECORD_PATH)
        bundle = self.bundle_with_libiio()
        from ohscore.devices.pluto import import_iio
        with Frozen(bundle), system("linux"):
            self.assertEqual(import_iio().PATH_AT_IMPORT, os.environ.get("PATH", ""))
        sys.modules.pop("iio", None)
        with system("windows"):           # not frozen: run from source
            self.assertEqual(import_iio().PATH_AT_IMPORT, os.environ.get("PATH", ""))

    def test_a_frozen_mac_build_imports_against_its_own_libiio_first(self):
        # iio.py's find_library("iio") reads DYLD_LIBRARY_PATH first on
        # macOS, so the bundle's folder goes there for the import - and only
        # for the import - and PATH is left alone.
        self.fake_iio("import os\nSEEN = os.environ.get('DYLD_LIBRARY_PATH', '')\n"
                      "PATH_AT_IMPORT = os.environ.get('PATH', '')\n")
        bundle = Path(self.tmp.name) / "bundle"
        (bundle / "libiio").mkdir(parents=True)
        (bundle / "libiio" / "libiio.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
        before = os.environ.get("DYLD_LIBRARY_PATH")
        from ohscore.devices.pluto import import_iio
        with Frozen(bundle), system("macos"):
            iio = import_iio()
        self.assertEqual(Path(iio.SEEN.split(os.pathsep)[0]), bundle / "libiio")
        self.assertEqual(iio.PATH_AT_IMPORT, os.environ.get("PATH", ""))
        self.assertEqual(os.environ.get("DYLD_LIBRARY_PATH"), before)

    def test_no_pluto_on_a_mac_points_at_find_not_at_drivers_or_iio_info(self):
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(61, 'Connection refused')\n")
        with system("macos"):
            msg = self.open_pluto()
        self.assertTrue(msg.startswith("No Pluto at usb:"), msg)
        self.assertIn("Find in Settings", msg)
        self.assertNotIn("iio_info", msg)
        self.assertNotIn("drivers", msg)
        # "usb:" has no host to check for Local Network privacy against, and
        # 61 (connection refused) is not one of its two errnos either.
        self.assertNotIn("Local Network", msg)

    def open_pluto_at(self, uri: str):
        from ohscore.devices import DeviceError
        from ohscore.devices.pluto import PlutoDevice
        with self.assertRaises(DeviceError) as cm:
            PlutoDevice(uri).open()
        return str(cm.exception)

    def test_a_lan_address_blocked_by_macos_names_local_network_privacy(self):
        # Errno 65 (EHOSTUNREACH): seen 07/10/2026 with a LibreSDR on the
        # LAN that answered ping and a direct TCP connect from the same Mac
        # - libiio's own connect was refused before it reached the radio,
        # because Info.plist had not asked for Local Network access yet.
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(65, 'No route to host')\n")
        with system("macos"):
            msg = self.open_pluto_at("ip:198.51.100.74")
        self.assertIn("Local Network", msg)
        self.assertIn("System Settings", msg)

    def test_eperm_is_the_same_refusal_as_ehostunreach(self):
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(1, 'Operation not permitted')\n")
        with system("macos"):
            msg = self.open_pluto_at("ip:10.0.0.5")
        self.assertIn("Local Network", msg)

    def test_the_hint_is_mac_only(self):
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(65, 'No route to host')\n")
        for name in ("linux", "windows"):
            with system(name):
                self.assertNotIn("Local Network", self.open_pluto_at("ip:198.51.100.74"))

    def test_loopback_and_public_addresses_are_never_blamed_on_local_network(self):
        # Loopback never crosses the boundary Local Network privacy guards
        # (and is what the build's own smoke test connects to); a public
        # address refusing a connection is an ordinary network failure.
        self.fake_iio("class Context:\n"
                      "    def __init__(self, uri):\n"
                      "        raise OSError(65, 'No route to host')\n")
        with system("macos"):
            self.assertNotIn("Local Network", self.open_pluto_at("ip:127.0.0.1"))
            self.assertNotIn("Local Network", self.open_pluto_at("ip:8.8.8.8"))

    def test_a_missing_bundled_libiio_on_windows_says_reinstall(self):
        self.fake_iio("raise TypeError('expected str, bytes or os.PathLike object, not NoneType')\n")
        with system("windows"):
            msg = self.open_pluto()
        self.assertIn("reinstall", msg)
        self.assertIn("not 1.0", msg)

    def test_a_mac_is_never_told_to_use_apt(self):
        with system("macos"):
            for what in ("libiio", "soapysdr", "wsjtx", "pyserial"):
                self.assertNotIn("apt", host.hint(what), what)
            self.assertIn(".dmg", host.hint("libiio"))
            self.assertEqual(host.system_name(), "macos")

    def test_soapy_is_linux_only_on_windows(self):
        from ohscore.devices import DeviceError
        from ohscore.devices.soapy import SoapyDevice
        with mock.patch.dict(sys.modules, {"SoapySDR": None}), system("windows"):
            with self.assertRaises(DeviceError) as cm:
                SoapyDevice("").open()
        self.assertIn("Linux-only", str(cm.exception))


class SoundDevices(unittest.TestCase):
    """Windows lists each card once per host API; only the default API's
    copy is offered, so choosing by name means one thing."""

    class FakePA:
        DEVS = [{"name": "Speakers (USB Audio)", "hostApi": 0, "maxInputChannels": 0, "maxOutputChannels": 2},
                {"name": "Speakers (USB Audio)", "hostApi": 1, "maxInputChannels": 0, "maxOutputChannels": 2},
                {"name": "Speakers (USB Audio)", "hostApi": 2, "maxInputChannels": 0, "maxOutputChannels": 2}]

        def get_default_host_api_info(self):
            return {"index": 0}

    def test_windows_offers_one_copy_linux_offers_all(self):
        from ohscore import audio
        pa = self.FakePA()
        with system("windows"):
            self.assertEqual([audio._usable_api(pa, d) for d in pa.DEVS], [True, False, False])
        with system("linux"):
            self.assertEqual([audio._usable_api(pa, d) for d in pa.DEVS], [True, True, True])
        with system("macos"):                   # Core Audio is the one host API there
            self.assertEqual([audio._usable_api(pa, d) for d in pa.DEVS], [True, True, True])


try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class Icon(unittest.TestCase):
    def test_frozen_build_finds_the_ico_shipped_beside_it(self):
        from ohsnb.ui import appicon
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "openhamshack-nb.ico").write_bytes(b"\0\0\1\0")
            with Frozen(Path(d)):
                self.assertEqual(appicon.svg_path(), Path(d) / "openhamshack-nb.ico")

    def test_source_tree_still_uses_packaging_svg(self):
        from ohsnb.ui import appicon
        self.assertEqual(appicon.svg_path().name, "openhamshack-nb.svg")


if __name__ == "__main__":
    unittest.main()
