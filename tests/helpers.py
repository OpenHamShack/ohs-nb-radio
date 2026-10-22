"""Shared set-up: a Radio on the simulator, faster than real time, with the
null audio backend (optionally fed test audio)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time

import numpy as np

from ohsnb import state
from ohscore.audio import NullAudio
from ohsnb.radio import Radio


def rig_conv(lo: float, side: str = "low") -> dict:
    """Settings for an IC-9700 upconverter with LO `lo` (low- or high-side),
    as the converter list holds it since the LO and side stopped being
    settings of their own: the list (NB's default LNB plus this) and the
    choice of it for the IC-9700."""
    from ohscore.converters import Converter, DOWN, RXTX
    from ohsnb import converters as nbconv
    c = Converter(f"Upconverter {lo / 1e6:g} {side}", DOWN, RXTX, float(lo), float(lo), inverted=side == "high")
    return {"converters": nbconv.DEFAULT_LIST + [c.to_dict()], "rigTxConverter": c.title}


def sim_cfg(**over):
    cfg = state.defaults(("setting", "control"))
    cfg.update(device="sim", simRealtime=False, simSeed=7, simSignals=False, audioBackend="null",
               simRxErrorHz=2500.0, simDriftHz=0.0, simUlErrorHz=3000.0, txGain=-30.0)
    cfg.update(over)
    return cfg


def noise_audio(level=0.5, seed=1):
    rng = np.random.default_rng(seed)

    def src(n):
        return (level * rng.standard_normal(n)).astype(np.float32)
    return src


def make_radio(tmpdir, audio_source=None, device=None, **over):
    """`device`: a device class to build from the same config instead of
    the one the `device` setting names (e.g. a simulator posing as a radio)."""
    cfg = sim_cfg(**over)
    r = Radio(cfg, persist=False, data_dir=tmpdir, audio=NullAudio(realtime=False, source=audio_source),
              device=device(dict(cfg)) if device is not None else None)
    return r


class RadiatingSim:
    """Mixed into a simulator, makes it claim to radiate, as a real radio
    does: what the licence gate must judge by, whatever the `device`
    setting says."""
    radiates = True


def sim_seconds(radio):
    d = radio.dev
    return d.n / d.fs


def run_sim(radio, seconds, feeds=(), until=None, timeout=120.0):
    """Let the simulator advance `seconds` of signal time, heartbeating like a
    UI would. Returns {feed: [items]} drained from `feeds`."""
    out = {f.kind: [] for f in feeds}
    start = sim_seconds(radio)
    t_wall = time.monotonic()
    while sim_seconds(radio) - start < seconds:
        if time.monotonic() - t_wall > timeout:
            raise TimeoutError("simulation did not advance")
        time.sleep(0.02)
        radio.heartbeat()
        for f in feeds:
            out[f.kind].extend(f.drain())
        if until and until():
            break
    for f in feeds:
        out[f.kind].extend(f.drain())
    return out


def wait_rx_lock(radio, timeout_sim=15.0):
    run_sim(radio, timeout_sim, until=lambda: radio.state()["rxLock"] == "locked")
    return radio.state()["rxLock"] == "locked"


_qt_cleanup_registered = False


def qt_app(make_app=None):
    """The one QApplication the UI tests share, torn down by ohscore.ui.qtapp.shutdown
    from an atexit hook - which runs before any module is torn down - rather
    than by PyQt during interpreter shutdown, which under Windows Python
    ended the passing suite with an access violation in two runs of five.

    Call it from setUpClass. While the calling test module runs, garbage is
    collected only by the application's event loop (qtapp._GuiThreadGc);
    when the module is done, qtapp.release_gc collects once more and hands
    collection back to Python, so the tests that follow, which never turn
    the event loop, are not left with no collection at all. `make_app` is
    the app's own (ohsnb.ui's by default; ohsradio.ui's for the HAM tests)."""
    global _qt_cleanup_registered
    import unittest
    from ohscore.ui.qtapp import release_gc, shutdown
    if make_app is None:
        from ohsnb.ui import make_app
    app = make_app(["test"])
    unittest.addModuleCleanup(release_gc)
    if not _qt_cleanup_registered:
        import atexit
        atexit.register(shutdown)
        _qt_cleanup_registered = True
    return app
