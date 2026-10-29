"""A fake SatDump 1.2.2 CLI for tests/test_ham_wxsat_decode.py: the tree
the real one writes for `satdump meteor_m2-x_lrpt baseband <in> <out>
...`, file for file and named as its source names them
(plugins/meteor_support/meteor/instruments/msumr/module_meteor_msumr_lrpt.cpp,
src-core/products/image_products.cpp, processor/image_processor.cpp),
chosen by the mode in fake.json beside the launcher, and a line in
runs.jsonl saying how it was run (argv, cwd, HOME, its nice value, the
settings.json and TLE file it was given, any proxy variable).

Modes: `day` (channels 1, 2 and 5: the 221 composite, thermal IR, MSA,
projected 221 and IR), `night` (channels 4 and 5), `short` (a lock of 20
lines), `nolock` (the tree the real SatDump 1.2.2 wrote on 29/10/2026 for
a real recording with no lock: an empty .cadu, dataset.json,
telemetry.json holding "null", MSU-MR/product.cbor, no picture; exit 0),
`crash` (its fatal-error line, exit 1), `slow` (sleeps first).

Not named test_*: the suite runs it only through the launcher a test
writes, and it must not import scratch_home - HOME is part of what it
reports.
"""
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

# The projection the fake writes: what SatDump's "auto" equirectangular
# would give a pass over Scotland, 2048 x 2048 pixels (here 256 x 256,
# eight times the degrees a pixel).
WEST, NORTH, SX, SY = -24.5, 71.25, 0.0175, 0.0125


def write_geotiff(path: Path, rgba16: np.ndarray, west: float, north: float, sx: float, sy: float,
                  nodata: str | None = None) -> None:
    """A GeoTIFF as SatDump's save_tiff writes one: little-endian,
    uncompressed, contiguous RGBA (extra sample: unassociated alpha) in
    strips, then ModelTiepoint (0, 0, 0, offset_x, offset_y, 0) and
    ModelPixelScale (scalar_x, -scalar_y, 0) - geotiff_write.cpp. Other
    sample counts and `nodata` (GDAL_NODATA, which SatDump does not write)
    are for the reader's tests of files without alpha."""
    h, w, c = rgba16.shape
    data = rgba16.astype("<u2").tobytes()
    rows = max(1, 8192 // (w * c * 2))
    strips = [data[i * w * c * 2 * rows:(i + 1) * w * c * 2 * rows] for i in range((h + rows - 1) // rows)]
    out = bytearray(b"II*\0" + struct.pack("<I", 0))
    offs = []
    for s in strips:
        offs.append(len(out))
        out += s
    tags = [(256, 4, [w]), (257, 4, [h]), (258, 3, [16] * c), (259, 3, [1]), (262, 3, [2]), (273, 4, offs),
            (274, 3, [1]), (277, 3, [c]), (278, 4, [rows]), (279, 4, [len(s) for s in strips]), (284, 3, [1]),
            (338, 3, [2]), (33550, 12, [sx, sy, 0.0]), (33922, 12, [0.0, 0.0, 0.0, west, north, 0.0]),
            (34735, 3, [1, 1, 0, 0])]
    if c in (1, 3):
        tags = [t for t in tags if t[0] != 338]
    if nodata is not None:
        tags.append((42113, 2, list(nodata.encode("ascii") + b"\0")))
    code = {2: "B", 3: "H", 4: "I", 12: "d"}
    ifd_at = len(out)
    entries = b""
    tail_at = ifd_at + 2 + 12 * len(tags) + 4
    tail = b""
    for tag, typ, vals in tags:
        raw = struct.pack("<" + code[typ] * len(vals), *vals)
        if len(raw) <= 4:
            entries += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
        else:
            entries += struct.pack("<HHII", tag, typ, len(vals), tail_at + len(tail))
            tail += raw
    out += struct.pack("<H", len(tags)) + entries + struct.pack("<I", 0) + tail
    struct.pack_into("<I", out, 4, ifd_at)
    path.write_bytes(bytes(out))


def main() -> None:
    from PIL import Image

    here = Path(sys.argv[0]).resolve().parent
    cfg = json.loads((here / "fake.json").read_text())
    args = sys.argv[1:]
    pipeline, level, infile, out = args[:4]
    flags = dict(zip(args[4::2], args[5::2]))
    cwd = Path.cwd()
    seen = {"argv": sys.argv, "cwd": str(cwd), "home": os.environ.get("HOME"), "nice": os.getpriority(os.PRIO_PROCESS, 0),
            "settings": json.loads((cwd / "settings.json").read_text()) if (cwd / "settings.json").exists() else None,
            "tle": Path(flags["--tle_override"]).read_text() if "--tle_override" in flags else None,
            "proxy": [k for k in os.environ if k.lower().endswith("_proxy")]}
    with open(here / "runs.jsonl", "a") as f:
        f.write(json.dumps(seen) + "\n")
    mode = cfg["mode"]
    print("[06:12:45 - 29/10/2026] (I) Starting SatDump v1.2.2")
    if mode == "slow":
        time.sleep(cfg.get("sleep", 30))
    if mode == "crash":
        print("[06:12:45 - 29/10/2026] \x1b[31m(E) Fatal error running pipeline : Could not open input file\x1b[0m")
        sys.exit(1)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    msu = out / "MSU-MR"
    msu.mkdir()
    (out / "meteor_m2-x_lrpt.soft").write_bytes(b"\0" * 4096)
    chans = {"day": [1, 2, 5], "night": [4, 5], "short": [1, 2, 5], "nolock": [], "slow": [1, 2, 5]}[mode]
    lines = 20 if mode == "short" else 600
    (out / "meteor_m2-x_lrpt.cadu").write_bytes(b"\x1a\xcf\xfc\x1d" * (2048 if chans else 0))
    (out / "dataset.json").write_text(json.dumps({"products": ["MSU-MR"], "satellite": "METEOR-M2 3" if chans else "Unknown Meteor",
                                                  "timestamp": 1792833561.0 if chans else 0.0}, indent=4))
    (out / "telemetry.json").write_text("null" if not chans else "{}")
    (msu / "product.cbor").write_bytes(b"\xa0")
    rng = np.random.default_rng(1)
    W = 1568
    for c in chans:
        Image.fromarray(rng.integers(0, 255, (lines, W), dtype=np.uint8), "L").save(msu / f"MSU-MR-{c}.png")

    def rgb(name, corrected=True, maps=False):
        a = rng.integers(0, 255, (lines, W, 3), dtype=np.uint8)
        Image.fromarray(a, "RGB").save(msu / f"msu_mr_rgb_{name}.png")
        if corrected:
            Image.fromarray(a[:, :1400], "RGB").save(msu / f"msu_mr_rgb_{name}_corrected.png")
        if maps:
            Image.fromarray(a, "RGB").save(msu / f"msu_mr_rgb_{name}_map.png")

    def grey16(name):
        a = (rng.integers(0, 65535, (lines, W), dtype=np.uint16) | 0xff00).astype(np.uint16)
        Image.fromarray(a, "I;16").save(msu / f"msu_mr_{name}.png")
        Image.fromarray(a[:, :1400], "I;16").save(msu / f"msu_mr_{name}_corrected.png")

    def proj(name):
        a = np.zeros((256, 256, 4), np.uint16)
        a[64:192, 32:224] = (65535, 32768, 0, 65535)
        write_geotiff(msu / f"rgb_msu_mr_{name}_projected.tif", a, WEST, NORTH, SX * 8, SY * 8)

    if {1, 2} <= set(chans):
        rgb("AVHRR_221_False_Color"); proj("rgb_AVHRR_221_False_Color")
        rgb("MSA", maps=True)
    if 5 in chans:
        grey16("10.8um_Thermal_IR_(Uncalibrated)"); proj("10.8um_Thermal_IR_(Uncalibrated)")
    if 4 in chans:
        grey16("3.9_um_Shortwave_IR_(Uncalibrated)")
    print("[06:12:54 - 29/10/2026] (I) Done! Goodbye")


if __name__ == "__main__":
    main()
