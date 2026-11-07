#!/usr/bin/env python3
"""Cut one Radio IQ recording down to a band segment: mix the segment's
centre to 0 Hz, low-pass it, decimate, and write the result as SigMF
ci16_le with a small JSON beside it.

    decimate.py --meta REC.sigmf-meta --data REC.sigmf-data --lo HZ --hi HZ
                --out-dir DIR --name NAME [--part N] [--receiver R]
                [--antenna "Antenna C, Loop Antenna"] [--scale S]

Written for ohs-iq-capture (the reference recordings of the RSGB autumn
contests, Brian 07/11/2026): a 35-minute part at 1.2 MS/s is about 10 GB,
and the 3600-3775 kHz SSB segment needs a fifth of that rate. It runs in
Radio's own image under rootless podman with --memory 1g --cpus 1,
because the controller's host Python has no numpy; numpy is all it uses.

Decisions, each because the obvious alternative failed or cost too much:

- **Streaming in blocks**, never the whole file: a part is 2.5 G samples.
  Memory is a few blocks of complex128 (tens of MB) whatever the length.
- **Mixed from the recording's own centre**, captures[i]["core:frequency"],
  never the dial that was asked for: the device centre sits off the dial
  (Radio's LO offset). Each capture of the meta (Radio starts a new one at
  a gap or a retune) mixes with its own centre. The oscillator is one
  precomputed block of exp(-jwn) turned by a running phase, so the phase
  runs on unbroken across blocks; recomputing exp(-jwn) from a global n
  in float64 loses phase after a billion samples.
- **FFT overlap-save FIR**, because time-domain convolution of a
  thousand-tap filter at 1.2 MS/s is far too slow in numpy. The filter is
  a Kaiser-windowed sinc (80 dB stopband), passing the segment plus 10 %
  and stopping at the output's Nyquist frequency; anything that folds
  back on decimation lands outside the segment. It is linear phase and
  the group delay is taken off, so output sample k is input sample k*d.
- **Decimation by the largest whole d with fs/d >= 1.15 x (hi - lo)**:
  whole, so no resampler; 1.15 leaves the filter room to roll off.
- **Two passes for the level**: the first finds the output's peak, the
  second writes with the gain that puts it at 32000 (no clipping), and
  the gain is recorded (`openhamshack:gain`) so parts can be compared.
  A fixed worst-case gain would leave a quiet segment a few bits deep
  under the 75 m broadcasters that set the input's peak. --scale skips the
  first pass (the tests, or a known gain).

Outputs, each written under a .partial name and renamed when complete, so
a copy taken mid-run never sees half a file:
  DIR/NAME-pNN.sigmf-data, DIR/NAME-pNN.sigmf-meta, DIR/NAME-pNN.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

STOP_DB = 80.0          # Kaiser stopband attenuation
GUARD = 1.15            # output rate at least this times the segment width
PASS_MARGIN = 0.10      # pass the segment plus 10 %
FULL = 32000.0          # the output's peak lands here (int16 full scale is 32767)


def plan(fs: float, lo: float, hi: float) -> tuple[int, float, float]:
    """(d, pass edge, stop edge) for a segment at sample rate fs; edges in
    Hz either side of 0 after mixing."""
    bw = hi - lo
    if bw <= 0:
        raise ValueError("the segment's high edge must be above its low edge")
    d = max(1, int(math.floor(fs / (GUARD * bw))))
    while d > 1 and fs / d < GUARD * bw:      # floor of a float division, made exact
        d -= 1
    pass_edge = bw * (1 + PASS_MARGIN) / 2
    stop_edge = fs / d / 2
    if stop_edge <= pass_edge:                 # d == 1 and a segment wider than the recording
        raise ValueError(f"the segment ({bw:.0f} Hz) does not fit in {fs:.0f} S/s")
    return d, pass_edge, stop_edge


def design(fs: float, pass_edge: float, stop_edge: float) -> np.ndarray:
    """A linear-phase low-pass: Kaiser-windowed sinc, odd length, unity at DC."""
    dw = 2 * math.pi * (stop_edge - pass_edge) / fs
    n = int(math.ceil((STOP_DB - 8) / (2.285 * dw))) + 1
    n += 1 - n % 2
    beta = 0.1102 * (STOP_DB - 8.7)
    fc = (pass_edge + stop_edge) / 2 / fs
    k = np.arange(n) - (n - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * k) * np.kaiser(n, beta)
    return h / h.sum()


def read_meta(path: Path) -> dict:
    meta = json.loads(path.read_text())
    g = meta.get("global") or {}
    if g.get("core:datatype") != "ci16_le":
        raise ValueError(f"{path.name}: core:datatype is {g.get('core:datatype')!r}, not ci16_le")
    caps = sorted(meta.get("captures") or [], key=lambda c: int(c.get("core:sample_start", 0)))
    if not caps or "core:frequency" not in caps[0]:
        raise ValueError(f"{path.name}: no capture with a core:frequency")
    return meta


class Chain:
    """Mixer, overlap-save filter and decimator, fed blocks of ci16 samples
    in order; `feed` returns the decimated complex output so far."""

    def __init__(self, fs: float, centre: float, captures: list[dict], h: np.ndarray, d: int, block: int):
        self.fs, self.centre, self.d, self.h = fs, centre, d, h
        self.M = len(h)
        self.D = (self.M - 1) // 2          # group delay, taken off
        self.L = block
        self.nfft = 1 << (self.L + self.M - 1 - 1).bit_length()
        self.H = np.fft.fft(h, self.nfft)
        self.hist = np.zeros(self.M - 1, np.complex128)
        self.starts = [int(c.get("core:sample_start", 0)) for c in captures]
        self.freqs = [float(c["core:frequency"]) for c in captures]
        self.n_in = 0                       # input samples mixed so far
        self.n_y = 0                        # filtered samples made so far
        self.phase = 0.0
        self._osc: dict[tuple[float, int], np.ndarray] = {}

    def _osc_block(self, w: float, n: int) -> np.ndarray:
        key = (w, n)
        if key not in self._osc:
            if len(self._osc) > 4:
                self._osc.clear()
            self._osc[key] = np.exp(1j * w * np.arange(n))
        return self._osc[key]

    def mix(self, x: np.ndarray) -> np.ndarray:
        """x times exp(-j 2pi (centre - capture centre) n / fs), the phase
        carried on from the block before."""
        out = np.empty_like(x)
        a, end = 0, len(x)
        while a < end:
            g = self.n_in + a
            i = max(j for j, s in enumerate(self.starts) if s <= g) if g >= self.starts[0] else 0
            nxt = self.starts[i + 1] - self.n_in if i + 1 < len(self.starts) else end
            b = min(end, max(nxt, a + 1))
            w = -2 * math.pi * (self.centre - self.freqs[i]) / self.fs
            out[a:b] = x[a:b] * (np.exp(1j * self.phase) * self._osc_block(w, b - a))
            self.phase = math.remainder(self.phase + w * (b - a), 2 * math.pi)
            a = b
        self.n_in += len(x)
        return out

    def filt(self, x: np.ndarray) -> np.ndarray:
        """Filter (overlap-save) and keep every d-th sample of the delay-
        corrected output: z[m] = y[m + D], kept where m % d == 0."""
        buf = np.concatenate((self.hist, x))
        y = np.fft.ifft(np.fft.fft(buf, self.nfft) * self.H)[self.M - 1:self.M - 1 + len(x)]
        self.hist = buf[len(buf) - (self.M - 1):]
        first = self.n_y - self.D           # m of y[0]
        self.n_y += len(x)
        # the first i with first + i >= 0 and (first + i) % d == 0
        i0 = max(0, -first)
        i0 += (-(first + i0)) % self.d
        return y[i0::self.d]

    def feed(self, x: np.ndarray) -> np.ndarray:
        return self.filt(self.mix(x))

    def flush(self) -> np.ndarray:
        """The last D outputs, still inside the filter."""
        return self.filt(np.zeros(self.D, np.complex128)) if self.D else np.zeros(0, np.complex128)


def blocks(data: Path, block: int):
    """The recording as complex128 blocks of `block` samples."""
    with open(data, "rb") as f:
        while True:
            raw = np.fromfile(f, dtype="<i2", count=2 * block)
            if raw.size < 2:
                return
            raw = raw[: raw.size - raw.size % 2].astype(np.float64)
            yield raw[0::2] + 1j * raw[1::2]


def run(chain_args: tuple, data: Path, total_in: int, sink) -> None:
    chain = Chain(*chain_args)
    n_out = -(-total_in // chain.d)          # outputs for m = 0, d, 2d, ... < total_in
    made = 0
    for x in blocks(data, chain.L):
        y = chain.feed(x)
        y = y[: max(0, n_out - made)]
        made += len(y)
        sink(y)
    y = chain.flush()[: max(0, n_out - made)]
    sink(y)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="decimate.py")
    p.add_argument("--meta", required=True, type=Path)
    p.add_argument("--data", required=True, type=Path)
    p.add_argument("--lo", required=True, type=float)
    p.add_argument("--hi", required=True, type=float)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--name", required=True)
    p.add_argument("--part", type=int, default=1)
    p.add_argument("--receiver", default="RSPdx")
    p.add_argument("--antenna", default="")
    p.add_argument("--scale", type=float, help="the output gain; skips the first pass")
    p.add_argument("--block", type=int, default=0, help="input samples per block (default: about 1 M)")
    a = p.parse_args(argv)

    meta = read_meta(a.meta)
    g = meta["global"]
    fs = float(g["core:sample_rate"])
    caps = sorted(meta["captures"], key=lambda c: int(c.get("core:sample_start", 0)))
    centre = (a.lo + a.hi) / 2
    for c in caps:
        f = float(c["core:frequency"])
        if max(abs(a.lo - f), abs(a.hi - f)) >= fs / 2:
            raise SystemExit(f"decimate: the segment {a.lo:.0f}-{a.hi:.0f} Hz is not inside the recording "
                             f"({f:.0f} Hz +/- {fs / 2:.0f})")
    d, pass_edge, stop_edge = plan(fs, a.lo, a.hi)
    h = design(fs, pass_edge, stop_edge)
    block = a.block or max(d, ((1 << 20) - len(h)) // d * d)
    block = max(d, block // d * d)            # a whole number of output samples per block
    total_in = a.data.stat().st_size // 4
    chain_args = (fs, centre, caps, h, d, block)

    if a.scale:
        gain = a.scale
    else:
        peak = [0.0]

        def measure(y):
            if len(y):
                peak[0] = max(peak[0], float(np.max(np.abs(y.real))), float(np.max(np.abs(y.imag))))
        run(chain_args, a.data, total_in, measure)
        gain = FULL / peak[0] if peak[0] > 0 else 1.0

    a.out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{a.name}-p{a.part:02d}"
    data_out = a.out_dir / f"{base}.sigmf-data"
    tmp = a.out_dir / f"{base}.sigmf-data.partial"
    written = [0]
    clipped = [0]
    with open(tmp, "wb") as f:
        def write(y):
            if not len(y):
                return
            v = np.empty(2 * len(y), np.float64)
            v[0::2], v[1::2] = y.real * gain, y.imag * gain
            np.rint(v, out=v)
            over = np.abs(v) > 32767
            if over.any():
                clipped[0] += int(over.sum())
                np.clip(v, -32767, 32767, out=v)
            v.astype("<i2").tofile(f)
            written[0] += len(y)
        run(chain_args, a.data, total_in, write)
    os.chmod(tmp, 0o600)

    fs_out = fs / d
    out_caps = []
    for c in caps:
        s = int(c.get("core:sample_start", 0))
        m = -(-s // d)
        oc = {"core:sample_start": m, "core:frequency": centre,
              "openhamshack:source_frequency": float(c["core:frequency"])}
        if "core:datetime" in c:
            oc["core:datetime"] = iso(parse_utc(c["core:datetime"]) + dt.timedelta(seconds=(m * d - s) / fs))
        if "openhamshack:gap_samples" in c:
            oc["openhamshack:gap_samples"] = int(round(c["openhamshack:gap_samples"] / d))
        out_caps.append(oc)
    start = out_caps[0].get("core:datetime")
    hw = f"SDRplay {a.receiver}" + (f", {a.antenna}" if a.antenna else "")
    source_id = a.meta.name[: -len(".sigmf-meta")] if a.meta.name.endswith(".sigmf-meta") else a.meta.stem
    out_meta = {
        "global": {
            "core:datatype": "ci16_le", "core:sample_rate": fs_out, "core:version": "1.0.0",
            "core:hw": hw, "core:recorder": "ohs-iq-capture decimate.py",
            "core:description": f"{a.name} part {a.part}: {a.lo / 1e3:.1f}-{a.hi / 1e3:.1f} kHz, "
                                f"cut down from {fs / 1e6:g} MS/s",
            "openhamshack:segment": {"lowHz": a.lo, "highHz": a.hi},
            "openhamshack:receiver": a.receiver, "openhamshack:antenna": a.antenna,
            "openhamshack:decimation": d, "openhamshack:gain": gain, "openhamshack:clipped": clipped[0],
            "openhamshack:filter": {"taps": len(h), "passHz": pass_edge, "stopHz": stop_edge, "stopDb": STOP_DB},
            "openhamshack:source": {"id": source_id, "sampleRate": fs, "global": g},
        },
        "captures": out_caps,
        "annotations": [],
    }
    small = {
        "name": a.name, "part": a.part,
        "data": data_out.name, "meta": f"{base}.sigmf-meta",
        "format": "SigMF ci16_le (interleaved int16 I, Q, little-endian)",
        "centreHz": centre, "sampleRate": fs_out, "startUtc": start,
        "seconds": round(written[0] / fs_out, 3), "samples": written[0],
        "segment": {"lowHz": a.lo, "highHz": a.hi},
        "receiver": a.receiver, "antenna": a.antenna,
        "gain": gain, "clipped": clipped[0],
        "source": {"id": source_id, "centreHz": float(caps[0]["core:frequency"]), "sampleRate": fs},
    }
    for name, obj in ((f"{base}.sigmf-meta", out_meta), (f"{base}.json", small)):
        t = a.out_dir / f"{name}.partial"
        t.write_text(json.dumps(obj, indent=1) + "\n")
        os.chmod(t, 0o600)
        t.replace(a.out_dir / name)
    tmp.replace(data_out)          # last: the data's name appearing means the part is whole
    print(json.dumps({"part": a.part, "data": data_out.name, "samples": written[0], "sampleRate": fs_out,
                      "decimation": d, "gain": gain, "clipped": clipped[0]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
