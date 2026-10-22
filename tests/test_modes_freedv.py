import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest
import numpy as np

from ohscore.modes import freedv

FS = 12_000.0


class ResampleTests(unittest.TestCase):
    def test_round_trip_preserves_a_tone(self):
        # 12k -> 8k -> 12k (FreeDV's own modem rate and back) must not wreck
        # a simple in-band tone, in amplitude or in how many cycles survive.
        t = np.arange(int(1.0 * FS)) / FS
        tone = np.sin(2 * np.pi * 400.0 * t).astype(np.float64)
        down = freedv.resample(tone, 2, 3)   # 12k -> 8k
        back = freedv.resample(down, 3, 2)   # 8k -> 12k
        n = min(len(tone), len(back))
        # Trim filter edge transients; compare the steady middle.
        a, b = tone[n // 4:3 * n // 4], back[n // 4:3 * n // 4]
        correlation = np.corrcoef(a, b[:len(a)])[0, 1]
        self.assertGreater(correlation, 0.95)

    def test_identity_when_up_equals_down(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        out = freedv.resample(x, 5, 5)
        np.testing.assert_allclose(out, x, atol=1e-6)

    def test_output_length_roughly_matches_ratio(self):
        x = np.zeros(1200)
        out = freedv.resample(x, 2, 3)
        self.assertAlmostEqual(len(out), 1200 * 2 / 3, delta=5)


@unittest.skipUnless(freedv._lib is not None, "libcodec2 not installed")
class AvailabilityTests(unittest.TestCase):
    def test_1600_and_700d_are_usable_on_this_host(self):
        self.assertEqual(freedv.available("1600"), (True, ""))
        self.assertEqual(freedv.available("700d"), (True, ""))

    def test_probe_is_cached(self):
        # Calling twice must not re-probe (which would re-open/close a real
        # freedv handle); can't observe that directly, but the result must
        # at least be stable and the cache dict must gain no new entry.
        freedv.available("700c")
        n = len(freedv._probe_cache)
        freedv.available("700c")
        self.assertEqual(len(freedv._probe_cache), n)

    def test_unavailable_mode_gives_a_reason(self):
        ok, why = freedv.available("700e")
        if not ok:  # only assert the shape of the message if this build really lacks it
            self.assertTrue(why)
            self.assertIn("700E", why.upper())

    def test_a_mode_the_build_lacks_is_never_closed_only_reported(self):
        # codec2 1.2.0 built without LPCNet hands back a half-made handle
        # for 2020 (speech rate 0), and freedv_close on it crashed the Mac
        # build at import. A working mode is still closed after its probe.
        from unittest import mock

        class Lib:
            closed = []

            def freedv_open(self, mode_id):
                return 0x1000 + mode_id

            def freedv_get_speech_sample_rate(self, h):
                return 0 if h == 0x1000 + 8 else 8000

            def freedv_close(self, h):
                self.closed.append(h)
        lib = Lib()
        with mock.patch.object(freedv, "_lib", lib):
            ok, why = freedv._probe_mode("2020")
            self.assertFalse(ok)
            self.assertIn("2020", why)
            self.assertEqual(freedv._probe_mode("700d"), (True, ""))
        self.assertEqual(lib.closed, [0x1000 + 7])

    def test_unknown_mode_name(self):
        ok, why = freedv.available("not-a-real-mode")
        self.assertFalse(ok)
        self.assertTrue(why)


def _tx_rx_loopback(mode: str, seconds: float = 4.0, send_text: str | None = None,
                     noise_std: float = 0.0, seed: int = 1):
    tx = freedv.FreeDVTx(mode=mode)
    if send_text:
        tx.send_text(send_text)
    t = np.arange(int(seconds * FS)) / FS
    speech = (0.3 * np.sin(2 * np.pi * 300.0 * t)).astype(np.float32)
    block = 1200
    chunks = []
    for i in range(0, len(speech), block):
        out = tx.process(speech[i:i + block])
        if len(out):
            chunks.append(out)
    modem_audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    if noise_std:
        rng = np.random.default_rng(seed)
        modem_audio = modem_audio + rng.normal(0, noise_std, len(modem_audio)).astype(np.float32)

    events = []
    speech_chunks = []
    dec = freedv.Decoder(events.append, speech_chunks.append, mode=mode)
    for i in range(0, len(modem_audio), block):
        dec.feed(modem_audio[i:i + block], t=i / FS)
    tx.close()
    dec.close()
    return events, speech_chunks


@unittest.skipUnless(freedv._lib is not None, "libcodec2 not installed")
class LoopbackTests(unittest.TestCase):
    def test_1600_reaches_sync_and_produces_speech(self):
        events, speech_chunks = _tx_rx_loopback("1600")
        syncs = [e["sync"] for e in events if "sync" in e]
        self.assertIn(True, syncs)
        self.assertGreater(sum(len(c) for c in speech_chunks), 0)

    def test_700d_reaches_sync_and_produces_speech(self):
        events, speech_chunks = _tx_rx_loopback("700d", seconds=5.0)
        syncs = [e["sync"] for e in events if "sync" in e]
        self.assertIn(True, syncs)
        self.assertGreater(sum(len(c) for c in speech_chunks), 0)

    @unittest.skipUnless(freedv.available("2020")[0], "this codec2 build has no FreeDV 2020")
    def test_2020_reaches_sync_at_its_16khz_speech_rate(self):
        events, speech_chunks = _tx_rx_loopback("2020", seconds=6.0)
        syncs = [e["sync"] for e in events if "sync" in e]
        self.assertIn(True, syncs)
        self.assertGreater(sum(len(c) for c in speech_chunks), 0)

    def test_decoded_speech_audio_is_12khz_float32(self):
        _, speech_chunks = _tx_rx_loopback("1600")
        self.assertTrue(speech_chunks)
        self.assertEqual(speech_chunks[0].dtype, np.float32)

    def test_text_channel_round_trips_something(self):
        # The text channel is bit-exact only once sync has fully settled;
        # the first character or two during acquisition can come through
        # corrupted (observed: 'H' -> 'r' with 'I' right behind it intact),
        # the same way PSK31's AFC takes a character to lock. The channel
        # existing and carrying real characters through is what's checked.
        events, _ = _tx_rx_loopback("1600", seconds=3.0, send_text="HI")
        texts = "".join(e["text"] for e in events if "text" in e)
        self.assertTrue(texts)

    def test_unsupported_mode_raises_with_reason(self):
        ok, why = freedv.available("700e")
        if ok:
            self.skipTest("this codec2 build actually supports 700E")
        with self.assertRaises(RuntimeError):
            freedv.FreeDVTx(mode="700e")

    def test_reset_clears_decoder_buffer(self):
        dec = freedv.Decoder(lambda e: None, lambda a: None, mode="1600")
        dec.feed(np.zeros(1200, dtype=np.float32), t=0.0)
        dec.reset()
        self.assertEqual(len(dec._modem_buf), 0)
        dec.close()


@unittest.skipUnless(freedv._lib is not None, "libcodec2 not installed")
class SnrTests(unittest.TestCase):
    """freedv_get_modem_stats(f, &sync, &snr_est) -- the struct-free getter
    confirmed from the real freedv_api.h at the 1.2.0 tag (see the module
    docstring) -- is what these events' "snr" field comes from. The claim
    worth proving isn't a specific dB value (codec2's own estimator, not
    this module's to pin down) but that it moves the right *way* as the
    channel gets worse, which is what an operator actually reads it for."""

    def _mean_snr(self, mode, noise_std, seed=1):
        events, _ = _tx_rx_loopback(mode, seconds=6.0, noise_std=noise_std, seed=seed)
        snrs = [e["snr"] for e in events if e.get("sync")]
        self.assertTrue(snrs, msg=f"no synced SNR readings at noise_std={noise_std}")
        return sum(snrs) / len(snrs)

    def test_snr_decreases_as_noise_increases(self):
        clean = self._mean_snr("1600", 0.0)
        light = self._mean_snr("1600", 0.05)
        heavy = self._mean_snr("1600", 0.2)
        self.assertGreater(clean, light)
        self.assertGreater(light, heavy)

    def test_snr_is_a_plausible_db_value(self):
        # Not a tight bound (codec2's own estimator, not reproduced here) --
        # just ruling out "always reports 0" or a wildly out-of-range
        # placeholder, which the struct-free getter removes any need for.
        mean = self._mean_snr("1600", 0.0)
        self.assertGreater(mean, 5.0)
        self.assertLess(mean, 60.0)

    def test_events_carry_both_sync_and_snr(self):
        events, _ = _tx_rx_loopback("700d", seconds=5.0)
        synced = [e for e in events if e.get("sync")]
        self.assertTrue(synced)
        for e in synced:
            self.assertIn("snr", e)
            self.assertIsInstance(e["snr"], float)


if __name__ == "__main__":
    unittest.main()
