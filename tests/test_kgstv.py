import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""KG-STV (ohscore/dsp/kgstv.py): real frames off the air decode, pictures go
through the modulator and the receiver whole, and the receiver survives
what the band does to them (noise, an offset, a sound card's clock).

The format was settled on Brian's recording of 07/10 (docs/kgstv-research.md).
ON_AIR below are five frames from it, as the channel bits the receiver
sliced: tests that decode them hold the decoder to the real thing, not to
its own transmitter."""
import unittest

import numpy as np

from ohscore.dsp import kgstv

RATE = 12000.0

# (frame, its length in channel bits, the bits as hex, zero-padded at the end)
ON_AIR = {
    # DL4CQ, 17:13 UTC, MSK/NORM: his callsign frame...
    "dl4cq_call": (227, "0e12365aef3153f5d9fd4a7208cf6d4d89884c2d45d51115174aa53760"),
    # ...block (12, 0), black space, and block (0, 0), "DL4CQ" over it.
    "dl4cq_12_0": (259, "0e12365aef3153f5d98fc143c6cf6d4aceacf22c048399cd9e7e8c0d6802d75360"),
    "dl4cq_0_0": (571, "0e12365aef3153f5d98fc09208cf6d385fb5bf1844c399cf2a9524ef5a51ff1e4707f7041295f13caf7e9ab507"
                       "02ecafdc09beacb817dacf3e93444d24b8d4b9eb3dcb6ac1f3e6c0"),
    # VU2SAA, 15:28 UTC, MSK/CONV: the callsign frame and block (5, 7), both coded.
    "vu2saa_call": (587, "0e12365aef3153f5d9fcf42a08c9fba730d333c6c79b09243741ab25a663f4268479a6d35e228f7e801f8d8"
                         "65bd54a151eb6a34c7eafdc17c2dcd089fe5e93707dc70c9cb6fe4fb18960"),
    "vu2saa_5_7": (607, "0e12365aef3153b5d98e7ea3608155a72a8e7a762900f01a5ed74e764c824ce9b853831d82503bfe7145ae4f4a"
                        "30483706004440f0631b330e4bd2d96aeb3d4199c746889def06c749a6080c"),
}


def air_bits(name: str) -> np.ndarray:
    n, hx = ON_AIR[name]
    return np.unpackbits(np.frombuffer(bytes.fromhex(hx), np.uint8))[:n]


def receive(x, chunk=600):
    rx = kgstv.Receiver(RATE)
    ev = []
    for i in range(0, len(x), chunk):
        ev.extend(rx.feed(x[i:i + chunk]))
    return rx, ev


def frames(ev):
    return [e for e in ev if e["kind"] == "frame"]


def on_air(bits, rng=None, snr_db=None, offset_hz=0.0, clock_ppm=0.0, lead=0.2):
    """Channel bits modulated, with noise in front (a receiver tuning in),
    an offset, a sender whose clock is `clock_ppm` fast, and white noise
    at `snr_db` in 2.5 kHz."""
    rng = rng or np.random.default_rng(1)
    x = kgstv.modulate(np.concatenate([np.tile([0, 1], 64), bits, np.tile([0, 1], 64)]), RATE)
    if clock_ppm:
        t = np.arange(0, len(x) - 1, 1 + clock_ppm * 1e-6)
        i = t.astype(int)
        f = t - i
        x = x[i] * (1 - f) + x[i + 1] * f
    x = np.concatenate([np.zeros(int(lead * RATE), np.complex64), x])
    x = x * np.exp(2j * np.pi * offset_hz * np.arange(len(x)) / RATE)
    if snr_db is not None:
        npow = 10 ** (-snr_db / 10) * RATE / 2500.0
        x = x + (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(npow / 2)
    return x.astype(np.complex64)


def card(seed=3):
    """A 240x320 test card with edges, gradients and flat colour."""
    y, x = np.mgrid[0:kgstv.HEIGHT, 0:kgstv.WIDTH]
    img = np.zeros((kgstv.HEIGHT, kgstv.WIDTH, 3), np.float64)
    img[..., 0] = 255 * x / kgstv.WIDTH
    img[..., 1] = 255 * y / kgstv.HEIGHT
    img[..., 2] = np.where((x // 40 + y // 40) % 2, 220, 30)
    img[100:140, 60:260] = (250, 250, 250)
    return np.clip(img, 0, 255).astype(np.uint8)


class RealFrames(unittest.TestCase):
    """Frames from the recording, modulated again and received."""

    def test_dl4cqs_callsign(self):
        _, ev = receive(on_air(air_bits("dl4cq_call")))
        f = frames(ev)
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["command"], f[0]["mode"], f[0]["size"]), ("callsign", "MSK/NORM", 40))
        self.assertEqual(kgstv.text_of(f[0]["data"]), "DL4CQ")

    def test_black_space_is_black(self):
        # Block (12, 0) of DL4CQ's Earth picture is empty sky. Read with
        # JPEG's own rule for negative values it comes out grey (128 - 127
        # x 16 / 8 clipped, then wrong); KG-STV's rule makes it black.
        _, ev = receive(on_air(air_bits("dl4cq_12_0")))
        f = frames(ev)[0]
        self.assertEqual((f["command"], f["x"], f["y"], f["sc"]), ("image", 12, 0, 10))
        rgb = kgstv.decode_block(f["data"], f["sc"])
        self.assertLess(int(rgb.max()), 8)
        dc = [int(b[0, 0]) for b in kgstv.decode_mcu(f["data"])[:4]]
        self.assertEqual(dc, [-64] * 4)       # -1024 / 16: pixel 0, quantised at x1.0

    def test_a_block_parses_to_exactly_its_size(self):
        _, ev = receive(on_air(air_bits("dl4cq_0_0")))
        f = frames(ev)[0]
        self.assertEqual((f["x"], f["y"], f["size"]), (0, 0, 384))
        blocks = kgstv.decode_mcu(f["data"])
        self.assertEqual(len(blocks), 6)
        # And back again, bit for bit: the encoder is the decoder's inverse.
        self.assertTrue(np.array_equal(kgstv.encode_mcu(blocks), f["data"]))
        with self.assertRaises(ValueError):
            kgstv.decode_mcu(np.concatenate([f["data"], [1, 0]]))

    def test_vu2saas_coded_frames(self):
        _, ev = receive(on_air(air_bits("vu2saa_call")))
        f = frames(ev)[0]
        self.assertEqual(f["mode"], "MSK/CONV")
        self.assertEqual(kgstv.text_of(f["data"]).split(), ["VU2SAA", "Sam", "NK03CA"])
        _, ev = receive(on_air(air_bits("vu2saa_5_7")))
        f = frames(ev)[0]
        self.assertEqual((f["command"], f["x"], f["y"], f["coded"]), ("image", 5, 7, 1))
        self.assertEqual(kgstv.decode_block(f["data"], f["sc"]).shape, (16, 16, 3))

    def test_a_weak_wrong_bit_is_repaired(self):
        # Bit 300 (in the data chunk) received just the wrong side of the
        # centre: the CRC fails, and flipping the weakest bit mends it.
        bits = air_bits("dl4cq_0_0")
        _, ev = receive(on_air(bits))
        want = frames(ev)[0]["data"]
        lead = np.tile([0, 1], 64)
        f = np.where(np.concatenate([lead, bits, lead]) > 0, kgstv.DEV_HZ, -kgstv.DEV_HZ)
        k = len(lead) + 300
        f[k] = -20.0 if f[k] > 0 else 20.0
        f = np.repeat(f, int(RATE / kgstv.BAUD))
        x = np.exp(2j * np.pi * np.cumsum(f) / RATE).astype(np.complex64)
        rx, ev = receive(np.concatenate([np.zeros(2400, np.complex64), x]))
        got = frames(ev)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["repaired"])
        self.assertTrue(np.array_equal(got[0]["data"], want))
        self.assertEqual(rx.repaired, 1)


class Codes(unittest.TestCase):
    def test_a_chunk_and_its_crc_leave_zero(self):
        bits = np.random.default_rng(2).integers(0, 2, 200).astype(np.uint8)
        c = kgstv.with_crc(bits)
        self.assertEqual(kgstv.crc16(c), 0)
        c[17] ^= 1
        self.assertNotEqual(kgstv.crc16(c), 0)

    def test_the_viterbi_decoder_corrects_scattered_errors(self):
        bits = np.random.default_rng(3).integers(0, 2, 54).astype(np.uint8)
        sym = kgstv.conv_encode(bits).astype(float) * 2 - 1
        sym[[5, 40, 77]] *= -1
        out, agree = kgstv.viterbi(sym)
        self.assertTrue(np.array_equal(out, bits))
        self.assertLess(agree, 1.0)

    def test_the_information_chunk_round_trips(self):
        info = kgstv.unpack_info(kgstv.pack_info(1, x=19, y=14, size=4095, sc=15, coded=1, fsk4=0))
        self.assertEqual({k: info[k] for k in ("com", "x", "y", "size", "sc", "coded", "fsk4", "ok")},
                         {"com": 1, "x": 19, "y": 14, "size": 4095, "sc": 15, "coded": 1, "fsk4": 0, "ok": True})

    def test_coefficients_round_trip_through_the_entropy_coder(self):
        rng = np.random.default_rng(4)
        for _ in range(20):
            blocks = []
            for _ in range(6):
                b = np.zeros(64, np.int32)
                k = rng.choice(64, int(rng.integers(0, 64)), replace=False)
                b[k] = rng.integers(-300, 300, len(k))
                b[0] = rng.integers(-1000, 1000)
                blocks.append(b.reshape(8, 8))
            back = kgstv.decode_mcu(kgstv.encode_mcu(blocks))
            for a, b in zip(blocks, back):
                self.assertTrue(np.array_equal(a, b))

    def test_a_block_comes_back_close_to_what_was_sent(self):
        img = card()[96:112, 48:64]
        for sc in (3, 10, 15):
            back = kgstv.decode_block(kgstv.encode_block(img, sc), sc)
            err = np.abs(back.astype(int) - img.astype(int)).mean()
            self.assertLess(err, 6 + 4 * kgstv.SCALES[sc], sc)

    def test_a_rate_that_is_not_whole_samples_a_bit_works(self):
        # 15 kHz, 12.5 samples a bit (what some sample rates give the channel).
        x = kgstv.modulate(np.concatenate([np.tile([0, 1], 64), air_bits("dl4cq_call"), np.tile([0, 1], 64)]),
                           60000.0)
        rx = kgstv.Receiver(15000.0)
        ev = rx.feed(x[:len(x) // 4 * 4].reshape(-1, 4).mean(1).astype(np.complex64))
        self.assertEqual([kgstv.text_of(e["data"]) for e in frames(ev)], ["DL4CQ"])

    def test_too_few_samples_a_bit_is_refused(self):
        with self.assertRaises(ValueError):
            kgstv.Receiver(4000.0)


class WholePictures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = card()
        cls.bits = kgstv.transmission_bits("G0ABC", cls.img)
        cls.ref = np.zeros_like(cls.img)
        for by in range(kgstv.BLOCKS_Y):
            for bx in range(kgstv.BLOCKS_X):
                sl = np.s_[by * 16:(by + 1) * 16, bx * 16:(bx + 1) * 16]
                cls.ref[sl] = kgstv.decode_block(kgstv.encode_block(cls.img[sl], 10), 10)

    def picture(self, x):
        rx, ev = receive(x, chunk=2400)
        pics = kgstv.Pictures()
        out = []
        for e in ev:
            out += pics.frame(e)
        out += pics.tick(rx.samples / RATE + 60)
        return rx, out

    def test_a_picture_arrives_whole_with_its_callsign(self):
        rx, out = self.picture(on_air(self.bits, snr_db=25.0))
        done = [e for e in out if e["kind"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["why"], done[0]["call"], done[0]["blocks"], done[0]["mode"]),
                         ("end", "G0ABC", 300, "MSK/NORM"))
        self.assertTrue(np.array_equal(done[0]["rgb"], self.ref))
        self.assertEqual(rx.lost, 0)
        self.assertEqual([e["call"] for e in out if e["kind"] == "call"], ["G0ABC"])

    def test_an_offset_and_a_fast_sound_card_cost_nothing(self):
        # 150 Hz off (an LNB not yet locked), and a sender's clock 300 ppm
        # fast: over a two-minute picture that is 50 bits of slip, which a
        # receiver that does not follow the clock loses blocks to.
        rx, out = self.picture(on_air(self.bits, snr_db=20.0, offset_hz=150.0, clock_ppm=300.0))
        done = [e for e in out if e["kind"] == "done"]
        self.assertEqual(done[0]["blocks"], 300)
        self.assertAlmostEqual(rx.freq, 150.0, delta=15.0)

    def test_tuning_in_halfway_gives_the_rest(self):
        x = on_air(self.bits, snr_db=25.0)
        rx, out = self.picture(x[len(x) // 2:])
        done = [e for e in out if e["kind"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertTrue(100 < done[0]["blocks"] < 200, done[0]["blocks"])
        blocks = [e for e in out if e["kind"] == "block"]
        self.assertEqual(blocks[-1]["y"], kgstv.BLOCKS_Y - 1)

    def test_noise_alone_gives_nothing(self):
        rng = np.random.default_rng(9)
        x = ((rng.standard_normal(int(60 * RATE)) + 1j * rng.standard_normal(int(60 * RATE))) * 0.5)
        rx, ev = receive(x.astype(np.complex64), chunk=2400)
        self.assertEqual(frames(ev), [])


class Assembly(unittest.TestCase):
    def block_ev(self, x, y, com=1, t=0.0):
        img = np.full((16, 16, 3), 40 + 10 * x, np.uint8)
        return {"kind": "frame", "com": com, "x": x, "y": y, "sc": 10, "data": kgstv.encode_block(img, 10),
                "t": t, "mode": "MSK/NORM"}

    def test_a_block_already_had_starts_the_next_picture(self):
        p = kgstv.Pictures()
        out = p.frame(self.block_ev(0, 0)) + p.frame(self.block_ev(1, 0)) + p.frame(self.block_ev(0, 0, t=5))
        kinds = [e["kind"] for e in out]
        self.assertEqual(kinds, ["start", "block", "block", "done", "start", "block"])
        self.assertEqual(out[3]["why"], "restart")

    def test_a_repeat_fills_a_hole_and_quiet_finishes(self):
        p = kgstv.Pictures()
        p.frame(self.block_ev(0, 0))
        p.frame(self.block_ev(2, 0, t=1))
        out = p.frame(self.block_ev(1, 0, com=2, t=2))
        self.assertEqual(out[-1]["blocks"], 3)
        self.assertEqual(p.tick(10.0), [])
        done = p.tick(40.0)
        self.assertEqual((done[0]["kind"], done[0]["why"], done[0]["blocks"]), ("done", "timeout", 3))

    def test_a_repeat_for_a_picture_never_seen_is_ignored(self):
        self.assertEqual(kgstv.Pictures().frame(self.block_ev(4, 4, com=2)), [])


if __name__ == "__main__":
    unittest.main()
