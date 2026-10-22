"""Automatic diagnostics upload (ohscore/diagupload.py, ohscore/ui/diagsend.py)
against a fake endpoint on 127.0.0.1 that answers as openhamshack.com's
upload.php does: off by default, nothing without consent, what the bundle
holds and what it never holds, the size cap, when reports go (after a fault,
at most one per 30 minutes, daily), never while keyed, and a failed upload
leaving the radio exactly as it was. Nothing here reaches the real site."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import gzip
import http.server
import json
import logging
import os
import random
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ohscore import diag, diagupload

from test_ui_window import HAVE_QT, WindowCase


class FakeSite:
    """upload.php's contract: POST gzip, ?app=&version=&install=, answers
    {"code": "SHACK-XXXX"} - or the status and error it is told to."""

    def __init__(self):
        self.posts: list[dict] = []
        self.status = 200
        self.error = ""
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                site.posts.append({"query": q, "body": body, "type": self.headers.get("Content-Type")})
                if site.status != 200:
                    out = json.dumps({"error": site.error}).encode()
                    self.send_response(site.status)
                else:
                    out = json.dumps({"code": f"SHACK-{'7KQ4' if len(site.posts) == 1 else 'A' + str(len(site.posts)).zfill(3)}"}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/diag/upload.php"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def doc(self, i=-1) -> dict:
        return json.loads(gzip.decompress(self.posts[i]["body"]))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ no Qt
class Scrubbing(unittest.TestCase):
    def test_secrets_in_log_lines_go_and_the_line_stays(self):
        text = ("2026-10-12 INFO MainThread x: login password=hunter2 ok\n"
                "token: abcdef123456 for the logbook\n"
                "fetch https://ray:s3cret@example.org/feed\n"
                "key sk-ABCDEFGHIJKLMNOPQRSTUVWX pasted\n"
                'api_key="QRZ-0123456789" set\n'
                "callsign: GM4BRI locator IO75RL\n")
        out = diag.redact_text(text)
        for secret in ("hunter2", "abcdef123456", "s3cret", "sk-ABCDEFGHIJKLMNOPQRSTUVWX", "QRZ-0123456789"):
            self.assertNotIn(secret, out)
        self.assertIn("login password=<redacted> ok", out)
        self.assertIn("https://ray:<redacted>@example.org/feed", out)
        self.assertIn("GM4BRI", out)                  # the callsign is what the report is about
        self.assertIn("IO75RL", out)

    def test_the_bundle_holds_no_secret_from_config_log_or_attachment(self):
        tmp = Path(tempfile.mkdtemp())
        conf = tmp / "config.json"
        conf.write_text(json.dumps({"callsign": "GM4BRI", "qrzApiKey": "abcd1234", "lotwPassword": "pw",
                                    "pskReporter": True}))
        logf = tmp / "openhamshack-nb.log"
        logf.write_text("INFO clublog token=TOKEN-XYZ uploaded\nINFO rig ok\n")
        diag.attach("ic9700-diagnostic.txt", "report with secret: SHOULDNOTSHOW\n")
        try:
            body, _info = diagupload.build(app="nb", version="0.1.18", install="0" * 32, kind="manual", events=[],
                                           report="report.txt here", status_lines=["password=pw1"],
                                           conf_path=conf, ui_path=None, log_paths=[logf], fault_path=None)
        finally:
            diag._ATTACHED.clear()
        raw = gzip.decompress(body).decode()
        for secret in ("abcd1234", '"pw"', "TOKEN-XYZ", "SHOULDNOTSHOW", "pw1"):
            self.assertNotIn(secret, raw)
        doc = json.loads(raw)
        self.assertEqual(doc["config"]["callsign"], "GM4BRI")
        self.assertEqual(doc["config"]["qrzApiKey"], "<redacted>")
        self.assertIn("ic9700-diagnostic.txt", doc["attachments"])
        self.assertEqual((doc["app"], doc["version"], doc["kind"], doc["trigger"]), ("nb", "0.1.18", "manual", "manual"))


    # Device serial numbers as they really reach a log: an IC-9700's by-id
    # name in a saved setting and in pyserial's error, its hwid, a Soapy
    # SDRplay listing, a Pluto's IIO description and hw_serial line, and
    # on Windows the COM port's hwid and the PnP instance ids the CODEC
    # pairing logs (once plain, once JSON-escaped). The serial values are
    # invented in the shapes the real ones have.
    LINUX = (
        "2026-10-13 21:04:11,532 INFO MainThread ohsnb.engine: saved civPort = '/dev/serial/by-id/"
        "usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_IC-9700_13012144_A-if00-port0'\n"
        "2026-10-13 21:04:12,001 WARNING rig ohscore.notable: rig-link-lost: could not open port /dev/serial/by-id/"
        "usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_IC-9700_13012144_A-if00-port0: [Errno 2] "
        "No such file or directory\n"
        "2026-10-13 21:04:13,100 INFO MainThread ohsnb.rigdiag: /dev/ttyUSB0: CP2102N USB to UART Bridge Controller "
        "(USB VID:PID=10C4:EA60 SER=IC-9700 13012144 A LOCATION=1-1.2:1.0)\n"
        "2026-10-13 21:04:13,200 INFO MainThread ohsnb.rigdiag: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI"
        "-if00-port0\n"
        "2026-10-13 21:05:00,000 INFO MainThread ohsradio.soapy: found {'driver': 'sdrplay', "
        "'label': 'SDRplay Dev0 RSPdx 191101D142', 'serial': '191101D142'}\n"
        "2026-10-13 21:05:01,000 INFO MainThread ohscore.devices.pluto: usb:1.2.5 (Analog Devices PlutoSDR Rev.C "
        "(Z7010-AD9363A)), serial=03d7610bc4a5000f0d0021001b8e4c2f15\n"
        "hw_serial: 104473b04a060006f9ff0f00c6d3b5d8f6\n"
        "2026-10-13 21:05:02,000 INFO MainThread ohsnb.engine: rx 10489750000 Hz, dial 144174000, fs 2400000, "
        "pyserial: 3.5 (/usr/lib/python3/dist-packages/serial), seqPort /dev/ttyUSB1\n")
    WINDOWS = (
        "2026-10-13 21:04:11,532 INFO MainThread ohsnb.engine: saved civPort = 'COM5'\n"
        "2026-10-13 21:04:13,100 INFO MainThread ohsnb.rigdiag: COM5: Silicon Labs CP210x USB to UART Bridge (COM5) "
        "(USB VID:PID=10C4:EA60 SER=IC-9700_13012144_A LOCATION=1-3:x.0)\n"
        "2026-10-13 21:04:14,000 INFO MainThread ohscore.rig.usbpair: paired by hub: port "
        "USB\\VID_10C4&PID_EA60\\IC-9700_13012144_A, CODEC USB\\VID_08BB&PID_2901&MI_00\\7&2A3B4C5&0&0000\n"
        '{"port": "FTDIBUS\\\\VID_0403+PID_6001+A50285BIA\\\\0000", "pnp": "USB\\\\VID_10C4&PID_EA60\\\\IC-9700_13012144_A"}\n'
        "2026-10-13 21:05:00,000 INFO MainThread ohsradio.soapy: SDRplay Dev0 RSPdx 191101D142 opened, "
        "rx 145500000 Hz\n")
    SERIALS = ("13012144", "A50285BI", "191101D142", "03d7610bc4a5000f0d0021001b8e4c2f15",
               "104473b04a060006f9ff0f00c6d3b5d8f6", "2A3B4C5")

    def test_serial_numbers_go_from_linux_log_lines_and_the_rest_stays(self):
        out = diag.redact_text(self.LINUX)
        for serial in self.SERIALS:
            self.assertNotIn(serial, out)
        for kept in ("2026-10-13 21:04:11,532", "IC-9700_<serial>_A-if00-port0", "[Errno 2]", "/dev/ttyUSB0",
                     "VID:PID=10C4:EA60 SER=<serial> LOCATION=1-1.2:1.0", "usb-FTDI_FT232R_USB_UART_<serial>-if00",
                     "SDRplay Dev0 RSPdx <serial>", "'serial': '<serial>'", "usb:1.2.5", "Z7010-AD9363A",
                     "serial=<serial>", "hw_serial: <serial>", "10489750000 Hz", "dial 144174000", "fs 2400000",
                     "pyserial: 3.5", "seqPort /dev/ttyUSB1"):
            self.assertIn(kept, out)

    def test_serial_numbers_go_from_windows_log_lines_and_the_rest_stays(self):
        out = diag.redact_text(self.WINDOWS)
        for serial in self.SERIALS:
            self.assertNotIn(serial, out)
        for kept in ("civPort = 'COM5'", "Bridge (COM5)", "VID:PID=10C4:EA60 SER=<serial> LOCATION=1-3:x.0",
                     "USB\\VID_10C4&PID_EA60\\<serial>", "USB\\VID_08BB&PID_2901&MI_00\\<serial>",
                     "FTDIBUS\\\\VID_0403+PID_6001+<serial>", "USB\\\\VID_10C4&PID_EA60\\\\<serial>",
                     "SDRplay Dev0 RSPdx <serial> opened", "rx 145500000 Hz"):
            self.assertIn(kept, out)

    def test_the_bundle_holds_no_serial_number_from_any_part(self):
        tmp = Path(tempfile.mkdtemp())
        conf = tmp / "config.json"
        conf.write_text(json.dumps({"civPort": "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_"
                                               "Controller_IC-9700_13012144_A-if00-port0"}))
        logf = tmp / "openhamshack-nb.log"
        logf.write_text(self.LINUX + self.WINDOWS)
        diag.attach("ic9700-diagnostic.txt", "NB's port USB\\VID_10C4&PID_EA60\\IC-9700_13012144_A at 19200 baud\n")
        events = [("rig-link-lost", "could not open port /dev/serial/by-id/usb-Silicon_Labs_IC-9700_13012144_A"
                                    "-if00-port0", time.time())]
        try:
            body, _info = diagupload.build(app="nb", version="0.1.18", install="0" * 32, kind="fault", events=events,
                                           report="hw_serial: 104473b04a060006f9ff0f00c6d3b5d8f6",
                                           status_lines=["RSPdx 191101D142 ok"], conf_path=conf, ui_path=None,
                                           log_paths=[logf], fault_path=None)
        finally:
            diag._ATTACHED.clear()
        raw = gzip.decompress(body).decode()
        for serial in self.SERIALS:
            self.assertNotIn(serial, raw)
        self.assertIn("19200 baud", raw)


class SizeCap(unittest.TestCase):
    def test_a_huge_log_is_cut_from_its_oldest_end_to_fit(self):
        rnd = random.Random(1)
        # Random text compresses badly: 6 MB of it cannot fit in 2 MB whole.
        lines = [f"{i:07d} " + "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(90))
                 for i in range(60_000)]
        text = "\n".join(lines) + "\n"
        body, info = diagupload.pack({"schema": 1}, text, cap=diagupload.MAX_BYTES)
        self.assertLessEqual(len(body), diagupload.MAX_BYTES)
        self.assertTrue(info["logCut"])
        doc = json.loads(gzip.decompress(body))
        self.assertTrue(doc["logCut"])
        self.assertTrue(doc["log"].endswith(lines[-1] + "\n"))        # the newest line survives
        self.assertNotIn(lines[0], doc["log"])
        self.assertTrue(doc["log"].split("\n", 1)[0] in lines)          # cut at a line, not mid-line

    def test_a_small_log_goes_whole(self):
        body, info = diagupload.pack({"schema": 1}, "one\ntwo\n")
        self.assertFalse(info["logCut"])
        self.assertEqual(json.loads(gzip.decompress(body))["log"], "one\ntwo\n")


class Timing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = diagupload.State(self.tmp / "diag-upload.json")
        self.t0 = 1_800_000_000.0
        self.plan = diagupload.Plan(self.state, self.t0)

    def due(self, t, **kw):
        args = dict(enabled=True, keyed=False, metered=False, logged_since=0.0)
        args.update(kw)
        return self.plan.due(t, **args)

    def test_a_fault_waits_to_settle_then_goes(self):
        self.plan.note([("over-aborted", "time-out", self.t0)])
        self.assertEqual(self.due(self.t0 + 10), "")
        self.assertEqual(self.due(self.t0 + diagupload.SETTLE_S), "fault")

    def test_at_most_one_fault_report_per_30_minutes(self):
        self.plan.note([("over-aborted", "a", self.t0)])
        t = self.t0 + 61
        self.assertEqual(self.due(t), "fault")
        self.plan.sent(t, "fault", "SHACK-AAAA", "over-aborted")
        self.plan.taken()
        self.plan.note([("rig-link-lost", "b", t + 60)])
        self.assertEqual(self.due(t + 600), "")
        self.assertEqual(self.due(t + diagupload.DEBOUNCE_S - 1), "")
        self.assertEqual(self.due(t + diagupload.DEBOUNCE_S), "fault")

    def test_daily_only_when_something_new_was_logged(self):
        t = self.t0 + diagupload.FIRST_DAILY_S
        self.assertEqual(self.due(t, logged_since=t - 5), "daily")
        self.plan.sent(t, "daily", "SHACK-BBBB", "daily")
        self.assertEqual(self.due(t + diagupload.DAILY_S, logged_since=t - 1), "")       # nothing new since
        self.assertEqual(self.due(t + diagupload.DAILY_S - 10, logged_since=t + 100), "")  # not a day yet
        self.assertEqual(self.due(t + diagupload.DAILY_S, logged_since=t + 100), "daily")

    def test_never_while_keyed_metered_or_off(self):
        self.plan.note([("over-failed", "x", self.t0)])
        t = self.t0 + diagupload.FIRST_DAILY_S
        self.assertEqual(self.due(t, keyed=True), "")
        self.assertEqual(self.due(t, metered=True), "")
        self.assertEqual(self.due(t, enabled=False), "")
        self.assertEqual(self.due(t), "fault")               # put off, not dropped

    def test_a_failure_backs_off_and_keeps_the_fault(self):
        ev = [("crash", "boom", self.t0)]
        self.plan.note(ev)
        self.plan.taken()
        self.plan.failed(self.t0 + 100, "fault", "offline", ev)
        self.assertEqual(self.due(self.t0 + 200), "")
        self.assertEqual(self.due(self.t0 + 100 + diagupload.RETRY_S), "fault")
        self.plan.failed(self.t0 + 100 + diagupload.RETRY_S, "fault", "offline", self.plan.taken())
        self.assertEqual(self.state["failures"], 2)
        self.assertEqual(self.state["retryAt"], self.t0 + 100 + 3 * diagupload.RETRY_S)

    def test_the_install_id_is_random_and_kept(self):
        a = self.state.install_id()
        self.assertRegex(a, r"^[0-9a-f]{32}$")
        self.assertEqual(diagupload.State(self.tmp / "diag-upload.json").install_id(), a)
        other = diagupload.State(Path(tempfile.mkdtemp()) / "diag-upload.json").install_id()
        self.assertNotEqual(a, other)

    def test_consent_is_for_this_consent_text_only(self):
        self.assertFalse(diagupload.consented(""))
        self.assertFalse(diagupload.consented(True))
        self.assertFalse(diagupload.consented(f"{diagupload.CONSENT_VERSION + 1}@2026-10-12T00:00:00Z"))
        self.assertTrue(diagupload.consented(diagupload.consent_stamp()))


class Triggers(unittest.TestCase):
    def setUp(self):
        self.w = diagupload.Watcher().install()

    def tearDown(self):
        self.w.remove()

    def test_notable_and_uncaught_thread_exceptions_are_heard(self):
        setup = diag.start_logging("openhamshack-test", Path(tempfile.mkdtemp()), console=False)
        try:
            diag.notable("rig-link-lost", "no answer")

            def boom():
                raise RuntimeError("worker died")
            t = threading.Thread(target=boom)
            t.start()
            t.join()
        finally:
            setup.stop()
        got = [k for k, _d, _t in self.w.take()]
        self.assertEqual(got, ["rig-link-lost", "crash"])
        self.assertEqual(self.w.take(), [])

    def test_an_engine_unkey_that_the_operator_did_not_ask_for_is_a_fault(self):
        from helpers import make_radio
        r = make_radio(tempfile.mkdtemp())
        with r.lock:
            r.st["keyed"] = True
        r._unkey("Unkeyed: transmit time-out (120 s)", "warn")
        with r.lock:
            r.st["keyed"] = True
        r._unkey("", None)                      # Escape / a normal stop: not a fault
        got = self.w.take()
        self.assertEqual([k for k, _d, _t in got], ["over-aborted"])
        self.assertIn("time-out", got[0][1])

    def test_the_9700_link_going_from_ok_to_lost_is_a_fault(self):
        from ohsnb.extrig import ExternalTx
        r = mock.MagicMock()
        r.st = {"rigLink": "ok", "keyed": False, "rigCatPtt": False}
        ext = ExternalTx.__new__(ExternalTx)
        ext.radio = r
        ext.plan = mock.MagicMock(problem=lambda: "")
        ext.link = mock.MagicMock()
        ext.cat = mock.MagicMock(owed=False)
        try:
            ext.report({"link": "lost", "error": "no answer from the IC-9700"})
        except Exception:  # noqa: BLE001 - only the trigger, logged before the status, matters here
            pass
        self.assertIn("rig-link-lost", [k for k, _d, _t in self.w.take()])


class OverHttp(unittest.TestCase):
    def setUp(self):
        self.site = FakeSite()

    def tearDown(self):
        self.site.close()

    def test_post_sends_gzip_with_app_version_install_and_returns_the_code(self):
        body = gzip.compress(b'{"schema": 1}')
        code = diagupload.post(self.site.url, body, app="nb", version="0.1.18", install="a" * 32)
        self.assertEqual(code, "SHACK-7KQ4")
        p = self.site.posts[0]
        self.assertEqual(p["query"], {"app": "nb", "version": "0.1.18", "install": "a" * 32})
        self.assertEqual(p["type"], "application/gzip")
        self.assertEqual(p["body"], body)

    def test_a_refusal_is_an_upload_error_with_the_sites_reason(self):
        self.site.status, self.site.error = 429, "too many reports from this installation today"
        with self.assertRaisesRegex(diagupload.UploadError, "429: too many reports"):
            diagupload.post(self.site.url, b"x", app="nb", version="0.1.18", install="a" * 32)

    def test_nobody_listening_is_an_upload_error(self):
        from test_update import closed_port_url
        with self.assertRaises(diagupload.UploadError):
            diagupload.post(closed_port_url() + "upload.php", b"x", app="nb", version="1", install="a" * 32,
                            timeout=3)


# ------------------------------------------------------------------ the window
@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class InTheWindow(WindowCase):
    def setUp(self):
        super().setUp()
        self.site = FakeSite()
        self.clock = Clock()
        self.metered = False

    def tearDown(self):
        self.site.close()
        super().tearDown()

    def controller(self, win, **kw):
        from ohscore.ui.diagsend import DiagSendController
        args = dict(url=self.site.url, clock=self.clock, metered=lambda: self.metered, timeout=5,
                    state_path=Path(self.tmp) / "diag-upload.json")
        args.update(kw)
        win.diagsend.stop()
        c = DiagSendController(win, **args)
        c.watcher.install()
        self.addCleanup(c.watcher.remove)
        win.diagsend = c
        return c

    def consent(self, win):
        win.prefs["diagUpload"] = True
        win.prefs["diagUploadConsent"] = diagupload.consent_stamp()

    def wait(self, cond, timeout=20.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def fault_then_settle(self, c, trigger="over-aborted"):
        diag.notable(trigger, "test fault")
        self.clock.t += diagupload.SETTLE_S + 1
        return c.tick()

    def test_off_by_default_and_nothing_sent(self):
        win, _b, _r = self.window()
        self.assertFalse(win.prefs["diagUpload"])
        c = self.controller(win)
        self.assertFalse(c.enabled())
        self.assertEqual(self.fault_then_settle(c), "")
        self.clock.t += 2 * diagupload.DAILY_S
        self.assertEqual(c.tick(), "")
        self.app.processEvents()
        self.assertEqual(self.site.posts, [])

    def test_the_switch_alone_is_not_consent(self):
        win, _b, _r = self.window()
        win.prefs["diagUpload"] = True               # e.g. ui.json edited by hand
        c = self.controller(win)
        self.assertFalse(c.enabled())
        self.assertEqual(self.fault_then_settle(c), "")
        self.assertEqual(self.site.posts, [])

    def test_turning_it_on_in_settings_records_consent_and_off_clears_it(self):
        win, _b, _r = self.window()
        d = win.settings_dialog()
        self.assertFalse(d.diag_toggle.on)
        d.diag_toggle.set_on(True)
        d.save()
        self.assertTrue(win.prefs["diagUpload"])
        self.assertTrue(diagupload.consented(win.prefs["diagUploadConsent"]))
        self.assertTrue(win.diagsend.enabled())
        d = win.settings_dialog()
        self.assertTrue(d.diag_toggle.on)
        d.diag_toggle.set_on(False)
        d.save()
        self.assertFalse(win.prefs["diagUpload"])
        self.assertEqual(win.prefs["diagUploadConsent"], "")

    def test_a_fault_sends_a_report_with_its_trigger_and_shows_the_code(self):
        win, _b, _r = self.window()
        self.consent(win)
        c = self.controller(win)
        self.assertEqual(self.fault_then_settle(c, "no-power-out"), "fault")
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(len(self.site.posts), 1)
        doc = self.site.doc()
        self.assertEqual(doc["trigger"], "no-power-out")
        self.assertEqual(doc["app"], "nb")
        self.assertIn("diagnostics report", doc["report"])
        self.assertEqual(self.site.posts[0]["query"]["install"], c.state.install_id())
        self.assertEqual(c.state["lastCode"], "SHACK-7KQ4")
        d = c.open_dialog()
        self.assertIn("SHACK-7KQ4", d.status.text())

    def test_faults_within_30_minutes_make_one_report(self):
        win, _b, _r = self.window()
        self.consent(win)
        c = self.controller(win)
        self.fault_then_settle(c)
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(self.fault_then_settle(c, "rig-link-lost"), "")
        self.clock.t += 20 * 60
        self.assertEqual(c.tick(), "")
        self.clock.t += 10 * 60
        self.assertEqual(c.tick(), "fault")
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(len(self.site.posts), 2)
        self.assertEqual(self.site.doc()["trigger"], "rig-link-lost")

    def test_nothing_is_sent_while_keyed_and_it_goes_after(self):
        win, _b, radio = self.window()
        self.consent(win)
        c = self.controller(win)
        real = radio.state
        with mock.patch.object(radio, "state", lambda: {**real(), "keyed": True}):
            self.assertEqual(self.fault_then_settle(c), "")
            self.assertFalse(c.send("manual"))
        self.app.processEvents()
        self.assertEqual(self.site.posts, [])
        self.assertEqual(c.tick(), "fault")
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(len(self.site.posts), 1)

    def test_nothing_automatic_on_a_metered_connection(self):
        win, _b, _r = self.window()
        self.consent(win)
        c = self.controller(win)
        self.metered = True
        self.assertEqual(self.fault_then_settle(c), "")
        self.metered = False
        self.assertEqual(c.tick(), "fault")

    def test_send_now_works_with_automatic_sending_off(self):
        win, _b, _r = self.window()
        c = self.controller(win)
        self.assertFalse(c.enabled())
        d = c.open_dialog()
        self.assertIn("Automatic sending is off", d.auto.text())
        self.assertIn("callsign", d.summary.text())
        self.assertIn("30 days", d.summary.text())
        d.btn_send.clicked.emit()
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(self.site.doc()["kind"], "manual")
        self.assertIn("SHACK-7KQ4", d.status.text())

    def test_a_failed_upload_leaves_the_radio_running_and_retries_later(self):
        win, _b, radio = self.window()
        self.consent(win)
        c = self.controller(win)
        self.site.status, self.site.error = 503, "storage full"
        self.assertEqual(self.fault_then_settle(c), "fault")
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertIn("storage full", c.last_error)
        self.assertTrue(radio.state()["running"])
        self.assertEqual(self.errors, [])
        self.site.status = 200
        self.assertEqual(c.tick(), "")                     # backing off
        self.clock.t += diagupload.RETRY_S
        self.assertEqual(c.tick(), "fault")                # the same fault, kept
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertEqual(self.site.doc()["trigger"], "over-aborted")

    def test_a_poster_that_raises_anything_never_reaches_the_window(self):
        win, _b, radio = self.window()
        self.consent(win)

        def broken(*a, **k):
            raise ValueError("a bug in the uploader")
        c = self.controller(win, poster=broken)
        self.assertEqual(self.fault_then_settle(c), "fault")
        self.assertTrue(self.wait(lambda: not c.sending))
        self.assertIn("something went wrong", c.last_error)
        self.assertTrue(radio.state()["running"])
