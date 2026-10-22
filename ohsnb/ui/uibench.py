"""How much the window costs per frame, for extrapolating to a Raspberry Pi.

    QT_QPA_PLATFORM=offscreen python3 -m ohsnb.ui.uibench [--seconds 10] [--size 1920x1080]

Runs the real window on the simulator in real time and reports, per frame:
the bridge pump (draining feeds, ingesting spectrum lines into both
waterfalls, every slot), each scope's paint, and a forced repaint of the
whole window; then the share of one CPU core the display takes at the
default 20 lines/s and a 30 Hz paint rate. The offscreen platform paints
with Qt's raster engine, which is also what a Pi's X11/Wayland session
uses for widgets, so the ratio carries over; DESIGN.md's rule of thumb is
that a Pi 400 is about five times slower than a desktop core.
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    secs = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 10.0
    size = argv[argv.index("--size") + 1] if "--size" in argv else "1920x1080"
    w, h = (int(x) for x in size.split("x"))
    tmp = tempfile.mkdtemp(prefix="ohsnb-bench-")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["OHS_NB_UI_CONF"] = str(Path(tmp) / "ui.json")

    from ohscore.audio import NullAudio
    from ohscore.ui.prefs import Prefs

    from .. import config, state
    from ..radio import Radio
    from . import build, make_app

    app = make_app(["bench"])
    cfg = state.defaults(("setting", "control"))
    cfg.update(device="sim", audioBackend="null", simSeed=5, vfo=10_489_700_000.0, mode="usb")
    radio = Radio(cfg, persist=False, data_dir=Path(tmp), audio=NullAudio(realtime=True))
    prefs = Prefs(config.CONFIG)
    prefs["welcomed"] = True
    win, bridge = build(radio, prefs)
    win.resize(w, h)
    win.show()

    pumps, wide_p, zoom_p = [], [], []
    orig_pump = bridge.pump

    def timed_pump():
        t0 = time.perf_counter()
        orig_pump()
        pumps.append((time.perf_counter() - t0) * 1000)

    bridge.timer.timeout.disconnect()
    bridge.timer.timeout.connect(timed_pump)
    for sc, store in ((win.wide, wide_p), (win.zoom, zoom_p)):
        orig = sc.paintEvent

        def paint(e, orig=orig, store=store):
            t0 = time.perf_counter()
            orig(e)
            store.append((time.perf_counter() - t0) * 1000)
        sc.paintEvent = paint

    def run(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.002)

    run(4.0)                      # let the radio lock and the levels settle
    pumps.clear(), wide_p.clear(), zoom_p.clear()
    lines0 = win.wide.wf.rows_total
    run(secs)
    lines = (win.wide.wf.rows_total - lines0) / secs
    full = []
    for _ in range(20):
        t0 = time.perf_counter()
        win.repaint()
        full.append((time.perf_counter() - t0) * 1000)

    def med(x):
        return statistics.median(x) if x else float("nan")

    def p95(x):
        return sorted(x)[int(0.95 * (len(x) - 1))] if x else float("nan")

    ing_w, ing_z = win.wide.cost_ingest, win.zoom.cost_ingest
    print(f"window {w}x{h}, {secs:.0f} s, {lines:.1f} spectrum lines/s per scope")
    print(f"  bridge pump (feeds + line ingest)  median {med(pumps):6.2f} ms   p95 {p95(pumps):6.2f} ms")
    print(f"  wide scope paint                   median {med(wide_p):6.2f} ms   p95 {p95(wide_p):6.2f} ms")
    print(f"  zoom scope paint                   median {med(zoom_p):6.2f} ms   p95 {p95(zoom_p):6.2f} ms")
    print(f"  line ingest  wide {ing_w:.2f} ms   zoom {ing_z:.2f} ms")
    print(f"  whole-window repaint               median {med(full):6.2f} ms")
    per_s = 30 * (med(wide_p) + med(zoom_p)) + 30 * med(pumps)
    print(f"  display cost at 30 Hz paint: {per_s / 10:.1f} % of one core here; "
          f"x5 for a Pi 400 -> {per_s / 2:.0f} % of one of its four cores")
    print(f"  one 30 Hz frame (pump + both scopes): {med(pumps) + med(wide_p) + med(zoom_p):.2f} ms here, "
          f"~{5 * (med(pumps) + med(wide_p) + med(zoom_p)):.1f} ms on a Pi 400 (budget 33 ms)")
    win.close()
    bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
