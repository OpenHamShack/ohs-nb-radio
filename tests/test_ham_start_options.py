"""Radio's --band, --mode and --rf on the command line (ohsradio/__main__.py,
Radio.start_on): run headless on the simulator from an empty config, as
tools/build-windows.ps1's smoke test does, and read back where it says the
dial is. Nothing keys: the headless run never transmits."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# A status line: "06:32:57 20m   FT8    14.074000 MHz seg ..."
STATUS = re.compile(r"^\d\d:\d\d:\d\d (?P<band>\S+)\s+(?P<mode>\S+)\s+(?P<mhz>\d+\.\d+) MHz", re.MULTILINE)


def run_headless(*args: str) -> list[tuple[str, str, float]]:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, OHS_RADIO_CONF=str(Path(tmp) / "config.json"), OHS_RADIO_DATA=str(Path(tmp) / "data"),
                   QT_QPA_PLATFORM="offscreen")
        res = subprocess.run([sys.executable, "-m", "ohsradio", "--headless", "--device", "sim", "--no-audio",
                              "--seconds", "3", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                             timeout=120)
    lines = [(m["band"], m["mode"], float(m["mhz"])) for m in STATUS.finditer(res.stdout)]
    assert res.returncode == 0 and lines, (res.returncode, res.stdout[-2000:], res.stderr[-2000:])
    return lines


class StartOptions(unittest.TestCase):
    def test_band_and_ft8_from_an_empty_config_land_on_the_ft8_dial(self):
        # HAM 0.1.18's Windows build stopped here: the band went first, so
        # 20 m's first visit landed on the SSB segment (14.125) in the start-up
        # mode and FT8 was then switched on there, where nothing decodes.
        for band, mode, mhz in run_headless("--band", "20m", "--mode", "ft8"):
            self.assertEqual((band, mode, mhz), ("20m", "FT8", 14.074))

    def test_a_mode_the_band_would_not_land_in_is_kept(self):
        # From CW a first visit lands in the SSB segment in USB; the
        # operator asked for CW, so CW it stays, on 20 m.
        for band, mode, _mhz in run_headless("--band", "20m", "--mode", "cw"):
            self.assertEqual((band, mode), ("20m", "CW"))

    def test_rf_wins_over_the_band_landing(self):
        for band, mode, mhz in run_headless("--band", "20m", "--mode", "ft8", "--rf", "14.080"):
            self.assertEqual((band, mode, mhz), ("20m", "FT8", 14.08))


if __name__ == "__main__":
    unittest.main()
