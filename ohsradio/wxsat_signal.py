"""Weather-satellite signal strength: how much of a Meteor-M pass was
heard, second by second, before any decoder locks (Brian, 29/10/2026: he
is mapping his radio horizon - the lowest elevation anything is heard at,
at each azimuth - from a fortnight of passes recorded from 0°; SatDump's
pictures say nothing about the seconds it could not decode).

    measure(iq, fs, offset_hz)           # (snr_db, noise_db) of about a second of IQ
    timeline(job)                        # the whole pass, from its recording
    save(folder, pass_id, tl) / load(folder, pass_id) / has(...) / prune(folder, now)
    url(pass_id)                         # api/wxsat/passes/<id>/signal
    SignalWorker(folder, done).submit(job)   # timeline() and save() on one nice-19 thread

**The measure is a power ratio, not a decode.** A Welch periodogram of
the second (Hann window, 50 % overlap, normalised as ohscore/dsp/spectrum.py's
Scope is: no scipy anywhere here, freedv.py says why). The signal band is
the satellite's expected frequency in the file +- BAND_HALF_HZ (70 kHz:
LRPT's ~120 kHz channel with room for the tuning error); the recording has
the satellite's *nominal* frequency at 0 Hz (wxsat.py shifts for that, not
for Doppler), so the expected frequency is the Doppler shift, from SGP4 and
the pass's own element set (wxsat_orbit.Orbit.doppler_hz). The noise is
the median power per bin of every bin well clear of the band on either
side (beyond BAND_HALF_HZ + GUARD_HZ, the guard keeping the Hann window's
own skirts out; at a rate so low that the guard leaves nothing, every bin
outside the band). Both are made power per hertz before they are compared,
so a figure means the same at any recording rate and any FFT size:

    snrDb = 10 log10(mean power per Hz in the band / median power per Hz outside it)

0 dB is "the band holds no more than the noise beside it": nothing there.
It is signal plus noise over noise, so it never goes far below 0 (one
second of noise alone reads within a fraction of a dB of it), and a signal
as strong as the noise in the band reads +3 dB. The mean, not the median,
in the band: it is "anything heard" Brian wants, and a narrow carrier or a
birdie inside the band counts as much as LRPT does - the receiver's own DC
spike included, which sits at 0 Hz in the file when the hardware is tuned
to the nominal frequency. `noise_db` is 10 log10 of the noise per Hz on the
engine's full scale (1.0): a figure to compare passes by, not an absolute
power.

**Live** (wxsat.py's _feed): one measure() a second on the receive thread,
inline - a few hundred 4096-point FFTs, a few ms a second - for
api/wxsat/status's `snrDb`. **After LOS** (and at startup for an older
pass whose recording is still there: WxSat.backfill_signal), timeline()
reads the whole recording once, a second at a time, on SignalWorker's
thread at nice 19, and the result is kept as `<passId>.json` in
data/wxsat/signal/ for KEEP_S (30 days) **whatever happens to the IQ**
(Brian): the recordings are pruned by size within days, and the timeline
is the part of a pass worth keeping for the horizon map.

**No `locked` field.** SatDump's CLI gives no per-second lock or SNR
cheaply: its log is free text written as it goes, and dataset.json is a
summary of the pass, not a timeline. Deriving one would mean parsing that
text or a decoder of our own (which Brian's rule forbids); neither is
worth it for a figure the pictures already answer pass by pass.
"""
from __future__ import annotations

import bisect
import json
import logging
import math
import os
import queue
import re
import statistics
import threading
from pathlib import Path

import numpy as np

from ohscore import sigmf
from ohsradio import wxsat_orbit, wxsat_tle
from ohsradio.i18n import _

log = logging.getLogger("ohsradio.wxsat")

BAND_HALF_HZ = 70_000.0
GUARD_HZ = 20_000.0
NFFT = 4096
MIN_NFFT = 256                     # below this a second's last scrap is too few samples to say anything
BATCH = 64                         # FFT frames at a time: a few MB, never the whole second at once
KEEP_S = 30 * 86_400.0
DROP_EVERY_BYTES = 32 << 20        # read pages handed back to the kernel this often (sigmf.py's reason)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

_windows: dict[int, tuple[np.ndarray, float]] = {}


def _window(nfft: int) -> tuple[np.ndarray, float]:
    """spectrum.Scope's window and its normalisation (a tone of amplitude
    A reads A**2 at its bin), made once per size."""
    w = _windows.get(nfft)
    if w is None:
        win = np.hanning(nfft + 2)[1:-1].astype(np.float32)
        w = _windows[nfft] = (win, float(win.sum()) ** 2)
    return w


def measure(iq: np.ndarray, fs: float, offset_hz: float) -> tuple[float | None, float | None]:
    """(snr_db, noise_db) of `iq` at rate `fs`, the satellite expected at
    `offset_hz` in it (module docstring); (None, None) when there are too
    few samples for a meaningful FFT or no bin to measure on one side."""
    x = np.asarray(iq, np.complex64)
    n = min(NFFT, len(x))
    if n < MIN_NFFT:
        return None, None
    nfft = 1 << (n.bit_length() - 1)               # the largest power of two that fits
    win, norm = _window(nfft)
    hop = nfft // 2
    frames = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop]
    acc = np.zeros(nfft, np.float64)
    for i in range(0, len(frames), BATCH):
        f = np.fft.fft(frames[i:i + BATCH] * win, axis=1)
        acc += (f.real ** 2 + f.imag ** 2).sum(axis=0)
    bin_hz = fs / nfft
    psd = acc / (len(frames) * norm * bin_hz)      # power per Hz, each bin
    freqs = np.fft.fftfreq(nfft, 1.0 / fs)
    away = np.abs(freqs - offset_hz)
    band = psd[away <= BAND_HALF_HZ]
    noise = psd[away > BAND_HALF_HZ + GUARD_HZ]
    if not len(noise):
        noise = psd[away > BAND_HALF_HZ]
    if not len(band) or not len(noise):
        return None, None
    floor = float(np.median(noise))
    if floor <= 0.0:                               # all zeros: a recording of nothing at all
        return None, None
    return 10.0 * math.log10(max(float(band.mean()), 1e-30) / floor), 10.0 * math.log10(floor)


# ---------------------------------------------------------------- the pass from its recording
def _checkpoints(caps: list, total: int, fs: float) -> list[tuple[int, int, float]]:
    """(first sample, end sample, UTC of the first) for each capture: a
    gap is a jump in time between two samples next to each other in the
    file, never silence written into it (sigmf.py). As filedev.py's
    _segments, without the device or the frequencies."""
    caps = [c for c in caps if int(c.get("core:sample_start", 0)) < total] or [{"core:sample_start": 0}]
    out: list[tuple[int, int, float]] = []
    for i, c in enumerate(caps):
        start = 0 if i == 0 else int(c["core:sample_start"])
        end = int(caps[i + 1]["core:sample_start"]) if i + 1 < len(caps) else total
        if c.get("openhamshack:utc") is not None:
            t = float(c["openhamshack:utc"])
        elif "core:datetime" in c:
            t = sigmf.parse_utc(c["core:datetime"])
        elif out:
            ps, pe, pt = out[-1]
            t = pt + (pe - ps) / fs + float(c.get("openhamshack:gap_samples", 0) or 0) / fs
        else:
            raise ValueError(_("The recording does not say when it was made"))
        if end > start:
            out.append((start, end, t))
    return out


def timeline(job: dict) -> dict:
    """job: {"passId", "data" (Path to the .sigmf-data), "lat", "lon"}.
    Reads the recording's own .sigmf-meta for everything else (the
    satellite's name, its nominal frequency, the element set the pass was
    predicted from), as wxsat.py's _decode_job does for the decoder, so it
    gives the same numbers right after LOS (WxSat._finish), in the startup
    backfill, which has nothing but the recording, or years later. Raises
    OSError, ValueError or KeyError when the metadata lacks what is needed
    (no element set recorded with the pass, a damaged file): the caller
    says what that means."""
    data, meta_path = sigmf.paths(Path(job["data"]))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    g = meta["global"]
    wx = g["openhamshack:wxsat"]
    tle = list(wx["tle"])
    if len(tle) < 2:
        raise ValueError(_("The recording has no element set"))
    orbit = wxsat_orbit.Orbit(tle[-2], tle[-1])
    fs = float(g["core:sample_rate"])
    nominal = float(wx["nominalHz"])
    comp, scale = sigmf.DTYPES[g["core:datatype"]]
    if g.get("openhamshack:scale"):
        scale = 1.0 / float(g["openhamshack:scale"])
    item = np.dtype(comp).itemsize * 2
    lat, lon = float(job["lat"]), float(job["lon"])
    total = data.stat().st_size // item
    segs = _checkpoints(meta.get("captures") or [], total, fs)
    second = max(1, int(round(fs)))
    samples, floors = [], []
    with open(data, "rb") as f:
        fd = f.fileno()
        dropped = 0
        if hasattr(os, "posix_fadvise"):
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
        for start, end, t0 in segs:
            f.seek(start * item)
            s = start
            while s < end:
                n = min(second, end - s)
                raw = f.read(n * item)
                n = len(raw) // item
                if not n:
                    break
                v = np.frombuffer(raw, comp, n * 2).astype(np.float32)
                v *= np.float32(scale)
                iq = v.view(np.complex64)
                t = t0 + (s - start + n / 2) / fs          # the middle of the second
                az, el = orbit.look(t, lat, lon)
                snr, noise = measure(iq, fs, orbit.doppler_hz(t, lat, lon, nominal))
                if noise is not None:
                    floors.append(noise)
                samples.append({"t": _iso_ms(t), "az": round(az, 1), "el": round(el, 1) + 0.0,
                                "snrDb": None if snr is None else round(snr, 1)})
                s += n
                if hasattr(os, "posix_fadvise") and f.tell() - dropped >= DROP_EVERY_BYTES:
                    # A 15-minute pass is ~3 GB, and in a container the page
                    # cache counts against its memory limit (sigmf.py):
                    # what has been read is handed back as it goes.
                    os.posix_fadvise(fd, dropped, f.tell() - dropped, os.POSIX_FADV_DONTNEED)
                    dropped = f.tell()
    return {"passId": str(job["passId"]), "sat": str(wx.get("satellite") or ""), "freqHz": int(round(nominal)),
            "noiseFloorDb": round(statistics.median(floors), 1) if floors else None,
            "samples": samples}


def _iso_ms(t: float) -> str:
    """To the tenth of a second: a timeline's seconds start wherever the
    recording did, and two in one whole second must not read alike."""
    whole = wxsat_tle.iso(t)
    return f"{whole[:-1]}.{int((t % 1.0) * 10) % 10}Z"


# ---------------------------------------------------------------- kept
def _path(folder: Path, pass_id: str) -> Path | None:
    return Path(folder) / f"{pass_id}.json" if _ID.match(str(pass_id)) else None


def url(pass_id: str) -> str:
    return f"api/wxsat/passes/{pass_id}/signal"


def has(folder: Path, pass_id: str) -> bool:
    p = _path(folder, pass_id)
    return p is not None and p.is_file()


def save(folder: Path, pass_id: str, tl: dict) -> None:
    p = _path(folder, pass_id)
    if p is None:
        raise ValueError(_("Not a pass id: {id}").format(id=pass_id))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tl, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def load(folder: Path, pass_id: str) -> dict | None:
    p = _path(folder, pass_id)
    if p is None:
        return None
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def prune(folder: Path, now: float) -> None:
    """Delete every timeline older than KEEP_S by its file's time -
    independent of the recording and of passes.json's own keeping: the
    JSON outlives the IQ on purpose (module docstring)."""
    try:
        files = list(Path(folder).glob("*.json"))
    except OSError:
        return
    for p in files:
        try:
            if p.stat().st_mtime < now - KEEP_S:
                p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- the worker
class SignalWorker:
    """One thread at nice 19 that makes and keeps timelines, one pass at a
    time, for a pass just ended and for the startup backfill alike (the
    queue is why one thread serves both). Started by submit(), gone after
    5 s with nothing to do, as wxsat_decode.Decoder's. `done(pass_id, ok,
    why)` is called from it after each job."""

    def __init__(self, folder: Path, done):
        self.folder = Path(folder)
        self.done = done
        self.q: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.current: str | None = None

    def submit(self, job: dict) -> None:
        """Queue `job` (timeline()'s) and start the thread if it is not running."""
        self.q.put(job)
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, name="wxsat-signal", daemon=True)
                self.thread.start()

    def idle(self) -> bool:
        return self.current is None and self.q.empty()

    def _loop(self) -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (AttributeError, OSError):
            pass
        while True:
            try:
                job = self.q.get(timeout=5.0)
            except queue.Empty:
                with self.lock:
                    if self.q.empty():
                        self.thread = None
                        return
                continue
            pid = self.current = str(job.get("passId"))
            if has(self.folder, pid):
                self.current = None
                continue                    # queued twice (a backfill and a pass's end): made once
            ok, why = True, None
            try:
                save(self.folder, pid, timeline(job))
            except ValueError as e:
                # timeline()'s own refusals (an empty recording, one with no
                # start time): said once by done() below. A traceback here
                # came back at every start for the 29/10 20:47Z pass, whose
                # recording the radio stopped at 0 s.
                ok, why = False, str(e) or type(e).__name__
            except Exception as e:  # noqa: BLE001 - a bad or missing recording fails its job, never the thread
                log.warning("weather satellites: the signal timeline of %s failed", pid, exc_info=True)
                ok, why = False, str(e) or type(e).__name__
            self.current = None
            try:
                self.done(pid, ok, why)
            except Exception:  # noqa: BLE001
                log.warning("weather satellites: reporting the signal timeline of %s failed", pid, exc_info=True)
