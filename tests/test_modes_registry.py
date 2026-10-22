import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest
import numpy as np

from ohscore.modes import MODES, ModeInfo


class RegistryShapeTests(unittest.TestCase):
    def test_every_entry_is_a_mode_info_with_required_fields(self):
        for mode_id, info in MODES.items():
            self.assertIsInstance(info, ModeInfo)
            self.assertEqual(info.id, mode_id)
            # "data": HSmodem's files, pictures and messages (07/10).
            self.assertIn(info.kind, ("voice", "text", "slot", "image", "data"))
            self.assertIsInstance(info.available, bool)
            self.assertIsInstance(info.why, str)

    def test_unavailable_entries_have_a_why_sentence(self):
        for info in MODES.values():
            if not info.available:
                self.assertTrue(info.why, msg=f"{info.id} is unavailable but has no why sentence")

    def test_available_entries_have_no_why_sentence(self):
        for info in MODES.values():
            if info.available:
                self.assertEqual(info.why, "", msg=info.id)

    def test_core_modes_are_registered(self):
        for expected in ("cw", "rtty", "psk31", "psk63", "psk125", "ft8", "ft4", "sstv"):
            self.assertIn(expected, MODES)

    def test_passband_is_a_sane_increasing_pair(self):
        for info in MODES.values():
            lo, hi = info.passband_hz
            self.assertLess(lo, hi)
            self.assertGreater(lo, 0)


class RegistryFactoryTests(unittest.TestCase):
    def test_cw_factories_work_through_the_registry(self):
        info = MODES["cw"]
        audio = info.make_encoder(text="E")
        self.assertGreater(len(audio), 0)
        events = []
        dec = info.make_decoder(events.append)
        dec.feed(audio, t=0.0)  # must not raise

    def test_psk_variant_is_baked_into_the_registry_entry(self):
        # psk31/63/125 all wrap the same psk.py Decoder/Encoder; the
        # registry's job is picking the right `variant` for each id so a
        # caller doesn't have to know psk.py's own kwarg names.
        audio31 = MODES["psk31"].make_encoder(text="E")
        audio63 = MODES["psk63"].make_encoder(text="E")
        self.assertNotEqual(len(audio31), len(audio63))

    def test_sstv_factories_work_through_the_registry(self):
        info = MODES["sstv"]
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        audio = info.make_encoder(image=img, mode="robot36")
        self.assertGreater(len(audio), 0)
        dec = info.make_decoder(lambda e: None, out_dir="/tmp")
        dec.feed(audio[:1200], t=0.0)  # must not raise

    @unittest.skipUnless(MODES["freedv_1600"].available, "codec2 not installed")
    def test_freedv_factory_returns_an_open_handle(self):
        tx = MODES["freedv_1600"].make_encoder()
        try:
            self.assertTrue(hasattr(tx, "process"))
        finally:
            tx.close()


if __name__ == "__main__":
    unittest.main()
