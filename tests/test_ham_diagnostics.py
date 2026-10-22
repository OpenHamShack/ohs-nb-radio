"""What OpenHamShack HAM adds to the shared diagnostics report
(ohsradio/diagnostics.py): the Pluto's identity and the fix's verdict, found
even when the radio cannot be opened, and secrets kept out by shape as
well as by name (ohscore.diag.redact). Against a pretend Pluto; nothing
reaches a real radio and nothing leaves the machine."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import time
import unittest
from unittest import mock

from pluto_fakes import Pluto
from ohscore import diag
from ohsradio import diagnostics, plutofix

SECRET_CFG = {
    "callsign": "GM4BRI", "locator": "IO85", "plutoUri": "ip:192.168.2.1", "vfo": 145500000.0,
    "qrzApiKey": "ABCD-1234-EFGH-5678",
    "clublog": {"password": "hunter2", "email": "op@example.org"},
    "uploads": [{"token": "t0k3n-value"}],
    "notes": "my key is sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
    "deploy": "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
    "sshKey": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----",
    "serial": "1044734c9605000d15003300deb64fb9ce",
}
SECRETS = ("ABCD-1234-EFGH-5678", "hunter2", "t0k3n-value", "sk-ant-api03", "ghp_aBcDeF", "b3BlbnNzaC1r")


class Redaction(unittest.TestCase):
    def test_secrets_go_by_key_name_and_by_shape_and_the_radio_facts_stay(self):
        red = diag.redact(SECRET_CFG)
        out = json.dumps(red)
        for s in SECRETS:
            self.assertNotIn(s, out)
        for k in ("callsign", "locator", "plutoUri", "vfo", "serial"):
            self.assertEqual(red[k], SECRET_CFG[k], k)
        self.assertEqual(red["clublog"]["email"], "op@example.org")


class Hangs:
    """libiio on a dead address of a live subnet: the open never returns."""
    version = (0, 26, "v0.26")

    @staticmethod
    def Context(uri):
        time.sleep(30)


class PlutoFindings(unittest.TestCase):
    def test_a_pluto_that_will_not_open_is_reported_within_the_deadline(self):
        from ohscore.devices import pluto
        t0 = time.monotonic()
        with mock.patch.object(pluto, "import_iio", return_value=Hangs):
            lines = diagnostics.pluto_findings("ip:192.0.2.1", timeout_s=0.5)
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertIn("address: ip:192.0.2.1", lines)
        self.assertTrue(any(x.startswith("reachable: no") for x in lines), lines)

    def test_a_stock_pluto_reports_its_identity_range_and_the_fix(self):
        radio = Pluto(fw="v0.38")
        lines = diagnostics.pluto_findings("ip:192.168.2.1", identify=radio.identify)
        for want in ("reachable: yes", "firmware: v0.38", "ad9361-phy model: ad9363",
                     "tuning range: 325-3800 MHz", "AD9364 fix: compatible", "hw_serial: 104473dc5996000c0d00",
                     "out of reach: 2 m"):
            self.assertIn(want, lines)

    def test_unsupported_firmware_says_manual_only(self):
        radio = Pluto(fw="tezuka-v0.3.21")
        lines = diagnostics.pluto_findings("ip:192.168.2.1", identify=radio.identify)
        self.assertTrue(any(x.startswith("AD9364 fix: manual only") for x in lines), lines)

    def test_the_findings_reach_the_shared_report(self):
        radio = Pluto(fw="v0.38")

        class Engine:
            cfg = {"device": "pluto", "plutoUri": "ip:192.168.2.1"}
            dev = None
        with mock.patch.object(diagnostics, "discovery", return_value=["Pluto: none found", "HL2: none found"]):
            more = diagnostics.findings(Engine(), identify=radio.identify)
        report = diag.build_report({"app": "OpenHamShack HAM"}, {"device": "pluto"}, extra=more)
        self.assertIn("  Pluto: none found", report)
        self.assertIn("  ad9361-phy model: ad9363", report)
        self.assertIn("  AD9364 fix: compatible", report)

    def test_the_open_device_is_preferred_over_a_new_connection(self):
        class Dev:
            kind, uri, model, serial, fw_version, identity, fir = ("pluto", "ip:192.168.2.1", "PlutoSDR", "1044",
                                                                    "v0.38", "ad9364", "not needed")

        def never(uri):
            raise AssertionError("probed although the radio is open")
        lines = diagnostics.pluto_findings("ip:192.168.2.1", Dev(), identify=never)
        self.assertIn("read from: the open radio", lines)
        self.assertIn("FIR: not needed", lines)
        self.assertFalse(any(x.startswith("out of reach") for x in lines))
        self.assertIsNotNone(plutofix.from_device(Dev()))


if __name__ == "__main__":
    unittest.main()
