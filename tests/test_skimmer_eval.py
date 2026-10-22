import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""tools/skimmer_eval.py reads a recording's own rxCorr track from its
meta. Without it, a run over a recording NB made (17/10/2026) placed every
signal ~31 kHz too high, so the skimmer named the wrong things."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("skimmer_eval", Path(__file__).parent.parent / "tools" / "skimmer_eval.py")
skimmer_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skimmer_eval)


class Corr(unittest.TestCase):
    def test_the_meta_track_is_followed_in_seconds(self):
        meta = {"global": {"openhamshack:track": {"rxCorr": [[0, 30_728.0], [1_200_000, 30_738.0]]}}}
        c = skimmer_eval.Corr.from_meta(meta, 1_200_000.0)
        self.assertAlmostEqual(c(0.0), 30_728.0)
        self.assertAlmostEqual(c(0.5), 30_733.0)
        self.assertAlmostEqual(c(9.0), 30_738.0)      # held past the last point, as np.interp does

    def test_a_meta_without_a_track_gives_none(self):
        self.assertIsNone(skimmer_eval.Corr.from_meta({"global": {}}, 1_200_000.0))


if __name__ == "__main__":
    unittest.main()
