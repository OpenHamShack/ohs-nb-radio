import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The middle beacon's text (ohsnb/dsp/ao40.py, ohsnb/beacontext.py): AO-40
blocks modulated as DK0SB sends them come out of the decoder whole, the
simulator's middle beacon carries them, and the engine decodes them from
the wide IQ wherever the dial is.

The format itself was settled on a real recording (ao40.py's docstring);
these tests hold the decoder to it and keep it from regressing."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohsnb import beacontext
from ohsnb.devices import midbeacon
from ohsnb.dsp import ao40

RATE = 4000.0


def on_air(blocks, rng, snr_db=None, offset_hz=0.0, drift_hz_s=0.0, start=0.3, repeats=2):
    """`blocks` modulated at the receiver's rate (entered `start` of the way
    through, as a receiver tuning in would be), turned by a carrier offset
    and a drift, in white noise of `snr_db` in 1 kHz."""
    x = ao40.modulate(blocks, RATE)
    x = np.concatenate([x[int(len(x) * start):]] + [x] * repeats)
    t = np.arange(len(x)) / RATE
    x = x * np.exp(2j * np.pi * (offset_hz * t + 0.5 * drift_hz_s * t * t))
    if snr_db is not None:
        npow = 10 ** (-snr_db / 10) * RATE / 1000.0
        x = x + (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(npow / 2)
    return x.astype(np.complex64)


def decode(x, chunk=60):
    rx = ao40.Receiver(RATE)
    ev = []
    for i in range(0, len(x), chunk):
        ev.extend(rx.feed(x[i:i + chunk]))
    return rx, [e for e in ev if e["kind"] == "frame"]


TEXT = [ao40.block_text("K", ["HI de TEST (sim)", "second line", "x" * 70]),
        ao40.block_text("L", ["another block", "", "after a blank line"])]


class Format(unittest.TestCase):
    def test_a_block_followed_by_its_crc_checks_to_zero(self):
        # tlmspec section 7: "calculating a crcc of a block that already
        # includes a correct crcc ... results in a net crcc = 0".
        b = TEXT[0]
        c = ao40.crc16(b)
        self.assertEqual(ao40.crc16(b + bytes([c >> 8, c & 0xFF])), 0)
        self.assertNotEqual(ao40.crc16(b + bytes([c >> 8, c & 0xFF ^ 1])), 0)
        # The CRC-16/CCITT-FALSE check value, the variant gr-satellites uses.
        self.assertEqual(ao40.crc16(b"123456789"), 0x29B1)

    def test_a_frame_is_sync_block_crc_and_the_fill_msb_first(self):
        bits = ao40.frame_bits(TEXT[0])
        raw = np.packbits(bits).tobytes()
        self.assertEqual(raw[:4], bytes([0x39, 0x15, 0xED, 0x30]))
        self.assertEqual(raw[4:516], TEXT[0])
        self.assertEqual(ao40.crc16(raw[4:518]), 0)
        self.assertEqual(raw[518:], ao40.FILL_BYTES)

    def test_a_block_is_type_space_then_64_character_lines(self):
        b = TEXT[0]
        self.assertEqual(len(b), 512)
        p = ao40.parse_block(b)
        self.assertEqual(p["type"], "K")
        self.assertEqual(p["lines"][0], "K HI de TEST (sim)")
        self.assertEqual(p["lines"][1], "second line")
        self.assertEqual(p["lines"][2], "x" * 64)          # a long line is cut, not wrapped
        self.assertEqual(len(p["lines"]), 8)

    def test_highlighted_and_unprintable_characters(self):
        b = bytearray(TEXT[1])
        b[2] |= 0x80                                        # "Bit 7 set ... highlighted"
        b[5] = 0x07
        p = ao40.parse_block(bytes(b))
        self.assertEqual(p["lines"][0][2], "a")
        self.assertEqual(p["highlight"][0], [2])
        self.assertEqual(p["lines"][0][5], "·")


class Decoder(unittest.TestCase):
    def test_clean_blocks_decode_exactly(self):
        rx, frames = decode(on_air(TEXT, np.random.default_rng(1)))
        self.assertGreaterEqual(len(frames), 4)
        for f in frames:
            self.assertIn(f["block"], TEXT)
            self.assertFalse(f["repaired"])
        self.assertEqual({f["type"] for f in frames}, {"K", "L"})

    def test_carrier_offset_drift_and_noise(self):
        # The free-running LNB of 07/10 moved the beacon ~2 Hz a second; a
        # beacon 5 dB over the noise in 1 kHz still decodes every block.
        rx, frames = decode(on_air(TEXT, np.random.default_rng(2), snr_db=7.0, offset_hz=-140.0, drift_hz_s=2.0))
        self.assertGreaterEqual(len(frames), 4)
        self.assertTrue(all(f["block"] in TEXT for f in frames))
        self.assertEqual(rx.failed, 0)
        self.assertGreater(rx.snr_db, 8.0)

    def test_noise_alone_gives_nothing(self):
        rng = np.random.default_rng(3)
        x = (rng.standard_normal(int(60 * RATE)) + 1j * rng.standard_normal(int(60 * RATE))).astype(np.complex64)
        rx, frames = decode(x)
        self.assertEqual(frames, [])
        self.assertEqual(rx.state, "searching")

    def test_a_broken_block_is_counted_not_shown(self):
        x = on_air([TEXT[0]], np.random.default_rng(4), start=0.0, repeats=3)
        # Wipe a stretch in the middle of the second block's data.
        n = len(ao40.modulate([TEXT[0]], RATE))
        x[n + n // 3: n + n // 3 + 400] = 0
        rx, frames = decode(x)
        self.assertGreaterEqual(rx.failed, 1)
        self.assertTrue(all(f["block"] == TEXT[0] for f in frames))

    def test_a_lost_carrier_is_searched_for_again(self):
        rng = np.random.default_rng(5)
        x = on_air(TEXT, rng, snr_db=20.0, repeats=1)
        gap = (rng.standard_normal(int(10 * RATE)) * 0.05).astype(np.complex64)
        # The beacon comes back 150 Hz away: further than the loop follows.
        t = np.arange(len(x)) / RATE
        y = np.concatenate([x, gap, (x * np.exp(2j * np.pi * 150.0 * t)).astype(np.complex64)])
        rx = ao40.Receiver(RATE)
        got = []
        states = set()
        for i in range(0, len(y), 200):
            got += [e for e in rx.feed(y[i:i + 200]) if e["kind"] == "frame"]
            states.add(rx.state)
        self.assertIn("searching", states)
        late = [f for f in got if abs(f["freq"] - 150.0) < 5.0]
        self.assertTrue(late, [f["freq"] for f in got])

    def test_channel_steps_it_is_told_of_cost_nothing(self):
        # Beacon lock follows a drifting LNB (here 6 Hz/s) by moving rxCorr
        # in steps, 3 Hz every half second as on 07/10, and the channel
        # moves with it; once, a 40 Hz jump (a typed rxCorr). Told of each
        # step (retune), the decoder loses no block. (Not told, it lost one
        # in four on the real recording of 07/10; this synthetic one is
        # kinder than that, so only the told case is held to it.)
        x = on_air(TEXT, np.random.default_rng(7), snr_db=9.0, repeats=3)
        half = int(RATE / 2)
        t = np.arange(len(x)) / RATE
        steps = [3.0 + (40.0 if k == 60 else 0.0) for k in range(len(x) // half + 1)]
        steps[0] = 0.0
        chan = np.repeat(np.cumsum(steps), half)[:len(x)]
        # The beacon drifting up, seen through a channel that steps after it.
        ph = 2 * np.pi * (0.5 * 6.0 * t * t - np.cumsum(chan) / RATE)
        y = (x * np.exp(1j * ph)).astype(np.complex64)

        rx = ao40.Receiver(RATE)
        got = []
        for k in range(0, len(y), half):
            if k:
                rx.retune(steps[k // half])
            for i in range(k, min(k + half, len(y)), 100):
                got += [e for e in rx.feed(y[i:i + 100]) if e["kind"] == "frame"]
        self.assertEqual(rx.failed, 0)
        self.assertGreaterEqual(len(got), 6)
        self.assertTrue(all(g["block"] in TEXT for g in got))

    def test_one_wrong_symbol_is_repaired(self):
        # A flipped symbol is two wrong message bits after differential
        # decoding; the weakest symbol is flipped back when the CRC fails.
        x = on_air([TEXT[1]], np.random.default_rng(6), snr_db=30.0, start=0.0, repeats=2)
        rx = ao40.Receiver(RATE)
        n = len(ao40.modulate([TEXT[1]], RATE))
        sps = int(RATE / ao40.BAUD)
        # Symbol 600 of the second block's data (32 sync bits in), made weak and wrong.
        k = n + (32 + 600) * sps
        x[k:k + sps] *= -0.1
        frames = []
        for i in range(0, len(x), 60):
            frames += [e for e in rx.feed(x[i:i + 60]) if e["kind"] == "frame"]
        self.assertTrue(any(f["repaired"] and f["block"] == TEXT[1] for f in frames))
        self.assertTrue(all(f["block"] == TEXT[1] for f in frames))

    def test_a_rate_that_is_not_whole_samples_a_bit_is_refused(self):
        with self.assertRaises(ValueError):
            ao40.Receiver(4100.0)


class SimulatedBeacon(unittest.TestCase):
    def test_the_simulator_sends_k_l_m_n_and_says_it_is_the_simulator(self):
        x = midbeacon.template()
        # 12 kHz -> 4 kHz: every third sample after a crude low-pass is
        # enough here; the engine's channel does it properly.
        h = ao40.lowpass_fir(12000.0, 1200.0)
        y = np.convolve(np.concatenate([x, x]), h, "same")[::3].astype(np.complex64)
        rx, frames = decode(y)
        self.assertEqual({f["type"] for f in frames}, {"K", "L", "M", "N"})
        self.assertTrue(all(f["lines"][0].endswith("OPENHAMSHACK NB SIMULATOR - not DK0SB") for f in frames))
        self.assertEqual({f["block"] for f in frames}, set(midbeacon.blocks()))

    def test_a_block_every_25_seconds_as_dk0sb_sends(self):
        self.assertAlmostEqual(len(midbeacon.template()) / 12000.0 / 4, 25.4, delta=0.05)

    def test_it_is_the_simulators_middle_beacon(self):
        from ohsnb.devices.sim import SimDevice
        d = SimDevice({"simSeed": 7, "simSignals": False})
        d.open()
        mid = [s for s in d.stations if s.name == "middle beacon"]
        self.assertEqual(len(mid), 1)
        self.assertIs(mid[0].tpl, midbeacon.template())


class InTheRadio(unittest.TestCase):
    """The engine decodes the middle beacon's text from the wide IQ through
    its own channel, wherever the dial is, once beacon lock has it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.radio = None

    def tearDown(self):
        if self.radio is not None:
            self.radio.stop()
        self.tmp.cleanup()

    def test_blocks_arrive_while_tuned_elsewhere(self):
        r = self.radio = make_radio(Path(self.tmp.name), vfo=10_489_620_000.0, mode="usb", mmbDecode=False)
        f = r.subscribe("midtext", 64)
        r.start()
        seen: list = []

        def until():
            seen.extend(f.drain())
            # The feed is published before the status keys are: both.
            return len({e["type"] for e in seen}) >= 2 and r.state()["midTextFrames"] >= 2
        run_sim(r, 80.0, until=until, timeout=240)
        seen.extend(f.drain())
        types = {e["type"] for e in seen}
        self.assertGreaterEqual(len(types), 2, types)
        blocks = {k: ao40.parse_block(b)["text"] for k, b in zip("KLMN", midbeacon.blocks())}
        for e in seen:
            self.assertEqual(e["text"], blocks[e["type"]])
            self.assertGreater(e["t"], 0)
        st = r.state()
        self.assertEqual(st["midTextState"], "receiving")
        self.assertGreaterEqual(st["midTextFrames"], 2)
        self.assertGreater(st["midTextSnr"], 10.0)
        self.assertLess(abs(st["midTextFreq"]), 30.0)
        # The latest of each type is kept for the next session's view.
        saved = beacontext.saved_blocks(Path(self.tmp.name) / "midbeacon")
        self.assertEqual({k: v[0] for k, v in saved.items()}, {k: blocks[k] for k in types})

    def test_switched_off_it_costs_nothing_and_says_so(self):
        r = self.radio = make_radio(Path(self.tmp.name), midTextDecode=False, mmbDecode=False)
        f = r.subscribe("midtext", 64)
        r.start()
        run_sim(r, 3.0)
        self.assertEqual(f.drain(), [])
        self.assertIsNone(r.midtext)
        self.assertEqual(r.state()["midTextState"], "off")
        r.set(midTextDecode=True)
        run_sim(r, 2.0)
        self.assertIsNotNone(r.midtext)
        self.assertIn(r.state()["midTextState"], ("searching", "tracking", "receiving"))
        r.set(midTextDecode=False)
        run_sim(r, 1.0)
        self.assertIsNone(r.midtext)
        self.assertEqual(r.state()["midTextState"], "off")


if __name__ == "__main__":
    unittest.main()
