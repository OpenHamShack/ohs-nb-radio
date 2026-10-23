"""IQ playback (ohscore/devices/filedev.py, Engine.start_playback): a SigMF
recording must play through the receiver as the radio would have delivered
it - on the frequencies it was received on, retunes and gaps where the
file marks them, its signals on the UTC they were sent at - must refuse
what it cannot do with a sentence (tuning outside it, transmitting), and
must never leave the recording's corrections in the operator's config.

The device is tested on small files written here; the engine with the
simulator, recorded and played back (record -> play: the same spectrum,
and PSK31 and FT8 decodes, FT8 in its original slot)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim, wait_rx_lock
from ohscore import sigmf
from ohscore.converters import Converter
from ohscore.devices import DeviceError
from ohscore.devices.filedev import FileDevice, GAP_FILL_S, LOOP_STEP_S
from ohscore.engine import TxRefused

FS = 48_000.0
T0 = 1_791_375_738.5          # a UTC with a half second in it, as a real recording's start is


def tone(n, f, fs=FS, amp=0.25, start=0):
    t = (start + np.arange(n)) / fs
    return (amp * np.exp(2j * np.pi * f * t)).astype(np.complex64)


def peak_hz(x, fs=FS):
    X = np.fft.fftshift(np.abs(np.fft.fft(x)))
    f = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
    return float(f[int(np.argmax(X))])


def record(base: Path, blocks, fs=FS, meta=None) -> Path:
    """A recording made by our own recorder from (samples, on-air Hz of DC,
    UTC) blocks; returns the .sigmf-data path."""
    rec = sigmf.Recorder(base, fs, meta or {}).start()
    for x, air, utc in blocks:
        assert rec.push(x, (air, air), utc)
    rec.close()
    assert rec.wait(10)
    return rec.data_path


def hand_made(base: Path, comps: np.ndarray, datatype: str, g=None, caps=None) -> Path:
    """A recording as another program might write it."""
    data, meta = sigmf.paths(base)
    comps.tofile(data)
    glob = {"core:datatype": datatype, "core:sample_rate": FS, "core:version": "1.0.0", **(g or {})}
    meta.write_text(json.dumps({"global": glob, "annotations": [],
                                "captures": caps or [{"core:sample_start": 0, "core:frequency": 1e6,
                                                      "core:datetime": sigmf.iso_utc(T0)}]}))
    return data


def read_all(dev, n=4800, blocks=None):
    out, stamps = [], []
    k = 0
    while not dev.ended and (blocks is None or k < blocks):
        out.append(dev.read(n))
        stamps.append(dev.utc_end)
        k += 1
    return np.concatenate(out), stamps


class FileDeviceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def play(self, path, tune=None, **kw):
        d = FileDevice(path, realtime=False, **kw)
        d.open()
        self.addCleanup(d.close)
        if tune is not None:
            d.set_rx_if(tune)
        return d


class Device(FileDeviceCase):
    def test_tuned_where_it_was_recorded_it_gives_back_the_samples(self):
        x = tone(48_000, 3_000.0)
        d = self.play(record(self.dir / "a", [(x, 100e6, T0)]), tune=100e6)
        self.assertFalse(d.can_tx)
        self.assertFalse(d.radiates)
        self.assertEqual(d.fs, FS)
        y, stamps = read_all(d)
        np.testing.assert_allclose(y[:len(x)], x, atol=1.5 / sigmf.SCALE)
        # The clock is the recording's: the end of the first block read is
        # its length after the file's start.
        self.assertAlmostEqual(stamps[0], T0 + 4800 / FS, places=6)

    def test_tuned_elsewhere_inside_it_the_signals_stay_where_they_were(self):
        # A carrier 3 kHz above DC at 100 MHz is on the air at 100.003 MHz;
        # with DC 2 kHz higher it must come out 1 kHz above DC - continuous
        # in phase from block to block (an NCO restarted each block would
        # smear the line).
        x = tone(96_000, 3_000.0)
        d = self.play(record(self.dir / "b", [(x, 100e6, T0)]), tune=100.002e6)
        y, _ = read_all(d, n=4799)
        np.testing.assert_allclose(y[:len(x)], tone(len(x), 1_000.0), atol=2e-4)

    def test_through_a_converter_it_is_matched_on_the_air(self):
        # The recording says where its DC was on the air (10489.75 MHz); an
        # app working through a 9750 MHz LNB asks for IFs.
        x = tone(48_000, 5_000.0)
        lnb = Converter("LNB", rx_offset=9_750e6)
        d = self.play(record(self.dir / "c", [(x, 10_489.75e6, T0)]), conv=lnb, tune=739.751e6)
        y, _ = read_all(d)
        self.assertAlmostEqual(peak_hz(y[:48_000]), 4_000.0, delta=2)
        # Through an inverting converter the stream comes out mirrored, as
        # that radio's would (the engine mirrors it back).
        hi = Converter("High-side", rx_offset=11_229.75e6, inverted=True)
        d = self.play(record(self.dir / "c2", [(x, 10_489.75e6, T0)]), conv=hi, tune=740e6)
        y, _ = read_all(d)
        self.assertAlmostEqual(peak_hz(y[:48_000]), -5_000.0, delta=2)

    def test_outside_the_recording_is_refused_with_a_sentence(self):
        d = self.play(record(self.dir / "d", [(tone(4800, 0.0), 100e6, T0)]))
        with self.assertRaises(DeviceError) as cm:
            d.set_rx_if(101e6)
        self.assertIn("outside the recording", str(cm.exception))
        self.assertIn("99.978400-100.021600 MHz", str(cm.exception))
        lo, hi = d.rx_range
        self.assertAlmostEqual(lo, 100e6 - 0.45 * FS)
        self.assertAlmostEqual(hi, 100e6 + 0.45 * FS)

    def test_each_capture_plays_at_its_own_frequency(self):
        # The recorder re-centred 1.5 kHz up half way (NB does, as rxCorr
        # moves): the station, fixed on the air, is 1.5 kHz lower in the
        # second capture's samples. Played tuned to one place, it does not move.
        a = tone(24_000, 5_000.0)
        b = tone(24_000, 3_500.0, start=24_000)
        path = record(self.dir / "e", [(a, 100e6, T0), (b, 100.0015e6, T0 + 0.5)])
        caps = json.loads(sigmf.paths(path)[1].read_text())["captures"]
        self.assertEqual(len(caps), 2)
        d = self.play(path, tune=100e6)
        y, _ = read_all(d)
        self.assertAlmostEqual(peak_hz(y[:24_000]), 5_000.0, delta=3)
        self.assertAlmostEqual(peak_hz(y[24_000:48_000]), 5_000.0, delta=3)

    def test_a_gap_is_silence_as_long_as_the_gap_and_the_clock_runs_on(self):
        a, b = tone(48_000, 1_000.0), tone(48_000, 1_000.0)
        path = record(self.dir / "g", [(a, 100e6, T0), (b, 100e6, T0 + 1.0 + 2.0)])   # 2 s lost
        d = self.play(path, tune=100e6)
        y, stamps = read_all(d)
        self.assertEqual(len(y), 48_000 * 4)                    # 1 s, 2 s of nothing, 1 s
        self.assertTrue(np.all(y[48_000:48_000 * 3] == 0))
        self.assertGreater(np.abs(y[48_000 * 3:]).min(), 0.2)
        self.assertAlmostEqual(stamps[-1], T0 + 4.0, places=5)

    def test_a_long_gap_moves_the_clock_at_a_block_boundary(self):
        a, b = tone(30_000, 1_000.0), tone(48_000, 1_000.0)
        later = T0 + 30_000 / FS + 600.0                 # a ten-minute reconnect
        d = self.play(record(self.dir / "h", [(a, 100e6, T0), (b, 100e6, later)]), tune=100e6)
        y, stamps = read_all(d)
        # The block the gap fell in is finished with silence; the next block
        # starts with the samples after the gap, stamped from the file.
        self.assertAlmostEqual(stamps[6], T0 + 7 * 4800 / FS, places=6)
        self.assertTrue(np.all(y[30_000:33_600] == 0))
        self.assertAlmostEqual(stamps[7], later + 4800 / FS, places=6)
        self.assertLess(len(y), 48_000 * 2 + int(GAP_FILL_S * FS))

    def test_a_loop_moves_on_by_whole_minutes(self):
        # FT8 slots (and their even/odd parity) keep their second of the
        # minute, and time never runs backwards.
        x = tone(48_000, 1_000.0)
        d = self.play(record(self.dir / "l", [(x, 100e6, T0)]), tune=100e6, loop=True)
        first = d.read(4800)
        for _ in range(9):
            d.read(4800)
        end_first = d.utc_end
        again = d.read(4800)
        np.testing.assert_allclose(again, first, atol=1e-6)
        self.assertEqual(d.loops, 1)
        self.assertAlmostEqual(d.utc_end - (T0 + 4800 / FS), LOOP_STEP_S, places=6)
        self.assertGreater(d.utc_end, end_first)
        self.assertAlmostEqual(d.recorded_utc(), T0 + 4800 / FS, places=6)

    def test_without_a_loop_the_end_is_silence_and_says_so(self):
        d = self.play(record(self.dir / "s", [(tone(4800, 0.0), 100e6, T0)]), tune=100e6)
        d.read(4800)
        self.assertTrue(d.ended)
        self.assertTrue(np.all(d.read(4800) == 0))
        self.assertTrue(d.status()["ended"])
        d.loop = True                               # looping switched on afterwards starts it again
        self.assertGreater(np.abs(d.read(4800)).min(), 0.2)

    def test_real_time_is_paced(self):
        d = self.play(record(self.dir / "p", [(tone(24_000, 0.0), 100e6, T0)]), tune=100e6)
        d.realtime = True
        t = time.monotonic()
        for _ in range(5):
            d.read(4800)                            # 0.5 s of samples
        self.assertGreater(time.monotonic() - t, 0.4)

    def test_cf32_ci8_and_cu8_from_other_programs(self):
        x = tone(4800, 2_000.0, amp=0.5)
        inter = np.empty(2 * len(x), np.float32)
        inter[0::2], inter[1::2] = x.real, x.imag
        cases = {"cf32_le": (inter.astype("<f4"), 1e-6),
                 "ci8": (np.round(inter * 128).astype("i1"), 1 / 128),
                 "cu8": (np.round(inter * 127.5 + 127.5).astype("u1"), 1 / 120)}
        for dt, (comps, tol) in cases.items():
            with self.subTest(dt):
                # Another program's namespace, never declared: still plays.
                d = self.play(hand_made(self.dir / dt, comps, dt, g={"acme:gain": 3}), tune=1e6)
                y = d.read(4800)
                np.testing.assert_allclose(y, x, atol=tol)

    def test_an_inverted_recording_plays_the_right_way_up(self):
        x = tone(48_000, -4_000.0)                  # mirrored: on the air it was +4 kHz
        d = self.play(record(self.dir / "i", [(x, 100e6, T0)], meta={"openhamshack:inverted": True}), tune=100e6)
        self.assertAlmostEqual(peak_hz(d.read(48_000)), 4_000.0, delta=2)

    def test_the_hand_made_recordings_frequency_is_the_lnbs_output(self):
        # Before the recorder existed (07/10/2026), core:frequency held the
        # SDR's frequency and openhamshack:lnb_lo_hz the LNB.
        comps = np.zeros(9600, "<i2")
        path = hand_made(self.dir / "hm", comps, "ci16_le", g={"openhamshack:lnb_lo_hz": 9_750e6},
                         caps=[{"core:sample_start": 0, "core:frequency": 739.771e6,
                                "core:datetime": sigmf.iso_utc(T0)}])
        d = self.play(path, conv=Converter("LNB", rx_offset=9_750e6), tune=739.771e6)
        self.assertEqual(d.segs[0].air, 10_489.771e6)

    def test_what_cannot_be_played_is_a_sentence(self):
        good = record(self.dir / "ok", [(tone(480, 0.0), 1e6, T0)])
        sigmf.paths(good)[0].unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            FileDevice(good)
        with self.assertRaisesRegex(ValueError, "missing"):
            FileDevice(self.dir / "nothing.sigmf-meta")
        with self.assertRaisesRegex(ValueError, "cannot be played"):
            FileDevice(hand_made(self.dir / "r", np.zeros(10, "<f4"), "rf32_le"))
        with self.assertRaisesRegex(ValueError, "channels"):
            FileDevice(hand_made(self.dir / "two", np.zeros(10, "<i2"), "ci16_le", g={"core:num_channels": 2}))
        with self.assertRaisesRegex(ValueError, "no samples"):
            FileDevice(hand_made(self.dir / "empty", np.zeros(0, "<i2"), "ci16_le"))


def wait_saved(radio, timeout=10.0):
    deadline = time.monotonic() + timeout
    while radio.rec_closing and time.monotonic() < deadline:
        radio.heartbeat()
        time.sleep(0.02)


def play_to_end(radio, feeds=(), timeout=120.0):
    got = run_sim(radio, 1e9, feeds, until=lambda: radio.state()["playEnded"], timeout=timeout)
    time.sleep(0.3)                                  # the supervisor's last tick and the decoders' last word
    for f in feeds:
        got[f.kind] += f.drain()
    return got


class NbPlayback(unittest.TestCase):
    """Recorded from the simulator, played back through OpenHamShack NB."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def record_sim(self, seconds, before=None, during=None, **over):
        """Record `seconds` of the simulator (after `before(radio)`, with
        `during(radio)` called once recording); returns the .sigmf-data path."""
        r = make_radio(self.dir, **over)
        r.start()
        try:
            if before is not None:
                before(r)
            path = r.start_recording()
            if during is not None:
                during(r)
            run_sim(r, seconds)
            r.stop_recording()
            wait_saved(r)
        finally:
            r.stop()
        return path

    def player(self, **over):
        r = make_radio(self.dir, **over)
        self.addCleanup(r.stop)
        return r

    def test_record_then_play_gives_the_same_spectrum(self):
        # Beacon lock on Hold at the simulator's own error, so rxCorr - and
        # with it every bin's frequency - is the same live and played.
        kw = dict(beaconMode="hold", rxCorr=2_500.0)
        live = []

        def during(r):
            f = r.subscribe("wide", 500)
            live.append(f)

        path = self.record_sim(2.0, before=lambda r: run_sim(r, 0.5), during=during, **kw)
        live_lines = live[0].drain()
        r = self.player(beaconMode="hold", rxCorr=0.0)
        wide = r.subscribe("wide", 500)
        r.start_playback(path, realtime=False)
        self.assertEqual(r.state()["rxCorr"], 2_500.0)         # seeded from the recording
        played = play_to_end(r, [wide])["wide"]
        self.assertGreater(len(played), 20)
        # Lines of the recording itself: not the scope filling at the start,
        # nor the silence after the end.
        played = [ln for ln in played[3:] if np.median(ln[3]) > -150]
        a = np.mean([ln[3] for ln in live_lines[3:]], axis=0)
        b = np.mean([ln[3] for ln in played], axis=0)
        self.assertEqual(live_lines[-1][1:3], played[-1][1:3])  # the same first bin and bin width
        # The beacons, in the same bins - to one bin: the middle beacon has
        # carried real text since 48d284a (devices/midbeacon.py), a flat-
        # topped BPSK whose two strongest bins are within a hair of each
        # other, so which wins its top-3 place changed from run to run.
        top_a = sorted(np.argsort(a)[-3:])
        top_b = sorted(np.argsort(b)[-3:])
        for ka, kb in zip(top_a, top_b):
            self.assertLessEqual(abs(int(ka) - int(kb)), 1, (top_a, top_b))
        # And at the same level: summed over the signal (+-3 bins), not one
        # bin, since text moves the middle beacon's power about its lobe
        # (a bin by ~2 dB between two windows) but not its total. Summed in
        # each line and then averaged over the lines, not summed from the
        # lines' averaged spectrum: playback's FFT frames can fall at a
        # different sample phase from the live ones, and then a steady
        # beacon's shape alternates between two forms line by line (its
        # total in each line unchanged, to 0.1 dB). An average of dB
        # spectra is not an average of power, so the two forms made the
        # summed level 0.4 dB low on the upper beacon and up to 1.3 dB on the
        # middle one in about half the runs (12/10/2026, found by release.sh
        # nb 0.1.15), while every line agreed with its live twin.
        def level(lines, k):
            return float(np.mean([10 * np.log10(np.sum(10 ** (np.asarray(ln[3])[max(k - 3, 0):k + 4] / 10)))
                                  for ln in lines]))
        for k in top_a:
            self.assertAlmostEqual(level(live_lines[3:], k), level(played, k), delta=0.5)
        self.assertLess(float(np.median(np.abs(a - b))), 1.0)  # and the noise between them

    def test_psk31_recorded_from_the_air_decodes_on_playback(self):
        text = "CQ CQ DE GM4BRI GM4BRI PSE K"

        def before(r):
            if not r.state()["modes"]["psk31"]["encode"]:
                self.skipTest("PSK31 not available: " + r.state()["modes"]["psk31"]["missing"])
            self.assertTrue(wait_rx_lock(r))

        def during(r):
            run_sim(r, 1.0)
            r.send("psk31", text=text)
            run_sim(r, 20.0, until=lambda: not r.state()["keyed"])

        path = self.record_sim(1.5, before=before, during=during, mode="psk31", vfo=10_489_560_000.0,
                               simUlErrorHz=6.0, sampleRate=600_000)
        # The player starts somewhere else entirely; the recording brings its dial and mode.
        r = self.player(mode="usb", vfo=10_489_700_000.0)
        ev = r.subscribe("events", 500)
        r.start_playback(path, realtime=False)
        self.assertEqual((r.state()["mode"], r.state()["vfo"]), ("psk31", 10_489_560_000.0))
        got = play_to_end(r, [ev])["events"]
        heard = "".join(e.get("text", "") for e in got if e.get("mode") == "psk31")
        self.assertIn(text, heard)

    def test_ft8_decodes_on_playback_in_the_slot_it_was_sent_in(self):
        from ohsnb.devices.sim import FT8Activity

        def before(r):
            if not r.state()["modes"]["ft8"]["decode"]:
                self.skipTest("FT8 decoder not available: " + r.state()["modes"]["ft8"]["missing"])
            # To just before a slot begins on the simulator's clock, so one
            # slot's worth of file holds a whole slot.
            d = r.dev
            run_sim(r, 15.0 - (d.t_epoch + d.n / d.fs) % 15.0 - 0.3)

        path = self.record_sim(15.6, before=before, mode="ft8", vfo=10_489_540_000.0, simSignals=True,
                               sampleRate=600_000)
        start = sigmf.parse_utc(json.loads(sigmf.paths(path)[1].read_text())["captures"][0]["core:datetime"])
        # The slot boundary nearest the recording's start. Aimed 0.3 s
        # before it, but run_sim only stops at a heartbeat - 1.2 s of signal
        # apart on an M4 Mac running the simulator unpaced - so the start
        # can land just after the boundary too, and that slot's
        # transmission (from 0.5 s in) is still the one in the file.
        slot = round(start / 15) * 15
        r = self.player()
        ev = r.subscribe("events", 500)
        r.start_playback(path, realtime=False)
        got = play_to_end(r, [ev])["events"]
        t0 = time.monotonic()
        while time.monotonic() - t0 < 10 and not any(e.get("mode") == "ft8" and e.get("text") for e in got):
            time.sleep(0.2)
            r.heartbeat()
            got += ev.drain()
        ft8 = [e for e in got if e.get("mode") == "ft8" and e.get("text")]
        self.assertTrue({e["text"] for e in ft8} & set(FT8Activity.MESSAGES), [e.get("text") for e in ft8])
        # In the slot it was sent in, by the recording's clock - not now.
        self.assertEqual({float(e["slot"]) for e in ft8}, {slot})

    def test_transmit_is_refused_and_says_why(self):
        path = self.record_sim(0.3)
        r = self.player()
        r.start_playback(path, realtime=False)
        st = r.state()
        self.assertFalse(st["canTx"])
        self.assertIn("Playing a recording", st["txBlocked"])
        with self.assertRaisesRegex(TxRefused, "Playing a recording"):
            r.ptt(True)
        with self.assertRaisesRegex(ValueError, "go back to the radio"):
            r.start_recording()

    def test_the_operators_corrections_are_not_the_recordings(self):
        # Their own rxCorr (Ray's LNB, -27 kHz) is saved; someone else's
        # recording (+2.5 kHz) plays and beacon lock follows it; a save in
        # the middle - or a crash - must still have theirs on disk, and
        # going back to the radio gives it back.
        path = self.record_sim(1.0, before=lambda r: wait_rx_lock(r))
        conf = self.dir / "config.json"
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        from helpers import sim_cfg
        cfg = sim_cfg(rxCorr=-27_454.0, rxCorrHand=False, vfo=10_489_650_000.0)
        r = Radio(cfg, conf_path=conf, data_dir=self.dir, audio=NullAudio(realtime=False))
        self.addCleanup(r.stop)
        r.start()
        r._save(force=True)
        r.start_playback(path, realtime=False)
        self.assertTrue(r.state()["playing"])
        self.assertAlmostEqual(r.state()["rxCorr"], 2_500.0, delta=100)
        lock = r.subscribe("lock", 500)
        got = play_to_end(r, [lock])["lock"]
        # Locked while the recording played (after its end, in the silence,
        # the lock is rightly lost - how soon depends on the machine's speed).
        # The first lock, not the last: past the end, before the lock is
        # lost, the tracker's last reports wander on silence, and how many
        # it makes first depends on the machine too (an M4 Mac's last was
        # 21.8 Hz out).
        locked = [m for m in got if m.get("kind") == "rx" and m.get("state") == "locked"]
        self.assertTrue(locked)
        self.assertAlmostEqual(float(locked[0]["rxCorr"]), 2_500.0, delta=20)
        r.set(filterHi=2_600.0)                      # an operator's change while playing is still theirs
        r._save(force=True)
        disk = json.loads(conf.read_text())
        self.assertEqual(disk["rxCorr"], -27_454.0)
        self.assertEqual(disk["vfo"], 10_489_650_000.0)
        self.assertEqual(disk["filterHi"], 2_600.0)
        # The end of a recording is silence: receive carries on, beacon lock
        # loses the beacon rather than failing.
        self.assertEqual(r.state()["error"], "")
        r.stop_playback()
        st = r.state()
        self.assertFalse(st["playing"])
        self.assertTrue(st["running"])
        self.assertEqual(r.dev.kind, "sim")
        self.assertTrue(st["canTx"])
        self.assertEqual(st["rxCorr"], -27_454.0)
        self.assertEqual(st["vfo"], 10_489_650_000.0)
        r.stop()
        self.assertEqual(json.loads(conf.read_text())["rxCorr"], -27_454.0)

    def test_a_recording_that_does_not_start_leaves_the_radio_as_it_was(self):
        # Recorded at 10 GHz of somewhere else entirely: nothing NB tunes is in it.
        x = tone(4800, 0.0, fs=1_200_000.0)
        path = record(self.dir / "far", [(x, 10_368.1e6, T0)], fs=1_200_000.0)
        r = self.player(vfo=10_489_650_000.0)
        r.start()
        with self.assertRaisesRegex(ValueError, "outside the recording"):
            r.start_playback(path, realtime=False)
        st = r.state()
        self.assertFalse(st["playing"])
        self.assertTrue(st["running"])
        self.assertEqual(r.dev.kind, "sim")
        self.assertEqual(st["vfo"], 10_489_650_000.0)


class HamPlayback(unittest.TestCase):
    def test_a_band_recording_plays_and_another_band_is_refused(self):
        from ham_helpers import close, make_radio as ham_radio, pump
        rec = ham_radio(vfo=144_300_000.0, mode="usb")
        self.addCleanup(close, rec)             # the recording lives in its data folder
        rec.start()
        pump(rec, 0.3)
        path = rec.start_recording()
        pump(rec, 0.6)
        centre = rec.centre
        rec.stop()
        r = ham_radio(vfo=7_100_000.0, mode="lsb")
        try:
            r.start_playback(path, realtime=False)
            st = r.state()
            self.assertEqual((st["band"], st["vfo"], st["mode"]), ("2m", 144_300_000.0, "usb"))
            self.assertEqual(r.centre, centre)                 # the same span as was recorded
            self.assertEqual(r.dev.kind, "file")
            with self.assertRaisesRegex(ValueError, "outside it"):
                r.set(vfo=432_200_000.0)
            r.set(vfo=144_250_000.0)                           # inside it, fine
            pump(r, 5.0, until=lambda: r.state()["playEnded"])
            self.assertTrue(r.state()["playEnded"])
            r.stop_playback()
            st = r.state()
            self.assertEqual((st["vfo"], st["mode"]), (7_100_000.0, "lsb"))
            self.assertEqual(r.dev.kind, "sim")
        finally:
            close(r)


if __name__ == "__main__":
    unittest.main()
