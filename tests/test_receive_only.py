"""--receive-only (ohscore/config.py RECEIVE_ONLY): a run that cannot
transmit, whatever is asked of it, by the engine's one existing refusal
for a device that cannot transmit - and a normal run unchanged beside it.
NB's simulator is the device: it can transmit, so a refusal here is the
flag's doing and not the device's."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import contextlib
import io
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import make_radio, noise_audio, run_sim
from ohscore.config import RECEIVE_ONLY, RECEIVE_ONLY_REFUSAL, receive_only
from ohscore.engine import TxRefused

# Where test_radio's digital-mode PTT test keys: FT4 in the digimodes segment.
KEYABLE = dict(mode="ft4", vfo=10_489_545_000.0)


class ReceiveOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, rx_only):
        over = dict(KEYABLE)
        if rx_only:
            # What the command line does with the flag, on the dict it hands Radio.
            receive_only(over)
        r = make_radio(self.tmp, audio_source=noise_audio(), **over)
        self.radios.append(r)
        r.start()
        return r

    def test_receive_only_refuses_every_over_with_its_reason(self):
        r = self.radio(rx_only=True)
        st = r.state()
        self.assertFalse(st["canTx"])
        self.assertEqual(st["txBlocked"], RECEIVE_ONLY_REFUSAL)
        with self.assertRaisesRegex(TxRefused, r"^Started receive-only \(--receive-only\)"):
            r.ptt(True)
        run_sim(r, 0.2)
        self.assertFalse(r.state()["keyed"])
        # Still receiving: the flag takes the transmitter, nothing else.
        self.assertTrue(r.state()["running"])

    def test_the_transmit_card_says_receive_only_not_unchecked(self):
        # With no licence class the card used to say "transmitting is not
        # refused" - untrue in a run that refuses every over.
        over = {}
        receive_only(over)
        r = make_radio(self.tmp, audio_source=noise_audio(), **over)
        self.radios.append(r)
        r.start()
        run_sim(r, 0.2)
        warning = r.state()["txWarning"]
        self.assertEqual(warning.get("text"), RECEIVE_ONLY_REFUSAL)
        self.assertNotIn("not refused", warning.get("text") or "")

    def test_a_normal_start_still_keys(self):
        r = self.radio(rx_only=False)
        self.assertTrue(r.state()["canTx"])
        r.ptt(True)
        run_sim(r, 0.2)
        self.assertTrue(r.state()["keyed"])
        r.ptt(False)

    def test_survives_a_restart_and_is_never_saved(self):
        # Settings › Radio restarts the engine on a fresh device object:
        # the flag is the run's, not the first device's.
        r = self.radio(rx_only=True)
        r.stop()
        r.start()
        with self.assertRaisesRegex(TxRefused, "--receive-only"):
            r.ptt(True)
        self.assertNotIn(RECEIVE_ONLY, r.cfg)


class CommandLine(unittest.TestCase):
    def test_keyed_diagnostic_and_receive_only_are_refused_together(self):
        from ohsnb import __main__ as nb_main
        err = io.StringIO()
        # Refused before logging, config or any radio: nothing to open.
        with mock.patch.object(nb_main.diag, "start_logging", side_effect=AssertionError("got as far as logging")), \
                contextlib.redirect_stderr(err):
            code = nb_main.main(["--rig-diagnostic", "--keyed", "--i-have-a-dummy-load-and-operator-present",
                                 "--receive-only"])
        self.assertEqual(code, 2)
        self.assertIn("--receive-only", err.getvalue())

    def test_the_flag_reaches_the_radio(self):
        # Both apps: the dict handed to Radio carries the flag, and the
        # radio's engine takes it.
        for mod_name in ("ohsnb.__main__", "ohsradio.__main__"):
            with self.subTest(app=mod_name):
                import importlib
                mod = importlib.import_module(mod_name)
                seen = {}

                class Stop(Exception):
                    pass

                def fake_radio(cfg, **_kw):
                    seen.update(cfg)
                    raise Stop

                with mock.patch.object(mod, "Radio", fake_radio), \
                        mock.patch.object(mod.diag, "record_facts"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    a = mock.Mock(device="sim", no_audio=True, receive_only=True, server=False, headless=True,
                                  rig_diagnostic=None, band=None, rf=None, mode=None)
                    with self.assertRaises(Stop):
                        mod._run(a)
                self.assertTrue(seen.get(RECEIVE_ONLY))


if __name__ == "__main__":
    unittest.main()
