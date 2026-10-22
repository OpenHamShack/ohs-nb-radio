"""Diagnostics (ohscore/diag.py, ohscore/ui/diagnostics.py): the log file
both apps write, what lands in it, and the zip Help › Save diagnostics…
makes. Every test runs the code - starts the log, raises in a thread,
builds the zip from a running window - and reads back what was written."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ohscore import diag
from ohsnb.devices.sim import SimDevice

from helpers import make_radio, run_sim, wait_rx_lock

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

ROOT = Path(__file__).resolve().parents[1]


class LogCase(unittest.TestCase):
    """A log started in a scratch data folder, stopped afterwards."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.setup = None

    def tearDown(self):
        if self.setup is not None:
            self.setup.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    APP = "openhamshack-test"

    def start(self, verbose=False):
        self.setup = diag.start_logging(self.APP, self.tmp, verbose, console=False)
        return self.setup

    def text(self) -> str:
        self.setup.flush()
        return self.setup.path.read_text(encoding="utf-8")


class LogFile(LogCase):
    def test_created_in_the_data_folders_logs(self):
        s = self.start()
        logging.getLogger("ohsnb.radio").info("hello from the radio")
        logging.getLogger("ohsnb.radio").debug("not at INFO")
        self.assertEqual(s.path, self.tmp / "logs" / "openhamshack-test.log")
        text = self.text()
        self.assertIn("hello from the radio", text)
        self.assertNotIn("not at INFO", text)

    def test_verbose_logs_debug(self):
        self.start(verbose=True)
        logging.getLogger("ohsnb.radio").debug("detail for -v")
        self.assertIn("detail for -v", self.text())

    def test_rotates_and_keeps_five(self):
        with mock.patch.object(diag, "LOG_BYTES", 4000):
            s = self.start()
        lg = logging.getLogger("ohsnb.radio")
        for i in range(600):
            lg.info("line %04d %s", i, "x" * 60)
        s.flush()
        files = s.files()
        self.assertEqual(files[0], s.path)
        self.assertEqual([p.name for p in files[1:]], [f"openhamshack-test.log.{i}" for i in range(1, 6)])
        for p in files:
            self.assertLessEqual(p.stat().st_size, 4000 + 200)
        self.assertIn("line 0599", s.path.read_text(encoding="utf-8"))

    def test_an_exception_in_a_thread_lands_in_it(self):
        self.start()

        def boom():
            raise ValueError("boom in a worker thread 4711")
        with mock.patch.object(sys, "stderr", None):       # as in the Windows GUI build: no console
            t = threading.Thread(target=boom, name="ohsnb-rx")
            t.start()
            t.join()
        text = self.text()
        self.assertIn("Uncaught exception in thread ohsnb-rx", text)
        self.assertIn("ValueError: boom in a worker thread 4711", text)
        self.assertIn("Traceback", text)

    def test_an_uncaught_exception_lands_in_it(self):
        # What PyQt calls for an exception escaping a slot.
        self.start()
        try:
            raise RuntimeError("a slot failed 815")
        except RuntimeError:
            with mock.patch.object(sys, "stderr", None):
                sys.excepthook(*sys.exc_info())
        self.assertIn("RuntimeError: a slot failed 815", self.text())

    def test_hooks_are_restored_when_stopped(self):
        before = sys.excepthook, threading.excepthook
        self.start()
        self.assertIsNot(sys.excepthook, before[0])
        self.setup.stop()
        self.setup = None
        self.assertEqual((sys.excepthook, threading.excepthook), before)

    def test_a_stalled_disk_never_blocks_the_caller(self):
        """The receive thread logging while the file cannot be written:
        the call returns at once, and what did not fit is counted, not
        waited for."""
        s = self.start()
        gate = threading.Event()
        real_emit = s.file_handler.emit

        def stalled(record):
            gate.wait(10)
            real_emit(record)
        s.file_handler.emit = stalled
        took = {}

        def dsp():
            lg = logging.getLogger("ohsnb.radio")
            t0 = time.perf_counter()
            for i in range(diag.QUEUE_MAX + 2000):
                lg.info("block %d", i)
            took["s"] = time.perf_counter() - t0
        t = threading.Thread(target=dsp, name="ohsnb-rx")
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "logging blocked the thread")
        self.assertLess(took["s"], 3.0)
        gate.set()
        s.flush(10)
        logging.getLogger("ohsnb.radio").info("after the stall")
        text = self.text()
        self.assertRegex(text, r"after the stall \[\d+ earlier log lines dropped")

    def test_the_engine_keeps_receiving_while_the_log_is_stalled(self):
        s = self.start(verbose=True)
        gate = threading.Event()
        s.file_handler.emit = lambda r: gate.wait(10)
        r = make_radio(str(self.tmp))
        r.start()
        try:
            t0 = time.monotonic()
            run_sim(r, 3.0, timeout=20)
            self.assertLess(time.monotonic() - t0, 20)
            self.assertTrue(r.state()["running"])
        finally:
            gate.set()
            r.stop()


class StartUp(unittest.TestCase):
    """Both apps' real entry points, headless: the file appears where the
    guide says, with the start-up facts and the device opening."""

    def run_app(self, module, env_prefix, name):
        data = Path(os.environ[f"{env_prefix}_DATA"])
        log = data / "logs" / f"{name}.log"
        if log.exists():
            log.unlink()
        out = subprocess.run([sys.executable, "-m", module, "--headless", "--seconds", "1.5", "--no-audio"],
                             cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        text = log.read_text(encoding="utf-8")
        for fact in ("version: ", "os: ", "python: ", "pyqt: ", "qt: ", "numpy: ", "libiio: ", "libiio library: ",
                     "pyserial: ", "jt9: ", "cty.dat: ", "codec2: ", "audio backend: null", "frozen: no"):
            self.assertIn(fact, text)
        self.assertIn("device sim opened", text)
        self.assertIn("device sim closed", text)
        self.assertIn("exiting", text)
        return text

    def test_nb(self):
        text = self.run_app("ohsnb", "OHS_NB", "openhamshack-nb")
        self.assertIn("---- OpenHamShack QO-100 NB", text)

    def test_ham(self):
        text = self.run_app("ohsradio", "OHS_RADIO", "openhamshack-radio")
        self.assertIn("---- OpenHamShack Radio", text)


class Jt9Fact(unittest.TestCase):
    """No build carries WSJT-X since 17/10/2026, so a missing jt9 is the
    normal case wherever ohsdigi decodes: the start-up facts say so calmly,
    and only call it a fault where nothing decodes at all."""

    def jt9(self, found, ohsdigi):
        from ohscore.modes import ft8
        with mock.patch.object(diag.host, "find_tool", return_value=found), \
                mock.patch.object(ft8, "_OHSDIGI_DEC", ohsdigi):
            return diag.facts("OpenHamShack QO-100 NB", "9.9.9")["jt9"]

    def test_absent_beside_ohsdigi_is_optional(self):
        self.assertEqual(self.jt9(None, object()), "not installed (optional; ohsdigi decodes)")

    def test_absent_with_no_ohsdigi_is_a_fault(self):
        self.assertEqual(self.jt9(None, None), "not found, and no ohsdigi: nothing decodes FT8")

    def test_an_installed_one_is_named(self):
        self.assertEqual(self.jt9("/Applications/wsjtx.app/Contents/MacOS/jt9", object()),
                         "/Applications/wsjtx.app/Contents/MacOS/jt9")


class EngineLog(unittest.TestCase):
    def test_lock_changes_are_logged_with_the_correction(self):
        r = make_radio(tempfile.mkdtemp(), simRxErrorHz=1500.0)
        with self.assertLogs("ohsnb.radio", "INFO") as cm:
            r.start()
            try:
                self.assertTrue(wait_rx_lock(r))
                run_sim(r, 1.0)
                time.sleep(0.3)                  # the supervisor's next tick
            finally:
                r.stop()
        text = "\n".join(cm.output)
        self.assertRegex(text, r"rxLock: 'searching' -> 'locked' \(rxCorr [+-]\d")
        self.assertIn("device sim opened", text)
        self.assertIn("device sim closed", text)

    def test_status_ring_holds_two_minutes(self):
        r = make_radio(tempfile.mkdtemp())
        self.assertEqual(r.status_lines.maxlen, 120)
        r.start()
        try:
            run_sim(r, 2.0)
            time.sleep(1.2)
        finally:
            r.stop()
        lines = list(r.status_lines)
        self.assertGreaterEqual(len(lines), 1)
        self.assertRegex(lines[-1], r"^\d\d:\d\d:\d\d RUN  USB .* rx-lock \w+ corr [+-]")

    def _radio(self, tmp):
        from helpers import sim_cfg
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        return Radio(sim_cfg(), conf_path=tmp / "config.json", data_dir=tmp, audio=NullAudio(realtime=False))

    def test_saving_settings_logs_old_and_new_values_and_who(self):
        # Ray's log said "rigTxAudioOut changed" and nothing else: what it
        # had been, what it became and who changed it are the line now.
        r = self._radio(Path(tempfile.mkdtemp()))
        with r.changes_from("IC-9700 setup assistant: Find"):
            r.set(authorise=True, rigTxAudioOut="USB Audio CODEC")
        r.set(volume=0.3)
        with self.assertLogs("ohsnb.radio", "INFO") as cm:
            r._save(force=True)
        text = "\n".join(cm.output)
        self.assertIn("setting rigTxAudioOut: '' -> 'USB Audio CODEC' (IC-9700 setup assistant: Find)", text)
        # Not named: the caller, by module and function.
        self.assertRegex(text, r"setting volume: [\d.]+ -> 0\.3 \(test_diag\.test_saving_settings_logs_old_and_new")
        # Logged once: the next save has nothing new to say.
        with self.assertNoLogs("ohsnb.radio", "INFO"):
            r._save(force=True)

    def test_the_setup_assistant_names_its_step(self):
        from ohsnb.rigsetup import RigSetup
        r = self._radio(Path(tempfile.mkdtemp()))
        with self.assertLogs("ohsnb.radio", "INFO") as cm:
            RigSetup(r)._save({"usbMod": 50, "port": "COM3"}, "Put back")
            r._save(force=True)
        self.assertIn("(IC-9700 setup assistant: Put back)", "\n".join(cm.output))

    def test_secret_looking_values_are_redacted(self):
        self.assertEqual(diag.setting_value("uploadToken", "abc123"), "'<redacted>'")
        self.assertEqual(diag.setting_value("note", "sk-" + "a" * 20), "'<redacted>'")
        self.assertEqual(diag.setting_value("keyerRepeat", True), "true")
        self.assertTrue(diag.setting_value("memories", ["x" * 50] * 20).endswith("..."))

    def test_a_startup_migration_is_logged(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "config.json").write_text(json.dumps({"beaconLock": False, "volume": 0.4}), encoding="utf-8")
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        with self.assertLogs("ohsnb.radio", "INFO") as cm:
            r = Radio(conf_path=tmp / "config.json", data_dir=tmp, audio=NullAudio(realtime=False))
        text = "\n".join(cm.output)
        self.assertIn("setting beaconLock: false -> (removed) (startup migration)", text)
        self.assertEqual(r.cfg["beaconMode"], "hold")
        self.assertNotIn("setting volume", text)


class Clock(unittest.TestCase):
    """The clock line: what the system says about its own time source
    (FT8 needs the clock within a second), from the commands each system
    already has. The commands are stand-ins here; nothing is asked."""

    W32TM = ("Leap Indicator: 0(no warning)\nStratum: 4 (secondary reference - syncd by (S)NTP)\n"
             "Precision: -23 (119.209ns per tick)\nLast Successful Sync Time: 12/10/2026 21:14:05\n"
             "Source: time.windows.com,0x9\nPoll Interval: 10 (1024s)\n")

    def ran(self, stdout="", stderr="", code=0, windows=False, raises=None):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(cmd, code, stdout, stderr)
        with mock.patch.object(diag.subprocess, "run", run), mock.patch.object(diag.host, "WINDOWS", windows), \
                mock.patch.object(diag.sys, "platform", "win32" if windows else "linux"):
            line = diag.clock_source()
        return line, calls

    def test_windows_says_its_source_and_last_sync(self):
        line, calls = self.ran(self.W32TM, windows=True)
        self.assertEqual(calls, [["w32tm", "/query", "/status"]])
        self.assertEqual(line, "w32tm: Source time.windows.com,0x9, Last Successful Sync Time 12/10/2026 21:14:05, "
                               "Leap Indicator 0(no warning), Stratum 4 (secondary reference - syncd by (S)NTP)")

    def test_windows_time_service_stopped_is_said(self):
        line, _ = self.ran("The following error occurred: The service has not been started. (0x80070426)",
                           code=1, windows=True)
        self.assertEqual(line, "w32tm: The following error occurred: The service has not been started. (0x80070426)")

    def test_linux_says_whether_ntp_has_synchronised(self):
        line, calls = self.ran("NTP=yes\nNTPSynchronized=no\n")
        self.assertEqual(calls[0][0], "timedatectl")
        self.assertEqual(line, "timedatectl: NTP service yes, synchronised no")

    def test_no_command_is_a_line_not_a_failure(self):
        line, _ = self.ran(raises=FileNotFoundError(2, "No such file", "timedatectl"))
        self.assertEqual(line, "not checked: timedatectl not found")

    def test_logged_now_and_then_every_period_until_the_log_stops(self):
        with mock.patch.object(diag, "clock_source", lambda: "timedatectl: NTP service yes, synchronised yes"), \
                self.assertLogs("ohscore.diag", "INFO") as cm:
            th = diag.start_clock_log(every=0.05)
            time.sleep(0.2)
            diag._clock_stop.set()
            th.join(1.0)
        self.assertFalse(th.is_alive())
        lines = [m for m in cm.output if "clock:" in m]
        self.assertGreaterEqual(len(lines), 2)
        self.assertRegex(lines[0], r"clock: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC; time source: timedatectl: "
                                   r"NTP service yes, synchronised yes")


class Watching(unittest.TestCase):
    def test_changes_once_counters_summarised_slow_keys_settle(self):
        lg = logging.getLogger("test.watch")
        w = diag.Watch(lg, keys=("rxLock",), slow=("rigFreq",), every=10.0, slow_s=5.0)
        st = {"rxLock": "searching", "rigFreq": 0.0}
        with self.assertLogs("test.watch", "INFO") as cm:
            t = 0.0
            for i in range(300):                      # 30 s at 10 Hz
                t = i * 0.1
                st["rxLock"] = "locked" if t >= 2.0 else "searching"
                st["rigFreq"] = 1_296_000_000.0 + (min(t, 12.0) * 1000.0 if t >= 1.0 else 0)
                w.tick(t, st, {"receive overruns": i // 20 if t < 15 else 14})
        out = [m.split(":", 2)[2] for m in cm.output]
        self.assertEqual(sum("rxLock" in m for m in out), 1)
        self.assertIn("rxLock: 'searching' -> 'locked'", out[[i for i, m in enumerate(out) if "rxLock" in m][0]])
        rig = [m for m in out if m.startswith("rigFreq")]
        self.assertLessEqual(len(rig), 5)                     # not 110 lines while the knob turned
        self.assertTrue(rig[-1].endswith("1296.012000 MHz"))  # where it settled
        over = [m for m in out if "overruns" in m]
        self.assertEqual(len(over), 2)                        # 0-10 s, 10-20 s; none after it stopped
        self.assertIn("receive overruns +5", over[0])


class Redaction(unittest.TestCase):
    def test_secrets_go_callsign_and_locator_stay(self):
        cfg = {"callsign": "G4XYZ", "locator": "IO91wm", "qrzPassword": "hunter2", "apiToken": "abc123",
               "logUpload": {"clublogApiKey": "k-999", "user": "g4xyz"}, "rigctldHost": "10.0.0.5",
               "feed": "https://g4xyz:pa55word@example.org/x", "memories": [{"name": "net", "dl": 1.0}],
               "emptySecret": ""}
        out = diag.redact(cfg)
        dumped = json.dumps(out)
        for secret in ("hunter2", "abc123", "k-999", "pa55word"):
            self.assertNotIn(secret, dumped)
        self.assertEqual(out["callsign"], "G4XYZ")
        self.assertEqual(out["locator"], "IO91wm")
        self.assertEqual(out["rigctldHost"], "10.0.0.5")
        self.assertEqual(out["logUpload"]["user"], "g4xyz")
        self.assertEqual(out["feed"], f"https://g4xyz:{diag.REDACTED}@example.org/x")
        self.assertEqual(out["emptySecret"], "")
        self.assertEqual(out["memories"], cfg["memories"])

    def test_collected_config_is_redacted(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "config.json").write_text(json.dumps({"callsign": "G4XYZ", "password": "hunter2"}))
        (tmp / "ui.json").write_text("{not json")
        entries = dict(diag.collect("openhamshack-test", tmp, tmp / "config.json", tmp / "ui.json", "report",
                                    ["a line"]))
        self.assertNotIn(b"hunter2", entries["config.json"])
        self.assertIn(b"G4XYZ", entries["config.json"])
        self.assertIn(b"not valid JSON", entries["ui.json"])
        self.assertNotIn(b"{not json", entries["ui.json"])


class PlutoContext(unittest.TestCase):
    def test_reads_the_open_context_only(self):
        from ohscore.devices.pluto import PlutoDevice

        class Ctx:
            attrs = {"fw_version": "v0.38", "hw_model": "Analog Devices PlutoSDR Rev.C (Z7010-AD9363A)",
                     "hw_serial": "104473b04a060006f9ff0f00c6d3b5d8f6"}
        d = PlutoDevice("ip:192.0.2.1")          # never opened: a documentation address
        self.assertEqual(d.context_attrs(), {})
        d.ctx = Ctx()
        self.assertEqual(d.context_attrs()["fw_version"], "v0.38")

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc/self/maps")
    def test_loaded_library_is_a_full_path(self):
        try:
            import iio
        except Exception:  # noqa: BLE001
            self.skipTest("no libiio here")
        p = diag.loaded_library(iio._lib)
        self.assertTrue(os.path.isabs(p), p)
        self.assertTrue(os.path.isfile(p))


class WithContext(SimDevice):
    """The simulator holding an IIO-like context, as an open Pluto does."""

    def context_attrs(self):
        return {"fw_version": "v0.38", "hw_serial": "1044735411960005", "ad9361-phy,model": "ad9364"}


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class SaveDiagnostics(LogCase):
    APP = "openhamshack-nb"     # the window's radio is NB's, with its data folder in self.tmp
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        super().setUp()
        self.errors = []
        self._hook = sys.excepthook

    def tearDown(self):
        super().tearDown()
        sys.excepthook = self._hook

    def window(self, app_name="nb"):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        os.environ["OHS_NB_UI_CONF"] = str(self.tmp / "ui.json")
        radio = make_radio(str(self.tmp), device=WithContext, callsign="G4XYZ", locator="IO91wm")
        radio.CONFIG.save(radio.cfg)          # as a running app has (make_radio does not persist)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        prefs.save()
        win, bridge = build(radio, prefs)
        win.resize(1400, 860)
        win.show()
        self.addCleanup(lambda: (win.close(), bridge.stop(), self.app.processEvents()))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            self.app.processEvents()
            time.sleep(0.01)
        return win, radio

    def test_zip_holds_the_files_and_a_report_with_the_facts(self):
        self.start()
        win, radio = self.window()
        from ohscore.ui import diagnostics
        dlg = diagnostics.save_diagnostics(win)
        listed = [dlg.files.item(i).text().split()[0] for i in range(dlg.files.count())]
        out = self.tmp / "out" / "diag.zip"
        out.parent.mkdir()
        self.assertTrue(dlg.save_to(out))
        self.assertTrue(dlg.btn_folder.isEnabled())
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            report = z.read("report.txt").decode()
            png = z.read("screenshot.png")
            log = z.read("logs/openhamshack-nb.log").decode() if "logs/openhamshack-nb.log" in names else ""
            cfg = json.loads(z.read("config.json"))
        self.assertEqual(listed, names)
        for name in ("report.txt", "status-recent.txt", "config.json", "ui.json", "screenshot.png"):
            self.assertIn(name, names)
        self.assertTrue(png.startswith(b"\x89PNG"))
        lines = {ln.split(":", 1)[0] for ln in report.splitlines() if ": " in ln}
        for key in ("version", "os", "python", "pyqt", "qt", "numpy", "frozen", "libiio", "libiio library",
                    "pyserial", "jt9", "ft8/ft4 encoder", "ft8/ft4 decoder", "cty.dat", "codec2", "controller pad",
                    "audio backend", "running", "fs", "cpu", "overruns",
                    "rxLock", "rxCorr", "txLockState", "txCorr", "rigLink", "rigFreq", "callsign", "locator",
                    "window", "fw_version", "hw_serial"):
            self.assertIn(key, lines, key)
        self.assertIn("== radio context (IIO attributes) ==", report)
        self.assertIn("fw_version: v0.38", report)
        self.assertRegex(report, r"screen 0 \(this window\): .*scale ")
        self.assertIn("callsign: G4XYZ", report)
        self.assertEqual(cfg.get("callsign"), "G4XYZ")
        self.assertIn("diagnostics requested", log)

    def test_open_log_folder_shows_the_log_folder(self):
        self.start()
        win, radio = self.window()
        with mock.patch("ohscore.ui.diagnostics.QDesktopServices.openUrl", return_value=True) as op:
            win.open_log_folder()
        self.assertEqual(Path(op.call_args[0][0].toLocalFile()), self.setup.log_dir)

    def test_help_menu_has_both_items(self):
        win, _ = self.window()
        helpm = [m for m in win.menuBar().actions() if m.text() == "&Help"][0].menu()
        texts = [a.text() for a in helpm.actions()]
        self.assertIn("Save diagnostics…", texts)
        self.assertIn("Open log folder", texts)


if __name__ == "__main__":
    unittest.main()
