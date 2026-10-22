"""The Pluto's chip identity and the AD9364 fix (ohsradio/plutofix.py),
against a pretend radio (tests/pluto_fakes.py): its IIO context reports
whatever its U-Boot environment says, and its shell edits that
environment and reboots. Each test checks what was sent to the radio and
what the radio says afterwards. No radio is touched."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import collections
import os
import unittest
from pathlib import Path

from pluto_fakes import Pluto, SshServer, fixer
from ohsradio import bands, plutofix

try:
    import paramiko  # noqa: F401
    HAVE_PARAMIKO = True
except ImportError:  # pragma: no cover - Debian: python3-paramiko
    HAVE_PARAMIKO = False

SETTERS = ("fw_setenv", "reboot")


def changes(radio):
    """The commands that changed something (the read-only look is left out)."""
    return [c for c in radio.commands if c.startswith(SETTERS)]


class Firmware(unittest.TestCase):
    def test_adi_versions_pick_their_method(self):
        self.assertEqual(plutofix.firmware_plan("v0.38").method, "compatible")
        self.assertEqual(plutofix.firmware_plan("v0.32").method, "compatible")
        self.assertEqual(plutofix.firmware_plan("v0.31").method, "attr")
        self.assertEqual(plutofix.firmware_plan("v0.26").method, "attr")

    def test_unknown_firmware_gets_no_method_and_a_reason(self):
        for fw in ("tezuka-v0.3.21", "", "v0.20", "v0.45", "plutoplus-1.2"):
            plan = plutofix.firmware_plan(fw)
            self.assertEqual(plan.method, "", fw)
            self.assertTrue(plan.reason, fw)

    def test_the_commands_are_adis(self):
        self.assertIn("fw_setenv compatible ad9364", [c for c, _ in plutofix.apply_commands("compatible")])
        old = [c for c, _ in plutofix.apply_commands("attr")]
        self.assertIn("fw_setenv attr_name compatible", old)
        self.assertIn("fw_setenv attr_val ad9364", old)
        self.assertEqual(plutofix.apply_commands(""), [])


class Bands(unittest.TestCase):
    def test_an_ad9363_reaches_70cm_but_not_2m_4m_or_6cm(self):
        reach = {b.name: not plutofix.out_of_reach("ad9363", b) for b in bands.BANDS}
        self.assertTrue(reach["70cm"])
        self.assertTrue(reach["23cm"])
        self.assertTrue(reach["13cm"])
        for name in ("2m", "4m", "6cm"):
            self.assertFalse(reach[name], name)
        self.assertFalse(any(plutofix.out_of_reach("ad9364", b) for b in bands.BANDS))

    def test_only_an_ad9363_pluto_needs_the_setting(self):
        class Dev:
            kind, identity = "pluto", "ad9363"
        self.assertEqual(plutofix.needs_ad9364(Dev(), "2m").name, "2m")
        self.assertIsNone(plutofix.needs_ad9364(Dev(), "70cm"))
        self.assertEqual(plutofix.needs_ad9364(Dev(), f=145_500_000.0).name, "2m")
        Dev.identity = "ad9364"
        self.assertIsNone(plutofix.needs_ad9364(Dev(), "2m"))
        Dev.kind = "hl2"
        self.assertIsNone(plutofix.needs_ad9364(Dev(), "2m"))

    def test_foundation_check_lists_its_vhf_bands(self):
        radio = Pluto()
        checks, info = plutofix.check_radio("ip:192.168.2.1", "foundation", identify=radio.identify)
        by = {c.label: c for c in checks}
        self.assertEqual(by["Reachable"].level, "ok")
        self.assertEqual(by["Chip identity"].level, "warn")
        self.assertEqual(by["2 m"].level, "fail")
        self.assertEqual(by["70 cm"].level, "ok")
        self.assertEqual(info.fw_version, "v0.38")
        self.assertFalse(any(c.label == "20 m" for c in checks))      # HF is the HL2's, not listed


class Fix(unittest.TestCase):
    def test_apply_on_current_firmware(self):
        radio = Pluto(fw="v0.38")
        f = fixer(radio)
        info, plan, cmds, why = f.preview()
        self.assertEqual(info.identity, "ad9363")
        self.assertEqual(changes(radio), [])                       # looking changes nothing
        res = f.run()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(changes(radio), ["fw_setenv compatible ad9364", "reboot"])
        self.assertEqual(radio.reboots, 1)
        self.assertEqual(res.identity, "ad9364")
        self.assertEqual(radio.identify("ip:192.168.2.1").identity, "ad9364")
        self.assertIn("AD9364", res.message)

    def test_apply_on_older_firmware_uses_attr_name_and_attr_val(self):
        radio = Pluto(fw="v0.30")
        res = fixer(radio).run()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(changes(radio), ["fw_setenv attr_name compatible", "fw_setenv attr_val ad9364", "reboot"])

    def test_wrong_password_then_the_right_one(self):
        radio = Pluto(password="s3cret")
        asked = []

        def ask():
            asked.append(1)
            return "s3cret"
        res = fixer(radio).run(ask_password=ask)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(asked, [1])                               # asked once, after the default failed
        self.assertEqual(radio.logins, ["analog", "s3cret"])

    def test_a_password_refused_twice_changes_nothing(self):
        radio = Pluto(password="s3cret")
        res = fixer(radio).run(ask_password=lambda: "wrong")
        self.assertFalse(res.ok)
        self.assertIn("refused the password", res.message)
        self.assertEqual(radio.commands, [])
        self.assertTrue(res.manual)

    def test_cancelling_the_password_changes_nothing(self):
        radio = Pluto(password="s3cret")
        res = fixer(radio).run(ask_password=lambda: None)
        self.assertFalse(res.ok)
        self.assertEqual(radio.commands, [])

    def test_the_radio_not_coming_back_times_out_with_a_sentence(self):
        radio = Pluto(down_polls=None)
        now = [0.0]

        def sleep(s):
            now[0] += max(s, 1.0)
        res = fixer(radio, sleep=sleep, clock=lambda: now[0], reboot_timeout_s=30.0).run()
        self.assertFalse(res.ok)
        self.assertIn("did not answer", res.message)
        self.assertIn("30 s", res.message)
        self.assertIn("reboot", res.ran)
        self.assertLess(now[0], 40.0)

    def test_unsupported_firmware_shows_manual_steps_and_runs_nothing(self):
        radio = Pluto(fw="tezuka-v0.3.21")
        res = fixer(radio).run()
        self.assertFalse(res.ok)
        self.assertEqual(radio.commands, [])
        self.assertEqual(radio.logins, [])                          # never even logged in
        self.assertIn("fw_setenv compatible ad9364", res.manual)
        self.assertIn("tezuka", res.message)

    def test_a_usb_only_radio_is_explained_and_nothing_is_run(self):
        radio = Pluto()
        res = fixer(radio, uri="usb:1.4.5").run()
        self.assertFalse(res.ok)
        self.assertIn("network link", res.message)
        self.assertEqual(radio.logins, [])
        self.assertIn("ssh root@192.168.2.1", res.manual)

    def test_undo_returns_it_to_ad9363(self):
        radio = Pluto(fw="v0.38")
        self.assertTrue(fixer(radio).run().ok)
        radio.commands.clear()
        res = fixer(radio).run(undo=True)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.identity, "ad9363")
        self.assertNotIn("compatible", radio.env)
        self.assertIn("fw_setenv compatible", changes(radio))

    def test_undo_also_clears_a_setting_made_the_old_way(self):
        radio = Pluto(fw="v0.38", env={"attr_name": "compatible", "attr_val": "ad9364"})
        radio.booted_env = dict(radio.env)
        self.assertEqual(radio.identity(), "ad9364")
        self.assertTrue(fixer(radio).run(undo=True).ok)
        self.assertEqual(radio.env, {})

    def test_already_set_runs_nothing(self):
        radio = Pluto(env={"compatible": "ad9364"})
        radio.booted_env = dict(radio.env)
        res = fixer(radio).run()
        self.assertTrue(res.ok)
        self.assertEqual(radio.commands, [])

    def test_a_radio_that_ignores_the_setting_says_so(self):
        radio = Pluto(fw="v0.38")
        radio.identity = lambda: "ad9363"
        res = fixer(radio).run()
        self.assertFalse(res.ok)
        self.assertIn("still reports AD9363", res.message)


class _Attr:
    def __init__(self):
        self.value = "0"


class _Node:
    """Any device or channel: every attribute and channel exists."""

    def __init__(self):
        self.attrs = collections.defaultdict(_Attr)
        self.chans = {}
        self.enabled = False
        self._device = None

    def find_channel(self, name, output=False):
        return self.chans.setdefault((name, output), _Node())

    def set_kernel_buffers_count(self, n):
        pass


class _Iio:
    def __init__(self, attrs):
        self.attrs = attrs

    def Context(self, uri):
        ctx = _Node()
        ctx.attrs = dict(self.attrs)
        devs = {n: _Node() for n in ("ad9361-phy", "cf-ad9361-lpc", "cf-ad9361-dds-core-lpc")}
        ctx.find_device = devs.get
        return ctx

    @staticmethod
    def Buffer(dev, n, cyclic):
        return object()


class OpenDevice(unittest.TestCase):
    """What ohscore's PlutoDevice records at open() and the chip check reads."""

    def open(self, **attrs):
        from unittest import mock
        from ohscore.devices import pluto
        base = {"hw_model": "Analog Devices PlutoSDR Rev.B (Z7010-AD9363)", "hw_serial": "104473dc",
                "fw_version": "v0.38"}
        base.update(attrs)
        d = pluto.PlutoDevice("ip:192.168.2.1", fs=2_400_000.0)
        with mock.patch.object(pluto, "import_iio", return_value=_Iio(base)):
            d.open()
        return d

    def test_open_records_firmware_serial_and_identity(self):
        d = self.open(**{"ad9361-phy,model": "ad9363"})
        st = d.status()
        self.assertEqual((st["fwVersion"], st["serial"], st["identity"]), ("v0.38", "104473dc", "ad9363"))
        self.assertEqual(d.rx_range, (325e6, 3.8e9))
        info = plutofix.from_device(d)
        self.assertEqual((info.fw_version, info.identity), ("v0.38", "ad9363"))
        self.assertEqual(plutofix.needs_ad9364(d, "2m").name, "2m")

    def test_an_ad9364_pluto_needs_nothing(self):
        d = self.open(**{"ad9361-phy,model": "ad9364"})
        self.assertIsNone(plutofix.needs_ad9364(d, "2m"))


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko is not installed (Debian: python3-paramiko)")
class OverRealSsh(unittest.TestCase):
    """ParamikoSession against a paramiko SSH server on 127.0.0.1."""

    def setUp(self):
        self.radio = Pluto(password="s3cret")
        self.server = SshServer(self.radio)
        port = self.server.port
        self.connect = lambda host, pw: plutofix.ParamikoSession.connect(host, pw, timeout_s=10.0, port=port)

    def tearDown(self):
        self.server.close()

    def test_wrong_then_right_password_sets_ad9364_and_writes_no_known_hosts(self):
        f = plutofix.Fixer("ip:127.0.0.1", connect=self.connect, identify=self.radio.identify,
                           sleep=lambda s: None, settle_s=0.0, poll_s=0.0)
        res = f.run(ask_password=lambda: "s3cret")
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.radio.logins, ["analog", "s3cret"])
        self.assertEqual(changes(self.radio), ["fw_setenv compatible ad9364", "reboot"])
        self.assertFalse((Path(os.path.expanduser("~")) / ".ssh" / "known_hosts").exists())

    def test_a_command_that_fails_stops_before_the_reboot(self):
        self.radio.password = "analog"
        execute = self.radio.execute
        self.radio.execute = lambda cmd: (1, "fw_setenv: cannot write\n") if cmd.startswith("fw_setenv") \
            else execute(cmd)
        res = plutofix.Fixer("ip:127.0.0.1", connect=self.connect, identify=self.radio.identify).run()
        self.assertFalse(res.ok)
        self.assertIn("cannot write", res.message)
        self.assertEqual(self.radio.reboots, 0)


if __name__ == "__main__":
    unittest.main()
