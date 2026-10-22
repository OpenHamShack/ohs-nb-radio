"""OpenHamShack NB on the shared converter list (ohsnb/converters.py): the LNB
setting and the IC-9700's upconverter LO and side became converter
choices, and a config from before must behave exactly as it did.

The migration proof compares against numbers taken from the code before
the change (commit 408b903, ohsnb/radio.py and ohsnb/extrig.py as they
were), on the simulator with beacon lock held and TX lock off so nothing
moves them: the receiver's tuning, the dial <-> IQ offset maps, the
Pluto's TX LO and aimed uplink, and where the IC-9700 is put and what it
reads back - for the old default LNB, two odd ones, and low- and
high-side upconverters.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from helpers import make_radio, noise_audio, run_sim, sim_cfg, wait_rx_lock
from ohscore import converters as cv
from ohscore.audio import NullAudio
from ohsnb import config
from ohsnb import converters as nbconv
from ohsnb.extrig import ExternalTx
from ohsnb.radio import Radio

VFO = 10_489_700_000.0

# Before: [rx_if, device rx_if, _off(10489.75 MHz), _dial_at(12345 Hz), Pluto TX LO, txUl], with
# rxCorr 0 and -1777.5 Hz, txCorr +1234 Hz.
BEFORE_RX = {
    (9_750_000_000.0, 0.0): [739746500.0, 739746500.0, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_750_000_000.0, -1777.5): [739744722.5, 739744722.5, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_750_100_000.0, 0.0): [739646500.0, 739646500.0, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_750_100_000.0, -1777.5): [739644722.5, 739644722.5, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_360_000_000.0, 0.0): [1129746500.0, 1129746500.0, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_360_000_000.0, -1777.5): [1129744722.5, 1129744722.5, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_749_987_654.0, 0.0): [739758846.0, 739758846.0, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
    (9_749_987_654.0, -1777.5): [739757068.5, 739757068.5, 3500.0, 10489758845.0, 2399970000.0, 2400201234.0],
}
# Before: [the IC-9700's frequency (want), where that lands (aim_dl), its USB on air, txUl] at
# dial 10489.612345 MHz with rigTxCorr -321 Hz.
BEFORE_RIG = {
    (1_104_000_000.0, "low", "23cm"): [1296112024, 10489612345.0, "usb", 2400112024.0],
    (3_696_200_000.0, "high", "23cm"): [1296087976, 10489612345.0, "lsb", 2400112024.0],
    (1_968_000_000.0, "low", "70cm"): [432112024, 10489612345.0, "usb", 2400112024.0],
}


def old_style(**over) -> dict:
    """A config as NB up to 0.1.6 wrote it: no converter keys at all."""
    cfg = sim_cfg(**over)
    for k in ("converters", "rxConverter", "txConverter", "rigTxConverter"):
        cfg.pop(k, None)
    return cfg


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_receive_and_the_pluto_transmit_exactly_as_before(self):
        for (lnb, corr), want in BEFORE_RX.items():
            with self.subTest(lnb=lnb, corr=corr):
                cfg = old_style(lnbLo=lnb, rxCorr=corr, vfo=VFO, mode="usb", simUlErrorHz=0.0, beaconMode="hold",
                                txLock=False, txCorr=1234.0)
                r = Radio(cfg, persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))
                self.assertEqual(nbconv.rx_converter(r.cfg).rx_offset, lnb)
                r.start()
                try:
                    run_sim(r, 0.3)
                    got = [r.rx_if, r.dev.rx_if, r._off(10_489_750_000.0), r._dial_at(12345.0)]
                    r.ptt(True)
                    run_sim(r, 0.4)
                    got += [r.dev.tx_lo, r.state()["txUl"]]
                    r.ptt(False)
                finally:
                    r.stop()
                for g, w in zip(got, want):
                    self.assertAlmostEqual(g, w, places=3)

    def test_the_ic9700_is_put_and_read_exactly_as_before(self):
        for (lo, side, band), want in BEFORE_RIG.items():
            with self.subTest(lo=lo, side=side):
                cfg = old_style(txRadio="civ", upconverterLo=lo, upconverterSide=side, rigIfBand=band,
                                vfo=10_489_612_345.0, rigTxCorr=-321.0)
                r = Radio(cfg, persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))
                r._derive()
                x = ExternalTx(r)
                got = [x.want(), x.aim_dl(x.want()), x.plan.on_air_mode("usb"), r.state()["txUl"]]
                self.assertEqual(got[0], want[0])
                self.assertAlmostEqual(got[1], want[1], places=3)
                self.assertEqual(got[2:], want[2:])
                c = nbconv.rig_converter(r.cfg)
                self.assertEqual((c.tx_offset, c.inverted, c.transmits, c.type), (lo, side == "high", True, cv.DOWN))

    def test_the_old_default_is_the_preset_and_the_fresh_default(self):
        notes = []
        cfg = config.clean(old_style(lnbLo=9_750_000_000.0), notes)
        self.assertEqual(cfg["rxConverter"], "QO-100: LNB 9750 MHz")
        self.assertEqual(cfg["converters"], nbconv.DEFAULT_LIST)
        self.assertEqual(config.defaults()["converters"], nbconv.DEFAULT_LIST)
        self.assertEqual(notes, [])
        self.assertNotIn("lnbLo", cfg)

    def test_an_odd_lnb_and_a_preset_upconverter_get_sensible_names(self):
        cfg = config.clean(old_style(lnbLo=9_749_987_654.0, upconverterLo=1_104_000_000.0, txRadio="civ"))
        self.assertEqual(cfg["rxConverter"], "QO-100: LNB 9749.987654 MHz")
        self.assertEqual(cfg["rigTxConverter"], "QO-100 uplink: 1296 MHz IF (LO 1104)")
        cfg = config.clean(old_style(upconverterLo=3_696_200_000.0, upconverterSide="high"))
        self.assertEqual(cfg["rigTxConverter"], "IC-9700 upconverter (LO 3696.2 MHz, high-side)")
        self.assertEqual(cfg["txConverter"], "")             # the Pluto path never inherits it

    def test_no_upconverter_lo_stays_no_converter_and_is_still_refused(self):
        cfg = config.clean(old_style(upconverterLo=None))
        self.assertEqual(cfg["rigTxConverter"], "")
        r = Radio(sim_cfg(), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))
        with self.assertRaisesRegex(ValueError, "Choose your upconverter"):
            r.set(authorise=True, txRadio="civ", civPort="COM5")

    def test_a_file_on_disk_migrates_and_saves_in_the_new_keys(self):
        p = Path(self.tmp) / "config.json"
        p.write_text(json.dumps({"lnbLo": 9_750_100_000.0, "upconverterLo": 1_968_000_000.0,
                                 "upconverterSide": "low", "rigIfBand": "70cm", "txRadio": "civ"}))
        cfg = config.load(p)
        config.save(cfg, p)
        saved = json.loads(p.read_text())
        self.assertNotIn("lnbLo", saved)
        self.assertNotIn("upconverterLo", saved)
        self.assertEqual(saved["rxConverter"], "QO-100: LNB 9750.1 MHz")
        self.assertEqual(saved["rigTxConverter"], "QO-100 uplink: 432 MHz IF (LO 1968)")
        self.assertEqual(config.load(p), cfg)                # and reads back the same

    def test_a_file_with_the_old_rxtx_key_loads_the_same_and_saves_use(self):
        # As NB 0.1.7-0.1.8 wrote it: converters with `rxtx`, before
        # `use` (07/10/2026). Same LNB, same upconverter, same numbers.
        p = Path(self.tmp) / "config.json"
        lnb = {"title": "QO-100: LNB 9750.1 MHz", "type": "down", "rxtx": False, "rxOffset": 9_750_100_000.0,
               "txOffset": 9_750_100_000.0, "inverted": False, "maxDriveDbm": None}
        up = {"title": "IC-9700 upconverter (LO 3696.2 MHz, high-side)", "type": "down", "rxtx": True,
              "rxOffset": 3_696_200_000.0, "txOffset": 3_696_200_000.0, "inverted": True, "maxDriveDbm": None}
        p.write_text(json.dumps({"converters": [lnb, up], "rxConverter": lnb["title"], "rigTxConverter": up["title"],
                                 "txRadio": "civ", "rigIfBand": "23cm"}))
        cfg = config.load(p)
        self.assertEqual(nbconv.rx_lo(cfg), 9_750_100_000.0)
        rig = nbconv.rig_converter(cfg)
        self.assertEqual((rig.use, rig.inverted), (cv.RXTX, True))
        self.assertEqual(rig.radio(2_400_112_024.0, tx=True), 1_296_087_976.0)    # BEFORE_RIG's high-side figure
        config.save(cfg, p)
        saved = json.loads(p.read_text())
        self.assertEqual([c["use"] for c in saved["converters"]], [cv.RX, cv.RXTX])
        self.assertFalse(any("rxtx" in c for c in saved["converters"]))
        self.assertEqual(config.load(p), cfg)

    def test_a_stored_uplink_preset_becomes_tx_only_and_transmits_the_same(self):
        # The list as NB 0.1.7-0.1.8 stored "+ QO-100": the uplink presets
        # RX/TX, which read "Down-converter" (Brian's screenshot, 07/10).
        # One edited by the operator, and one already given a use, stay.
        stored = [dict({k: v for k, v in c.to_dict().items() if k != "use"},
                       rxtx=c.title.startswith("QO-100 uplink")) for c in cv.QO100]
        stored[4]["maxDriveDbm"] = -10.0                       # the 432 one: a most drive added (still the preset)
        mine = dict(stored[5], title="QO-100 uplink: 144 MHz IF (LO 2256)", txOffset=2_256_100_000.0)
        stored[5] = mine                                         # the 144 one: its LO changed
        later = {"title": "Kept RX/TX", "use": "rxtx", "rxOffset": 1_104_000_000.0}
        cfg = dict(sim_cfg(), converters=stored + [later], txRadio="civ", rigIfBand="23cm",
                   rigTxConverter="QO-100 uplink: 1296 MHz IF (LO 1104)", rigTxCorr=-321.0, vfo=10_489_612_345.0)
        before = cv.Converter.from_dict(stored[3])
        r = Radio(dict(cfg), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))
        r._derive()
        uses = {c.title: c.use for c in cv.parse(r.cfg["converters"])}
        self.assertEqual([uses[c.title] for c in cv.QO100], [cv.RX, cv.RX, cv.RX, cv.TX, cv.TX, cv.RXTX])
        self.assertEqual(uses["Kept RX/TX"], cv.RXTX)
        after = nbconv.rig_converter(r.cfg)
        self.assertEqual(after.kind(), cv.UP)
        self.assertEqual(cv.find(r.cfg["converters"], "QO-100 uplink: 432 MHz IF (LO 1968)").max_drive_dbm, -10.0)
        for ul in (2_400_000_000.0, 2_400_112_024.0, 2_400_500_000.0):
            self.assertEqual(after.radio(ul, tx=True), before.radio(ul, tx=True))
        x = ExternalTx(r)
        self.assertEqual(x.want(), BEFORE_RIG[(1_104_000_000.0, "low", "23cm")][0])   # the IC-9700 where it was
        self.assertEqual(x.plan.on_air_mode("usb"), "usb")

    def test_hand_written_converters_win_over_the_old_keys(self):
        mine = [{"title": "Mine", "rxOffset": 9_750_050_000.0}]
        cfg = config.clean(dict(old_style(lnbLo=9_360_000_000.0), converters=mine, rxConverter="Mine"))
        self.assertEqual([c["title"] for c in cfg["converters"]], ["Mine"])
        self.assertEqual(nbconv.rx_lo(cfg), 9_750_050_000.0)

    def test_a_receive_converter_missing_from_the_list_falls_back_to_one_that_works(self):
        cfg = config.clean(dict(sim_cfg(), rxConverter="Gone"))
        self.assertEqual(cfg["rxConverter"], "QO-100: LNB 9750 MHz")


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.r = Radio(sim_cfg(), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))

    def test_the_lnb_must_be_a_down_converter_that_does_not_invert_and_lands_in_the_sdr(self):
        lst = cv.add_pack(self.r.state()["converters"], cv.QO100 + cv.VHF_UHF_SHF)
        self.r.set(authorise=True, converters=lst, rxConverter="QO-100: LNB 9750.1 MHz")
        for title, words in [("HF upconverter (125 MHz)", "does not invert"),
                             ("1296 MHz (28 MHz IF)", "outside what the SDR tunes")]:
            with self.assertRaisesRegex(ValueError, words):
                self.r.set(rxConverter=title)
        inv = lst + [{"title": "Inv", "type": "down", "rxOffset": 11_200_000_000.0, "inverted": True}]
        with self.assertRaisesRegex(ValueError, "does not invert"):
            self.r.set(authorise=True, converters=inv, rxConverter="Inv")

    def test_a_transmit_converter_must_be_rx_tx_and_named_in_the_list(self):
        lst = cv.add_pack(self.r.state()["converters"], cv.QO100)
        self.r.set(authorise=True, converters=lst)
        with self.assertRaisesRegex(ValueError, "receive only"):
            self.r.set(authorise=True, txConverter="QO-100: LNB 9750.1 MHz")
        with self.assertRaisesRegex(ValueError, "not in the list"):
            self.r.set(authorise=True, rigTxConverter="Nope")
        with self.assertRaises(ValueError):
            self.r.set(txConverter="QO-100 uplink: 432 MHz IF (LO 1968)")      # Settings only
        self.r.set(authorise=True, txConverter="QO-100 uplink: 432 MHz IF (LO 1968)")

    def test_a_tx_only_converter_transmits_and_is_never_the_lnb(self):
        up = {"title": "Ray's upconverter", "type": "down", "use": "tx", "txOffset": 1_104_000_000.0}
        lst = self.r.state()["converters"] + [up]
        self.r.set(authorise=True, converters=lst, rigTxConverter=up["title"])
        self.r.set(authorise=True, txConverter=up["title"])
        self.assertEqual(nbconv.rig_converter(self.r.state()).radio(2_400_100_000.0, tx=True), 1_296_100_000.0)
        with self.assertRaisesRegex(ValueError, "TX only: nothing can be received through it"):
            self.r.set(authorise=True, rxConverter=up["title"])
        self.assertEqual(self.r.state()["rxConverter"], "QO-100: LNB 9750 MHz")

    def test_a_hand_edited_file_receiving_through_a_tx_only_converter_receives_through_the_lnb(self):
        up = {"title": "Up", "use": "tx", "txOffset": 1_104_000_000.0}
        cfg = config.clean(dict(sim_cfg(), converters=nbconv.DEFAULT_LIST + [up], rxConverter="Up"))
        self.assertEqual(cfg["rxConverter"], "QO-100: LNB 9750 MHz")
        self.assertEqual(nbconv.rx_lo(cfg), 9_750_000_000.0)

    def test_the_converter_s_most_drive_caps_the_pluto_s_gain(self):
        lst = self.r.state()["converters"] + [{"title": "Up", "type": "down", "rxtx": True,
                                               "rxOffset": 1_968_000_000.0, "maxDriveDbm": -10.0}]
        self.r.set(authorise=True, converters=lst, txConverter="Up", txGainCeiling=0.0)
        self.r.set(txGain=-16.5)                      # 6.5 dBm - 16.5 dB = -10 dBm: at the limit
        with self.assertRaisesRegex(ValueError, "overdrive Up"):
            self.r.set(txGain=-16.0)


class PlutoThroughAConverter(unittest.TestCase):
    """The Pluto driving an upconverter: tuned to the IF, and - for an
    inverting one - its output mirrored, so that what comes back through
    the simulated transponder (with the converter in the simulator's loop)
    lands where the dial says. TX lock converging on the simulator's error
    from speech proves the sideband: a mirrored spectrum does not correlate."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, conv: dict):
        lst = nbconv.DEFAULT_LIST + [conv]
        r = make_radio(self.tmp, audio_source=noise_audio(), mode="usb", vfo=VFO, simUlErrorHz=3000.0,
                       simDriftHz=0.0, converters=lst, txConverter=conv["title"])
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 1.5)
            r.ptt(True)
            run_sim(r, 0.3)
            lo = r.tx_lo
            self.assertAlmostEqual(r.dev.tx_lo, cv.Converter.from_dict(conv).radio(lo, tx=True))
            run_sim(r, 8)
            s = r.state()
            self.assertLess(abs(s["txCorr"] + 3000.0), 10.0)
        finally:
            r.stop()

    def test_low_side_from_432(self):
        self._run({"title": "432 up", "type": "down", "rxtx": True, "rxOffset": 1_968_000_000.0})

    def test_high_side_from_1296_is_mirrored_and_still_lands(self):
        self._run({"title": "1296 high", "type": "down", "rxtx": True, "rxOffset": 3_696_200_000.0,
                   "inverted": True})


if __name__ == "__main__":
    unittest.main()
