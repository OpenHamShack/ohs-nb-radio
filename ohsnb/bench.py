"""python3 -m ohsnb.bench [--rate 1200000] [--seconds 20]

Measures what fraction of one CPU core the engine needs, so the figure in
docs/PERF.md can be re-measured on the machine that matters (a Pi 400):

1. receive: every RX consumer (wide + zoom scopes, VFO channel + SSB demod +
   AGC, beacon lock in tracking, TX monitor channel) on pre-generated
   simulator IQ, so the simulator's own cost is not counted;
2. transmit: SSB modulator + upconversion to the device rate, per second of
   air time;
3. simulator: generating the band, per second of signal;
4. whole process: a real-time headless run on the simulator (all threads,
   null audio), CPU seconds per wall second;
5. Pluto rate change: what a Pluto whose firmware refuses the AD9361's FIR
   costs (devices/pluto.py) - int16 conversion + decimation of the 2.4 MS/s
   receive stream, and interpolation + int16 conversion on transmit - with
   the conversion alone at 2.4 MS/s for comparison.
"""
from __future__ import annotations

import argparse
import os
import platform  # os.uname() does not exist on Windows
import time

import numpy as np

from ohscore.audio import NullAudio
from ohscore.devices.base import Device

from . import state
from .devices.sim import SimDevice
from .radio import RX_CENTRE_DL, Radio


class Replay(Device):
    kind = "replay"
    can_tx = False

    def __init__(self, iq: np.ndarray, fs: float):
        self.iq, self.fs, self.pos = iq, fs, 0
        self.realtime = True

    def open(self):
        pass

    def set_rx_if(self, hz):
        pass

    def read(self, n):
        if self.pos + n > len(self.iq):
            self.pos = 0
        out = self.iq[self.pos:self.pos + n]
        self.pos += n
        return out


def cfg_for(rate: int, **over) -> dict:
    cfg = state.defaults(("setting", "control"))
    cfg.update(sampleRate=rate, simRealtime=False, simSeed=11, audioBackend="null")
    cfg.update(over)
    return cfg


def bench_rx(rate: int, seconds: float) -> dict:
    sim = SimDevice(cfg_for(rate, simDriftHz=0.0), rate)
    sim.open()
    # Tune the recording where the engine will believe it is tuned.
    sim.set_rx_if(RX_CENTRE_DL - sim.lnb_lo + sim.rx_err0)
    t = time.process_time()
    blk = 5 * sim.geo.L
    # Enough for the 4 s warm-up and the run without wrapping (a wrap is a
    # jump in the simulated LNB, which would send beacon lock back to search).
    iq = np.concatenate([sim.read(blk) for _ in range(int((seconds + 5) * rate / blk))])
    sim_cost = (time.process_time() - t) / (len(iq) / rate)
    # The replay cannot retune, so start the engine at the sim's LNB error and
    # it never needs to re-centre.
    r = Radio(cfg_for(rate, rxCorr=sim.rx_err0), persist=False, audio=NullAudio(realtime=False),
              device=Replay(iq, float(rate)))
    r.start()
    r.stop_ev.set()                 # we drive the receive path ourselves, on this thread
    for th in r.threads:
        th.join(timeout=2)
    # warm up (beacon search, then tracking) - search is a transient, tracking the steady state
    n = 5 * r.geo.L
    for _ in range(int(4 * rate / n)):
        r._rx_block(r.dev.read(n))
    t0 = time.process_time()
    w0 = time.perf_counter()
    k = int(seconds * rate / n)
    for _ in range(k):
        r._rx_block(r.dev.read(n))
    cpu = time.process_time() - t0
    wall = time.perf_counter() - w0
    lock = r.state()["rxLock"]
    r.running = False
    return {"rx": cpu / (k * n / rate), "rx_wall": wall / (k * n / rate), "sim": sim_cost, "lock": lock}


def bench_tx(rate: int, seconds: float) -> float:
    from ohscore.dsp.bank import Geometry, Source, Synthesis
    from ohscore.dsp.mod import SsbMod
    g = Geometry(rate)
    src, syn, mod = Source(g, g.decimation_for(12_000)), Synthesis(g), SsbMod()
    mod.configure(300, 2700, 0, 6, True)
    src.freq = 200_000.0
    hop = g.L // g.decimation_for(12_000)
    a = (0.3 * np.random.default_rng(1).standard_normal(5 * hop)).astype(np.float32)
    t0 = time.process_time()
    k = int(seconds * rate / (5 * g.L))
    for _ in range(k):
        syn.render(5, [(src, mod(a))])
    return (time.process_time() - t0) / (k * 5 * g.L / rate)


def bench_process(rate: int, seconds: float) -> float:
    r = Radio(cfg_for(rate, simRealtime=True, simSignals=True), persist=False, audio=NullAudio(realtime=True))
    feeds = [r.subscribe(k, 100) for k in ("wide", "zoom", "meter", "lock", "state")]
    r.start()
    time.sleep(3)
    c0, w0 = time.process_time(), time.monotonic()
    while time.monotonic() - w0 < seconds:
        time.sleep(1 / 30)          # a UI draining at 30 Hz
        r.heartbeat()
        for f in feeds:
            f.drain()
    used = (time.process_time() - c0) / (time.monotonic() - w0)
    r.stop()
    return used


def bench_rate_change(rate: int, seconds: float) -> dict:
    from ohscore.dsp.multirate import Decimator, Interpolator
    from ohscore.devices.pluto import NO_FIR_MIN
    m = -(-NO_FIR_MIN // rate)
    hw = rate * m
    blk = int(rate * 0.075)                       # the Pluto's block, engine rate
    rng = np.random.default_rng(1)
    raw = rng.integers(-2048, 2048, 2 * blk * m).astype(np.int16).tobytes()
    k = max(1, int(seconds * rate / blk))

    def conv():
        return np.frombuffer(raw, np.int16).astype(np.float32).view(np.complex64) / 2048.0

    def per_second(fn):
        fn()                                       # the first call builds FFT plans
        t0 = time.process_time()
        for _ in range(k):
            fn()
        return (time.process_time() - t0) / (k * blk / rate)

    dec, it = Decimator(m), Interpolator(m)
    x = (0.3 * (rng.standard_normal(blk) + 1j * rng.standard_normal(blk))).astype(np.complex64)

    def tx():
        y = it(x)
        s = np.empty(2 * len(y), np.int16)
        s[0::2] = np.clip(np.round(y.real * 32767), -32767, 32767)
        s[1::2] = np.clip(np.round(y.imag * 32767), -32767, 32767)
    return {"m": m, "hw": hw, "conv": per_second(conv), "rx": per_second(lambda: dec(conv())),
            "tx": per_second(tx)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m ohsnb.bench")
    ap.add_argument("--rate", type=int, default=1_200_000, choices=[600_000, 1_200_000])
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--skip-process", action="store_true")
    a = ap.parse_args(argv)
    print(f"host: {platform.machine()}, {os.cpu_count()} cpus, numpy {np.__version__}, rate {a.rate} S/s")
    rx = bench_rx(a.rate, a.seconds)
    print(f"receive path   : {100 * rx['rx']:5.1f} % of one core  (beacon lock {rx['lock']})")
    print(f"simulator      : {100 * rx['sim']:5.1f} % of one core")
    print(f"transmit path  : {100 * bench_tx(a.rate, a.seconds):5.1f} % of one core while keyed")
    rc = bench_rate_change(a.rate, a.seconds)
    print(f"Pluto, FIR refused (radio at {rc['hw'] / 1e6:g} MS/s, M={rc['m']}): receive "
          f"{100 * rc['rx']:4.1f} %, transmit {100 * rc['tx']:4.1f} % of one core "
          f"(int16 conversion alone: {100 * rc['conv']:4.1f} %)")
    if not a.skip_process:
        print(f"whole process  : {100 * bench_process(a.rate, a.seconds):5.1f} % of one core "
              f"(real-time sim, all threads, UI draining at 30 Hz)")


if __name__ == "__main__":
    main()
