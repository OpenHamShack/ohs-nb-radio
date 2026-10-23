"""The Radio API: smoke test, feeds, spectrum calibration and the safety rules."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from helpers import make_radio, noise_audio, run_sim, wait_rx_lock
from ohscore.devices import DeviceError
from ohscore.engine import Feed, TxRefused, slot_start
from ohsnb import bandplan, state
from ohsnb.devices.sim import FT8Activity as SimFT8, SimDevice
from ohsnb.radio import plan_tx_lo


class RadioCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, start=True, audio=None, **over):
        r = make_radio(self.tmp, audio_source=audio, **over)
        self.radios.append(r)
        if start:
            r.start()
        return r


class Api(RadioCase):
    def test_smoke_feeds_and_state(self):
        r = self.radio(start=False)
        self.assertFalse(r.state()["running"])
        feeds = [r.subscribe(k, 500) for k in ("wide", "zoom", "meter", "lock", "state")]
        r.start()
        self.assertFalse(r.state()["keyed"])                # rule 1: never at start
        got = run_sim(r, 3.0, feeds)
        for k in ("wide", "zoom", "meter", "lock"):
            self.assertTrue(got[k], k)
        t, start, bin_hz, db = got["wide"][-1]
        self.assertIsInstance(db, np.ndarray)
        self.assertEqual(db.dtype, np.float32)
        self.assertLessEqual(start, bandplan.DL_LO - 20_000)
        self.assertGreaterEqual(start + bin_hz * len(db), bandplan.DL_HI + 20_000)
        self.assertGreater(got["wide"][-1][0], 1e9)          # wall-clock time stamp
        r.set(vfo=10_489_612_000.0, mode="ft8")
        got = run_sim(r, 0.5, [feeds[4]])
        changes = {}
        for it in got["state"]:
            changes.update(it["changes"])
        self.assertEqual(changes.get("vfo"), 10_489_612_000.0)
        self.assertEqual(changes.get("mode"), "ft8")
        s = r.state()
        self.assertEqual(s["rxDial"], 10_489_612_000.0)
        self.assertEqual(s["segment"], "digimodes (2.7 kHz max)")
        # Zoom follows the dial.
        z = run_sim(r, 1.0, [feeds[1]])["zoom"][-1]
        _, zs, zb, zdb = z
        self.assertAlmostEqual(zs + zb * len(zdb) / 2, 10_489_612_000.0, delta=2 * zb)
        self.assertAlmostEqual(zb * len(zdb), s["zoomSpanHz"], delta=3 * zb)

    def test_set_validates_all_or_nothing(self):
        r = self.radio()
        with self.assertRaisesRegex(ValueError, "cannot be above"):
            r.set(vfo=10_489_711_000.0, volume=7)
        self.assertEqual(r.state()["vfo"], state.SPEC["vfo"]["default"])   # nothing applied
        self.assertEqual(r.state()["volume"], 0.5)
        with self.assertRaisesRegex(ValueError, "measured"):
            r.set(keyed=True)
        with self.assertRaisesRegex(ValueError, "Settings"):
            r.set(txGainCeiling=0.0)
        r.set(authorise=True, txGainCeiling=-35.0)           # gain (-30) comes down with it
        self.assertEqual(r.state()["txGain"], -35.0)
        with self.assertRaisesRegex(ValueError, "ceiling"):
            r.set(txGain=-20.0)

    def test_feed_drops_oldest_and_never_stalls_receive(self):
        r = self.radio()
        stuck = r.subscribe("wide", 3)                       # never drained
        live = r.subscribe("wide", 1000)
        got = run_sim(r, 3.0, [live])
        self.assertEqual(len(stuck), 3)
        self.assertGreater(stuck.dropped, 20)
        self.assertGreater(len(got["wide"]), 30)             # receive carried on regardless
        newest = stuck.drain()
        self.assertEqual(newest[-1][0], max(it[0] for it in newest))

    def test_feed_unit(self):
        f = Feed("x", 2)
        for i in range(5):
            f.put(i)
        self.assertEqual(f.drain(), [3, 4])
        self.assertEqual(f.dropped, 3)
        self.assertIsNone(f.get())


class SpectrumCalibration(unittest.TestCase):
    def test_beacon_sits_on_its_nominal_frequency(self):
        tmp = tempfile.mkdtemp()
        r = make_radio(tmp, simRxErrorHz=17_000.0, wideBins=8192, wideAvg=4, zoomSpanHz=2000.0, zoomBins=1024,
                       vfo=bandplan.BEACONS["lower"]["dl"] + 200.0, zoomPan=0.0)
        wide, zoom = r.subscribe("wide", 50), r.subscribe("zoom", 50)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 2.0)
            wide.drain()
            zoom.drain()
            got = run_sim(r, 1.0, [wide, zoom])
            # Wide: the strongest bin near the lower beacon is one of its two
            # F1A tones (10489.500000 / .500400), to within the bin width.
            _, start, bin_hz, db = got["wide"][-1]
            f = start + bin_hz * np.arange(len(db))
            lb = bandplan.BEACONS["lower"]["dl"]
            sel = np.abs(f - lb) < 2000
            peak = f[sel][np.argmax(db[sel])]
            self.assertLess(min(abs(peak - lb), abs(peak - lb - 400)), 0.6 * bin_hz)
            # Zoom (2 kHz span, ~2 Hz bins): both F1A tones within a few Hz of nominal.
            _, zs, zb, zdb = got["zoom"][-1]
            avg = np.mean([it[3] for it in got["zoom"][-5:]], axis=0)
            fz = zs + zb * np.arange(len(avg))
            for tone in (bandplan.BEACONS["lower"]["dl"], bandplan.BEACONS["lower"]["dl"] + 400):
                s2 = np.abs(fz - tone) < 100
                self.assertLess(abs(fz[s2][np.argmax(avg[s2])] - tone), zb + 2.0)
        finally:
            r.stop()
            shutil.rmtree(tmp, ignore_errors=True)


class BeaconCw(unittest.TestCase):
    """The beacons' bookmarks, in CW, decode the beacons' Morse: the mark
    tone is the one on the pitch. At the old bookmarks the space tone was,
    and the decoder printed unknown letters (Brian's TV, 10/10/2026)."""

    def decoded_at(self, preset: str) -> str:
        tmp = tempfile.mkdtemp()
        dial = next(p["dl"] for p in bandplan.PRESETS if p["name"] == preset)
        r = make_radio(tmp, simRxErrorHz=17_000.0, vfo=dial, mode="cw")
        events = r.subscribe("events", 500)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            # Two 37.9 s cycles: wherever the first starts, one whole
            # message is in them.
            got = run_sim(r, 80.0, [events])
            return "".join(e.get("text", "") for e in got["events"] if e.get("mode") == "cw")
        finally:
            r.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_lower_beacon(self):
        self.assertIn("HI DE QO100 QRA DK0SB", self.decoded_at("Lower beacon"))

    def test_upper_beacon(self):
        self.assertIn("HI DE QO100 QRA DK0SB", self.decoded_at("Upper beacon"))


class Safety(RadioCase):
    def test_refused_on_beacon_segment_outside_band_and_wrong_mode(self):
        r = self.radio(vfo=10_489_748_000.0)
        with self.assertRaisesRegex(TxRefused, "middle beacon"):
            r.ptt(True)
        r.set(vfo=10_489_490_000.0)
        with self.assertRaisesRegex(TxRefused, "outside"):
            r.ptt(True)
        r.set(vfo=10_489_520_000.0, mode="usb")
        with self.assertRaisesRegex(TxRefused, "not allowed"):
            r.ptt(True)
        r.set(vfo=10_489_700_000.0, mode="am")
        with self.assertRaisesRegex(TxRefused, "receive-only"):
            r.ptt(True)
        self.assertFalse(r.state()["keyed"])

    def test_idle_judges_a_message_mode_by_its_own_signal(self):
        # 0.1.3: after an FT4 send that had measured itself and gone out,
        # txBlocked said "narrow digimodes allows 500 Hz; this signal is
        # 2400 Hz wide" - the SSB passband's width, true of nothing FT4 sends.
        narrow = 10_489_545_000.0
        r = self.radio(mode="ft4", vfo=narrow, audio=noise_audio())
        run_sim(r, 0.3)
        self.assertEqual(r.state()["txBlocked"], "")
        if r.state()["modes"]["ft4"]["encode"]:
            with mock.patch("ohscore.engine.slot_start", lambda *a, **k: 0.0):
                r.send("ft4", text="CQ GM4BRI IO86", freq=1500.0)
            run_sim(r, 0.3)
            self.assertTrue(r.state()["keyed"])
            run_sim(r, 10.0, until=lambda: not r.state()["keyed"])
            self.assertFalse(r.state()["keyed"])
            r.set(vfo=narrow + 100.0)                  # anything that re-derives the idle state
            run_sim(r, 0.3)
            self.assertEqual(r.state()["txBlocked"], "")
        # Each message mode in the narrow segment: judged by what it sends.
        for mode in ("ft8", "ft4", "psk31", "psk63", "psk125", "rtty"):
            r.set(mode=mode, vfo=narrow)
            self.assertEqual(r.state()["txBlocked"], "", mode)
        r.set(mode="sstv")
        self.assertRegex(r.state()["txBlocked"], r"500 Hz at most; this signal is 1250 Hz wide")
        # Where still matters: no digital mode in the CW segment.
        r.set(mode="ft4", vfo=10_489_520_000.0)
        self.assertIn("not allowed in the CW only segment", r.state()["txBlocked"])
        # A measured message is still judged by itself, not by the table.
        r.set(vfo=narrow)
        self.assertIn("500 Hz at most", r._tx_guard("ft4", narrow, (narrow + 300.0, narrow + 2700.0)))

    def test_ptt_in_a_digital_mode_is_judged_as_that_mode(self):
        # Plain PTT in FT8/FT4 carries another program's signal through a
        # loopback device. Judged by the SSB passband it could not key in
        # the narrow digimodes segment at all; judged as FT4 it can, and
        # SSTV's 1.25 kHz still cannot.
        r = self.radio(mode="ft4", vfo=10_489_545_000.0, audio=noise_audio())
        r.ptt(True)
        run_sim(r, 0.2)
        self.assertTrue(r.state()["keyed"])
        r.ptt(False)
        run_sim(r, 0.2)
        r.set(mode="sstv")
        with self.assertRaisesRegex(TxRefused, "500 Hz at most"):
            r.ptt(True)
        self.assertFalse(r.state()["keyed"])

    def test_the_width_table_is_what_the_encoders_send(self):
        from ohscore import modes_glue
        r = self.radio(start=False)
        for mode, width in bandplan.SIGNAL_WIDTH.items():
            enc = modes_glue.encoder(mode)
            if enc is None:
                continue
            if mode == "sstv":
                img = np.zeros((256, 320, 3), np.uint8)
                img[..., 0] = np.arange(320) % 256
                img[..., 1] = 128
                audio = enc.render(image=img)
            elif mode == "kgstv":
                # The busiest picture there is (noise) at the finest quality NB
                # offers: the longest over, and the content that once widened it.
                pic = np.random.default_rng(1).integers(0, 256, (240, 320, 3), dtype=np.uint8)
                audio = enc.render(picture=pic, callsign="GM4BRI", locator="IO75RL", scale=8)
            elif mode == "js8":
                # The table holds JS8's widest speed, Ultra (bandplan.py says
                # why), and JS8 sends the operator's call with every message,
                # so it refuses without one; the other text modes take none.
                audio = enc.render(text="CQ CQ", offset=1500.0, callsign="GM4BRI", locator="IO75",
                                   speed="ultra")
            else:
                audio = enc.render(text="CQ CQ DE GM4BRI GM4BRI K", freq=1500.0, offset=1500.0, center=1500.0)
            lo, hi = r._occupied(mode, 0.0, np.asarray(audio, np.float32))
            self.assertLessEqual(hi - lo, width, mode)
            self.assertGreater(hi - lo, 0.85 * width, mode)
        rng = np.random.default_rng(1)
        for wave, width in bandplan.FREEDV_WIDTH.items():
            st = modes_glue.streamer("freedv", wave)
            if st is None:
                continue
            audio = np.concatenate([np.asarray(st.process((0.3 * rng.standard_normal(1200)).astype(np.float32)),
                                               np.float32) for _ in range(100)])
            lo, hi = r._occupied("freedv", 0.0, audio[len(audio) // 4:])      # past the modem's preamble
            self.assertLessEqual(hi - lo, width, wave)
            self.assertGreater(hi - lo, 0.85 * width, wave)

    def test_receive_only_device_refused(self):
        class RxOnly(SimDevice):
            can_tx = False
        from helpers import sim_cfg
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        r = Radio(sim_cfg(), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False), device=RxOnly(sim_cfg()))
        self.radios.append(r)
        r.start()
        with self.assertRaisesRegex(TxRefused, "receive-only"):
            r.ptt(True)

    def test_settings_and_restart_never_key(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.set(volume=0.2, vfo=10_489_521_000.0)
        self.assertFalse(r.state()["keyed"])
        r.ptt(True)
        run_sim(r, 0.5)
        self.assertTrue(r.state()["keyed"])
        r.stop()
        r.start()
        run_sim(r, 0.5)
        self.assertFalse(r.state()["keyed"])

    def test_receiver_gain_applies_to_the_running_radio(self):
        # It used to reach the device only when it was next opened: saving
        # it in Settings changed nothing until the radio was restarted.
        r = self.radio()
        wide = r.subscribe("wide", 500)
        dev = r.dev

        def floor():
            run_sim(r, 0.5, [wide])                       # let the change land, drop what came before
            lines = run_sim(r, 1.0, [wide])["wide"]
            return float(np.median(np.concatenate([db for _t, _s, _b, db in lines])))

        agc = floor()
        r.set(rxGainMode="manual", rxGain=60.0)
        manual = floor()
        self.assertIs(r.dev, dev)                         # the same device: no restart
        self.assertTrue(r.state()["running"])
        self.assertAlmostEqual(manual - agc, 20.0, delta=1.0)
        r.set(rxGain=30.0)
        self.assertAlmostEqual(floor() - agc, -10.0, delta=1.0)
        r.set(rxGainMode="slow_attack")
        self.assertAlmostEqual(floor() - agc, 0.0, delta=1.0)

    def test_a_refused_receiver_gain_is_reported_and_receive_carries_on(self):
        class Refuses(SimDevice):
            def set_rx_gain(self, mode, db):
                if getattr(self, "opened", False):
                    raise DeviceError("no such attribute")
                super().set_rx_gain(mode, db)
        from helpers import sim_cfg
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        r = Radio(sim_cfg(), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False),
                  device=Refuses(sim_cfg()))
        self.radios.append(r)
        toasts = r.subscribe("toast", 50)
        r.start()
        r.set(rxGainMode="manual")
        got = run_sim(r, 0.5, [toasts])["toast"]
        self.assertTrue(any("Receiver gain not applied" in t["text"] and "no such attribute" in t["text"]
                            for t in got), got)
        self.assertTrue(r.state()["running"])

    def test_tuning_onto_a_beacon_while_keyed_unkeys(self):
        r = self.radio(mode="usb", vfo=10_489_740_000.0, audio=noise_audio())
        toast = r.subscribe("toast", 50)
        r.ptt(True)
        run_sim(r, 0.5)
        r.set(vfo=10_489_744_000.0)                      # speech would reach the beacon guard
        run_sim(r, 0.3)
        self.assertFalse(r.state()["keyed"])
        self.assertTrue(any("beacon" in t["text"] for t in toast.drain()))

    def test_tuning_a_send_onto_a_beacon_unkeys(self):
        # send() measures its occupied band at the dial it was sent from;
        # the transmitter follows the dial, and so must the re-check. It
        # judged the band where it was measured, and a send tuned onto the
        # middle beacon carried on.
        r = self.radio(mode="cw", vfo=10_489_550_000.0)
        toast = r.subscribe("toast", 50)
        r.send("cw", text="PARIS " * 10)
        run_sim(r, 0.5)
        self.assertTrue(r.state()["keyed"])
        r.set(vfo=10_489_750_000.0)
        self.assertFalse(r.state()["keyed"])
        self.assertTrue(any("beacon" in t["text"] for t in toast.drain()))

    def test_a_send_tuned_within_its_segment_carries_on(self):
        r = self.radio(mode="cw", vfo=10_489_550_000.0)
        r.send("cw", text="PARIS " * 10)
        run_sim(r, 0.5)
        r.set(vfo=10_489_552_000.0)
        run_sim(r, 0.3)
        self.assertTrue(r.state()["keyed"])

    # The timers' minimum settings are seconds long for operators; the tests
    # shorten them in the engine's state directly so they run quickly.
    def test_tx_timeout(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.st["txTimeoutSec"] = 0.6
        r.ptt(True)
        t0 = time.monotonic()
        while r.state()["keyed"] and time.monotonic() - t0 < 5:
            time.sleep(0.05)
            r.heartbeat()
        self.assertFalse(r.state()["keyed"])
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_a_slow_key_up_is_not_timed_from_the_previous_over(self):
        # The previous over started long ago (on the first over of a run,
        # tx_t0 is 0.0: boot time). Key-up here takes several supervisor
        # ticks - a real Pluto retuning, or an FT8 send waiting for its
        # slot - and the over must be timed from now, not from back then.
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        toast = r.subscribe("toast", 64)
        r.tx_t0 = r.last_mic_audio = time.monotonic() - 10_000.0
        key_up = r._tx_key_up

        def slow_key_up(dev):
            time.sleep(0.4)
            key_up(dev)
        r._tx_key_up = slow_key_up
        r.ptt(True)
        # Wall-clock time, not simulated: the supervisor ticks on the clock.
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.8:
            time.sleep(0.05)
            r.heartbeat()
        self.assertTrue(r.state()["keyed"], [t["text"] for t in toast.drain()])

    def test_dead_air_unkeys_voice(self):
        r = self.radio(mode="usb", vfo=10_489_700_000.0)     # null audio: silence
        r.st["deadAirSec"] = 0.5
        r.ptt(True)
        t0 = time.monotonic()
        while r.state()["keyed"] and time.monotonic() - t0 < 5:
            time.sleep(0.05)
            r.heartbeat()
        self.assertFalse(r.state()["keyed"])

    def test_voice_with_audio_stays_keyed(self):
        r = self.radio(mode="usb", vfo=10_489_700_000.0, audio=noise_audio())
        r.st["deadAirSec"] = 0.5
        r.ptt(True)
        run_sim(r, 3.0)
        self.assertTrue(r.state()["keyed"])

    def test_watchdog_unkeys_when_the_ui_stops(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.st["watchdogSec"] = 0.5
        r.ptt(True)
        time.sleep(1.5)                                    # no heartbeat, no draining
        self.assertFalse(r.state()["keyed"])

    def test_level_guard_trims_power_below_beacon(self):
        # Sim: at -20 dB our carrier equals the beacon; at -5 dB it is 15 dB over.
        r = self.radio(mode="cw", vfo=10_489_520_000.0, txGain=-5.0, txGainCeiling=0.0, levelMarginDb=6.0)
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 1.5)
        r.ptt(True)
        run_sim(r, 6.0)
        s = r.state()
        self.assertLess(s["txGain"], -20.0)
        self.assertIsNotNone(s["vsBeacon"])
        self.assertLess(s["vsBeacon"], -4.0)

    def test_tx_lo_never_in_the_passband(self):
        for fs in (1_200_000.0, 600_000.0):
            lo = None
            for ul in np.arange(bandplan.UL_LO + 5_000, bandplan.UL_HI - 10_000, 7_000.0):
                if 2_400_245_000 <= ul <= 2_400_255_000:
                    continue
                new = plan_tx_lo(ul, fs, lo)
                if new is None:
                    self.assertEqual(fs, 600_000.0)       # only the low rate has a gap
                    self.assertTrue(2_400_210_000 < ul < 2_400_290_000)
                    continue
                self.assertFalse(bandplan.UL_LO <= new <= bandplan.UL_HI)
                self.assertLessEqual(abs(ul - new), 0.4 * fs)
                lo = new
        # At 1.2 MS/s the LO stays put across most of the band.
        self.assertEqual(plan_tx_lo(2_400_400_000.0, 1.2e6, None), plan_tx_lo(2_400_010_000.0, 1.2e6, None))


class MemoriesAndLog(RadioCase):
    def test_memories(self):
        r = self.radio()
        names = [m["name"] for m in r.memories()]
        self.assertIn("FT8", names)
        r.recall("FT8")
        self.assertEqual(r.state()["mode"], "ft8")
        r.save_memory("net", dl=10_489_811_000.0, mode="usb")
        r.recall("net")
        self.assertEqual(r.state()["vfo"], 10_489_811_000.0)
        r.delete_memory("net")
        with self.assertRaises(ValueError):
            r.recall("net")

    def test_log_and_adif(self):
        r = self.radio(start=False, callsign="GM4BRI", locator="IO86")
        r.log_qso("g4xyz", dl=10_489_701_000.0, mode="usb", rstSent="59", rstRcvd="57", t=1_790_000_000)
        path = r.export_adif(Path(self.tmp) / "out.adi")
        text = path.read_text()
        self.assertIn("<CALL:5>G4XYZ", text)
        self.assertIn("<SAT_NAME:6>QO-100", text)
        self.assertIn("<PROP_MODE:3>SAT", text)
        self.assertIn("<FREQ:11>2400.201000", text)
        self.assertIn("<FREQ_RX:12>10489.701000", text)
        self.assertIn("<STATION_CALLSIGN:6>GM4BRI", text)
        self.assertEqual(text.count("<EOR>"), 1)

    def test_log_edit_and_delete(self):
        r = self.radio(start=False)
        r.log_qso("g4xyz", dl=10_489_701_000.0, mode="usb", rstSent="59", t=1_790_000_000)
        r.log_qso("dl1abc", dl=10_489_540_000.0, mode="ft8", rstSent="-10", t=1_790_000_100)
        r.edit_qso(0, call="g4xyy", rstRcvd="55", rstSent="")
        e = r.log_entries()
        self.assertEqual(e[0]["call"], "G4XYY")
        self.assertEqual(e[0]["rstRcvd"], "55")
        self.assertNotIn("rstSent", e[0])
        self.assertEqual(e[1]["call"], "DL1ABC")
        r.delete_qso(0)
        self.assertEqual([x["call"] for x in r.log_entries()], ["DL1ABC"])
        with self.assertRaises(ValueError):
            r.edit_qso(5, call="X")
        with self.assertRaises(ValueError):
            r.edit_qso(0, call="!!")

    def test_sstv_pictures_go_to_the_data_directory(self):
        r = self.radio(mode="sstv")
        run_sim(r, 0.5)
        if r.decoder is None:
            self.skipTest("no SSTV decoder here")
        # Written by the engine's decoder host (shack_sdr), into its files
        # folder: the data folder's sstv folder.
        self.assertEqual(Path(r.decoders.files_dir()), Path(self.tmp) / "sstv")


class Persistence(unittest.TestCase):
    def test_corrections_persist_but_keyed_never_does(self):
        tmp = tempfile.mkdtemp()
        try:
            from helpers import sim_cfg
            from ohsnb import config
            from ohscore.audio import NullAudio
            from ohsnb.radio import Radio
            conf = Path(tmp) / "c.json"
            r = Radio(sim_cfg(simRxErrorHz=-4321.0), conf_path=conf, data_dir=tmp, audio=NullAudio(realtime=False))
            r.start()
            self.assertTrue(wait_rx_lock(r))
            r.stop()
            cfg = config.load(conf)
            self.assertAlmostEqual(cfg["rxCorr"], -4321.0, delta=5)
            self.assertNotIn("keyed", cfg)
            self.assertEqual(state.SPEC["keyed"]["persist"], False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Sending(RadioCase):
    def test_cw_send_keys_and_unkeys_itself(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.send("cw", text="EE", wpm=30)
        self.assertTrue(r.state()["keyed"])
        run_sim(r, 3.0, until=lambda: not r.state()["keyed"])
        self.assertFalse(r.state()["keyed"])
        self.assertEqual(r.state()["txSource"], "")

    def test_send_needs_the_matching_mode_and_a_legal_place(self):
        r = self.radio(mode="usb", vfo=10_489_700_000.0)
        with self.assertRaisesRegex(ValueError, "Switch to cw"):
            r.send("cw", text="TEST")
        r.set(mode="ft8")
        with self.assertRaises(ValueError):          # SSB-only segment (or no FT8 encoder here)
            r.send("ft8", text="CQ G4XYZ IO91")
        self.assertFalse(r.state()["keyed"])


class SlotScheduling(unittest.TestCase):
    """When send() keys an FT8/FT4 transmission, with the clock in the
    test's hands. T is a slot boundary for both modes and its FT8 slot is
    even (slot index = floor(utc / 15))."""

    T = 1_791_000_000.0

    def test_queued_before_the_start_waits_for_it(self):
        self.assertEqual(slot_start(self.T + 0.2, "ft8"), self.T + 0.5)

    def test_queued_a_little_late_goes_at_once_in_this_slot(self):
        for late in (0.6, 1.0, 1.5, 2.0):
            with self.subTest(late=late):
                self.assertEqual(slot_start(self.T + late, "ft8"), self.T + late)

    def test_too_late_waits_for_the_next_slot(self):
        self.assertEqual(slot_start(self.T + 2.1, "ft8"), self.T + 15.5)
        self.assertEqual(slot_start(self.T + 14.9, "ft8"), self.T + 15.5)

    def test_answering_a_cq_goes_in_the_very_next_slot(self):
        # A CQ in the even slot T..T+15, decoded at 13.5 s; on a slow machine
        # jt9 takes until 1.2 s into the next (odd) slot; the answer, which
        # must be odd, goes out there and then. The old rule waited for the
        # next boundary (T+30, even) and then a further slot for parity:
        # T+45.5, two cycles late.
        self.assertEqual(slot_start(self.T + 16.2, "ft8", "odd"), self.T + 16.2)
        # Decoded in time, before the odd slot began: its normal start.
        self.assertEqual(slot_start(self.T + 14.3, "ft8", "odd"), self.T + 15.5)

    def test_parity_is_honoured(self):
        self.assertEqual(slot_start(self.T + 1.0, "ft8", "odd"), self.T + 15.5)
        self.assertEqual(slot_start(self.T + 1.0, "ft8", "even"), self.T + 1.0)
        self.assertEqual(slot_start(self.T + 2.1, "ft8", "even"), self.T + 30.5)

    def test_q65_starts_1_s_in_and_at_most_1_s_late(self):
        # WSJT-X starts Q65-60 1 s into the period (DT 0 at its receivers)
        # and, on default settings, finds a signal up to DT +1 s.
        self.assertEqual(slot_start(self.T + 0.2, "q65"), self.T + 1.0)
        self.assertEqual(slot_start(self.T + 1.9, "q65"), self.T + 1.9)
        self.assertEqual(slot_start(self.T + 2.1, "q65"), self.T + 61.0)

    def test_ft4(self):
        # FT4 nominally starts 0.5 s in (DT 0) and may start up to 0.5 s late.
        self.assertEqual(slot_start(self.T + 0.3, "ft4"), self.T + 0.5)
        self.assertEqual(slot_start(self.T + 0.9, "ft4"), self.T + 0.9)
        self.assertEqual(slot_start(self.T + 1.1, "ft4"), self.T + 8.0)
        self.assertEqual(slot_start(self.T + 7.6, "ft4", "even"), self.T + 15.5)

    def test_a_late_start_still_ends_inside_the_slot(self):
        # 79 symbols of 0.16 s from the latest start allowed must be over
        # before WSJT-X's last decoding pass, 14.7 s into the slot.
        latest = max(t for t in np.arange(0.0, 15.0, 0.01) if slot_start(self.T + t, "ft8") < self.T + 15)
        self.assertLessEqual(latest + 79 * 0.16, 14.7)


class Decoding(RadioCase):
    def test_the_engine_closes_the_decoders_it_replaces_and_stops(self):
        # A decoder that was swapped out was simply dropped: FT8's working
        # folder (and FreeDV's codec2 handle) went with it unclosed.
        closed = []

        class Dec:
            def __init__(self, name):
                self.name = name

            def feed(self, audio, t):
                pass

            def close(self):
                closed.append(self.name)

        from ohscore import modes_glue
        with mock.patch.object(modes_glue, "decoder", lambda mode, emit, **kw: Dec(mode)):
            r = self.radio(mode="ft8", vfo=10_489_540_000.0)
            run_sim(r, 0.5)
            r.set(mode="psk31")
            run_sim(r, 0.5, until=lambda: closed)
            self.assertEqual(closed, ["ft8"])
            r.stop()
            self.assertEqual(closed, ["ft8", "psk31"])
            r.start()                                  # and a restart decodes again, with a new one
            run_sim(r, 0.5, until=lambda: r.decoder is not None)
            self.assertEqual(r.decoder.name, "psk31")

    def test_the_ft8_decoder_setting_reaches_the_decoder_and_its_choice_the_status(self):
        from ohscore.modes import ft8
        r = self.radio(mode="ft8", vfo=10_489_540_000.0)
        run_sim(r, 0.3, until=lambda: r.decoder is not None)
        if not ft8.CAN_DECODE:
            self.skipTest("no FT8 decoder installed")
        first = "ohsdigi" if ft8._OHSDIGI_DEC is not None else "jt9"
        run_sim(r, 0.3, until=lambda: r.state().get("ft8DecoderInUse"))
        self.assertEqual(r.state()["ft8DecoderInUse"], first)
        self.assertEqual(r.decoder._order()[0], first)
        r.set(authorise=True, ft8Decoder="jt9")       # asked at each slot: no new decoder needed
        if ft8._JT9:
            self.assertEqual(r.decoder._order()[0], "jt9")
        r.set(mode="psk31")
        run_sim(r, 0.3, until=lambda: r.state().get("ft8DecoderInUse") == "")
        self.assertEqual(r.state()["ft8DecoderInUse"], "")

    def test_choosing_a_mode_with_no_decoder_says_so_and_why(self):
        """0.1.10-beta.1's store image had no FT8 decoder and FT8 was just
        silent. Choosing it now toasts the registry's reason and holds it
        in decoderMissing until a mode that decodes is chosen."""
        from ohscore import modes_glue
        real = modes_glue._entry

        def entry(name, freedv_mode="700d"):
            info, missing = real(name, freedv_mode)
            return (info, "no FT8 decoder in this test") if name == "ft8" else (info, missing)
        with mock.patch.object(modes_glue, "_entry", entry):
            r = self.radio(mode="psk31", vfo=10_489_540_000.0)
            toasts = r.subscribe("toast", 50)
            run_sim(r, 0.3, until=lambda: r.decoder is not None)
            self.assertEqual(r.state()["decoderMissing"], "")
            r.set(mode="ft8")
            got = run_sim(r, 0.5, [toasts], until=lambda: r.state()["decoderMissing"])["toast"]
            self.assertEqual(r.state()["decoderMissing"], "no FT8 decoder in this test")
            self.assertTrue(any(t["text"] == "FT8 cannot be decoded here: no FT8 decoder in this test"
                                and t["level"] == "warn" for t in got), got)
            r.set(mode="usb")                       # needs no decoder: nothing missing
            run_sim(r, 0.3, until=lambda: r.state()["decoderMissing"] == "")
            self.assertEqual(r.state()["decoderMissing"], "")

    def test_ft8_from_the_simulated_band_decodes(self):
        # Needs ohscore.modes' FT8 (and WSJT-X's jt9); skipped where they are absent.
        r = self.radio(start=False, simSignals=True, mode="ft8", vfo=10_489_540_000.0)
        ev = r.subscribe("events", 200)
        r.start()
        if not r.state()["modes"]["ft8"]["decode"]:
            self.skipTest("FT8 decoder not available: " + r.state()["modes"]["ft8"]["missing"])
        got = run_sim(r, 47.0, [ev])["events"]
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10 and not any(e.get("mode") == "ft8" for e in got):
            time.sleep(0.2)
            r.heartbeat()
            got += ev.drain()
        texts = {e.get("text") for e in got if e.get("mode") == "ft8"}
        self.assertTrue(texts & set(SimFT8.MESSAGES), texts)

    def test_psk31_own_echo_decodes(self):
        # Our own transmission, round the simulated transponder: 250 ms late,
        # 6 Hz high (an uplink error inside the decoder's AFC range, which TX
        # lock may also move mid-over), at whatever level and timing the whole
        # receive chain delivers. The decoder is created when the mode is
        # selected and has been listening to noise for seconds before the
        # echo arrives - the case a decoder that only acquired once, on the
        # first audio it was fed, never decoded.
        r = self.radio(start=False, mode="psk31", vfo=10_489_560_000.0, simUlErrorHz=6.0)
        ev = r.subscribe("events", 500)
        r.start()
        if not r.state()["modes"]["psk31"]["encode"]:
            self.skipTest("PSK31 not available: " + r.state()["modes"]["psk31"]["missing"])
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 3.0)
        text = "CQ CQ DE GM4BRI GM4BRI PSE K"
        r.send("psk31", text=text)
        got = run_sim(r, 20.0, [ev], until=lambda: not r.state()["keyed"])["events"]
        got += run_sim(r, 2.0, [ev])["events"]
        heard = "".join(e.get("text", "") for e in got if e.get("mode") == "psk31")
        self.assertIn(text, heard)

    def test_robot36_own_echo_decodes_aligned(self):
        # A picture sent with radio.send() and received as our own echo:
        # 250 ms late, a few hertz off (TX lock corrects it mid-picture), at
        # the level and with the noise the simulated transponder gives it,
        # through the whole receive chain. Robot36 is the shortest mode
        # (36 s), and the simulator runs several times faster than real time.
        from test_modes_sstv import BARS, _bars, _edge_columns, _png
        r = self.radio(start=False, mode="sstv", vfo=10_489_600_000.0, simUlErrorHz=6.0)
        ev = r.subscribe("events", 2000)
        r.start()
        if not r.state()["modes"]["sstv"]["encode"]:
            self.skipTest("SSTV not available: " + r.state()["modes"]["sstv"]["missing"])
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 1.0)
        img = _bars(240, 320)
        r.send("sstv", image=img, sstvMode="robot36")
        got = run_sim(r, 45.0, [ev], until=lambda: not r.state()["keyed"], timeout=240)["events"]
        got += run_sim(r, 3.0, [ev], until=lambda: any(e.get("state") == "done" for e in got + ev.drain()))["events"]
        got += ev.drain()
        done = [e for e in got if e.get("mode") == "sstv" and e.get("state") == "done"]
        self.assertEqual(len(done), 1, [e.get("state") for e in got if e.get("state") != "line"])
        with open(done[0]["path"], "rb") as f:
            dec = _png(f.read())
        # The echo is not clean: the transponder's noise leaves a pixel-to-
        # pixel scatter of about 25 levels in 255 (mean error ~23 measured),
        # but each bar is its own colour and every edge is where it was sent.
        self.assertLess(np.abs(dec.astype(int) - img.astype(int)).mean(), 30)
        for k in range(8):
            got = dec[60:180, k * 40 + 10:(k + 1) * 40 - 10].reshape(-1, 3).mean(axis=0)
            self.assertLess(np.abs(got - BARS[k]).max(), 40, f"bar {k}: {got}")
        truth, found = _edge_columns(dec, slice(40, 200))
        for t, f in zip(truth, found):
            self.assertLessEqual(abs(t - f), 2, f"edge at {t} found at {f}")


if __name__ == "__main__":
    unittest.main()
