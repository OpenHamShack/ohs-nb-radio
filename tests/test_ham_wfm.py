"""Wide FM in Radio's engine (ohsradio/radio.py, ohscore/dsp/wfm.py): a
broadcast station heard through the engine's own channel at the RSPdx's and
the Pluto's rates, the passband reported in state, the de-emphasis setting,
the refusal on a receiver too slow for it (the emulated Hermes-Lite 2), and
transmit refused in it everywhere, before the licence is asked."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from ohscore.audio import NullAudio
from ohscore.devices.hl2sim import HL2Sim
from ohscore.engine import TxRefused
from ohsradio.radio import Radio

from ham_helpers import close, make_radio, pump
from listen_helpers import Station, make_listener, tone_snr

STATION = 97_700_000.0
SAYS = "WFM is for listening only: nothing is ever transmitted in it"


def listen(r, audio, seconds=1.5):
    """Audio heard for `seconds` once the dial's re-centring has settled."""
    pump(r, 10, until=lambda: r._rx_settled())
    pump(r, 0.3)
    audio.take()
    pump(r, 30, until=lambda: sum(len(c) for c in audio.chunks) >= seconds * 12_000)
    return audio.take()


class HearsABroadcastStation(unittest.TestCase):
    def check(self, fs):
        r, audio, _dev = make_listener([Station(STATION, "wfm")], fs=fs, vfo=STATION, mode="wfm")
        self.addCleanup(close, r)
        r.start()
        a = listen(r, audio)
        peak, snr = tone_snr(a[1200:], 1000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=5)
        self.assertGreater(snr, 30.0)
        # The channel is the bank's 240 kS/s one at either rate.
        self.assertEqual(r.wfm_ch.rate, 240_000.0)
        return r, audio

    def test_at_the_rspdx_rate(self):
        self.check(2_400_000.0)

    def test_at_the_pluto_rate(self):
        self.check(1_200_000.0)

    def test_a_station_off_the_dial_is_not_heard(self):
        # Two channels up, the dial hears noise: the 180 kHz filter is real.
        r, audio, _dev = make_listener([Station(STATION + 400_000.0, "wfm")], vfo=STATION, mode="wfm")
        self.addCleanup(close, r)
        r.start()
        _peak, snr = tone_snr(listen(r, audio)[1200:], 1000.0)
        self.assertLess(snr, 0.0)


class ReportsItsPassband(unittest.TestCase):
    def setUp(self):
        self.r = make_radio()
        self.addCleanup(close, self.r)

    def test_wfm_reports_the_180_khz_channel(self):
        self.r.set(mode="wfm", vfo=STATION)
        st = self.r.state()
        self.assertEqual((st["rxFilterLo"], st["rxFilterHi"]), (-90_000.0, 90_000.0))

    def test_every_other_mode_reports_what_its_demodulator_uses(self):
        self.r.set(mode="usb", filterLo=200.0, filterHi=2800.0)
        self.assertEqual((self.r.state()["rxFilterLo"], self.r.state()["rxFilterHi"]), (200.0, 2800.0))
        self.r.set(mode="am", amWidth=4500.0)
        self.assertEqual((self.r.state()["rxFilterLo"], self.r.state()["rxFilterHi"]), (-4500.0, 4500.0))

    def test_the_catalogue_offers_it_to_listen_never_to_send(self):
        self.r.start()
        self.assertEqual(self.r.state()["modes"]["wfm"], {"decode": True, "encode": False, "missing": ""})


class Deemphasis(unittest.TestCase):
    def test_50_us_by_default_and_75_as_a_setting(self):
        r, _audio, _dev = make_listener([Station(STATION, "wfm")], vfo=STATION, mode="wfm")
        self.addCleanup(close, r)
        self.assertEqual(r.state()["wfmDeemphasis"], 50.0)
        r.start()
        pump(r, 0.5)
        self.assertEqual(r.wfmdemod.tau_us, 50.0)
        r.set(wfmDeemphasis=75.0)
        pump(r, 5, until=lambda: r.wfmdemod.tau_us == 75.0)
        self.assertEqual(r.wfmdemod.tau_us, 75.0)
        with self.assertRaises(ValueError):
            r.set(wfmDeemphasis=60.0)


class NeverTransmitted(unittest.TestCase):
    """In a band and a class that would allow FM, wide FM is still refused:
    the refusal is the mode's, before the licence is asked."""

    def setUp(self):
        self.r = make_radio(licenceClass="full")
        self.addCleanup(close, self.r)
        self.r.start()
        self.r.set(mode="fm", vfo=145_500_000.0)
        self.assertEqual(self.r.state()["txBlocked"], "")         # FM here keys for a Full licence

    def test_ptt_is_refused(self):
        self.r.set(mode="wfm")
        self.assertEqual(self.r.state()["txBlocked"], SAYS)
        with self.assertRaises(TxRefused) as e:
            self.r.ptt(True)
        self.assertEqual(str(e.exception), SAYS)
        pump(self.r, 0.3)
        self.assertFalse(self.r.state()["keyed"])
        self.assertEqual(self.r.dev.drive, 0.0)

    def test_send_and_tune_are_refused(self):
        self.r.set(mode="wfm")
        with self.assertRaises(TxRefused):
            self.r.send("wfm", text="CQ")
        with self.assertRaises(TxRefused):
            self.r.tune(True)
        pump(self.r, 0.3)
        self.assertFalse(self.r.state()["keyed"])


class TooSlowAReceiver(unittest.TestCase):
    """A Hermes-Lite 2 (emulated, on 127.0.0.1) at 48 kS/s cannot hold a
    180 kHz channel: wfm is refused with the sentence, before and after the
    radio opens, and the catalogue says the same. At 384 kS/s it can."""

    def radio(self, rate):
        sim = HL2Sim(tone_hz=14_080_000.0, tone_level=0.05).start()
        self.addCleanup(sim.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "hl2", "hl2Address": sim.address, "hl2Rate": rate, "audioBackend": "null",
               "vfo": 14_074_000.0, "mode": "usb", "callsign": "GM4BRI", "licenceClass": "full"}
        r = Radio(cfg, persist=False, data_dir=tmp.name, audio=NullAudio(realtime=True))
        self.addCleanup(r.stop)
        return r

    def test_48_ks_refuses_it_with_the_reason(self):
        r = self.radio(48_000)
        says = "Wide FM needs the receiver to run at 240 kS/s or more, and the hl2 runs at 48 kS/s"
        with self.assertRaises(ValueError) as e:
            r.set(mode="wfm")
        self.assertEqual(str(e.exception), says)
        r.start()
        with self.assertRaises(ValueError):
            r.set(mode="wfm")
        self.assertEqual(r.state()["mode"], "usb")
        self.assertEqual(r.state()["modes"]["wfm"], {"decode": False, "encode": False, "missing": says})

    def test_384_ks_holds_it(self):
        r = self.radio(384_000)
        r.start()
        r.set(mode="wfm")
        self.assertEqual(r.state()["modes"]["wfm"]["missing"], "")
        self.assertEqual(r.wfm_ch.rate, 384_000.0)



class DesktopTuning(unittest.TestCase):
    """The window's click-to-tune and default step in wfm: a click on a
    broadcast station lands on the 50 kHz raster it sits on, and the
    arrows step a 100 kHz channel."""

    def test_a_click_lands_on_the_station(self):
        from ohscore.ui.tuning import DEFAULT_STEP, click_to_dial
        self.assertEqual(click_to_dial("wfm", 97_712_400.0, {}), 97_700_000.0)
        self.assertEqual(click_to_dial("wfm", 95_046_000.0, {}), 95_050_000.0)
        self.assertEqual(DEFAULT_STEP["wfm"], 100_000)

    def test_nb_never_offers_it(self):
        from ohscore import modegroups
        from ohsnb import state as nb_state
        self.assertNotIn("wfm", [m for _g, ms in modegroups.groups(nb_state.MODES) for m in ms])


if __name__ == "__main__":
    unittest.main()
