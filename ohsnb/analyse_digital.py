"""FT4, Q65, JS8 and PSK31 decode counts across a whole recording, beside
the base report's own FT8 - "where did anything other than FT8 show up,
and when", not a second decode of FT8 itself.

New --other-modes section of `python3 -m ohsnb --analyse`. The three
slotted modes (FT4, Q65, JS8) are decoded exactly as FT8 already is in
ohsnb.analyse's own base report: the same Decoder class each mode's own
module already has (ohscore.modes.ft8/q65/js8), fed the file's audio at
that mode's documented QO-100 calling frequency (ohsnb.bandplan's own
presets - the only ones docs/qo100-research.md cites), bucketed by slot
time and with each decode's dial noted (the preset plus jt9's own
reported `df`). None of this re-implements a decoder: it only builds the
channel audio (ohsnb.analyse._ft8_stream_decode's own approach, generalised
to any dial) and drives each mode's existing Decoder the way its own
module already drives itself live - streamed one block at a time, never
held as a whole-file array (_channel_audio_chunks's own docstring says
why).

PSK31 is not slotted, so it is treated differently: every `window_s`
(default 10 minutes), ohscore.modes.psk.find_carriers looks for PSK-shaped
carriers in the band-plan segments digital traffic is allowed in, and each
candidate is decoded for that window by shack_sdr's psk decoder, every
candidate a channel of one session (ohscore.modes.sdrmode.PskDecoder) -
counted here is characters actually decoded (squelch open, varicode
framed), the nearest PSK has to a discrete "message" without following a
whole QSO frame by frame. A non-PSK tone `find_carriers` also notices
(an FT8/Q65/JS8 signal sharing a digimode segment) never passes the
decoder's own squelch, so it contributes nothing - no mode identification
is needed ahead of the decoder itself.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from ohscore.modes import ft8 as ft8mod
from ohscore.modes import js8 as js8mod
from ohscore.modes import psk as pskmod
from ohscore.modes import q65 as q65mod
from ohscore.modes import sdrmode
from ohscore import sdr

from . import bandplan
from .analyse import _audio_blocks, _audio_fed_before, _chunk_grid, _CorrAt, _owns, _wait_for_room

BUCKET_S = 600.0

# Each slotted mode's own QO-100 calling frequency (ohsnb.bandplan.PRESETS,
# cited to docs/qo100-research.md) and how to flush its last, otherwise
# partial slot: ft8.Decoder exposes a real _close() (it runs an early and
# a final pass a slot, so one is needed in the live radio too); q65/js8's
# own Decoder classes do not (one pass a period, "not worth its own thread
# here yet" - their own docstrings), so their last slot is flushed the way
# their own feed() already flushes every slot before the last: one more
# sample timestamped past the period's end.
_SLOTTED = {
    "ft4": {"dial": next(p["dl"] for p in bandplan.PRESETS if p["name"] == "FT8"),
           "period_s": ft8mod.SLOT_S["ft4"], "module": ft8mod,
           "make": lambda emit: ft8mod.Decoder(emit, variant="ft4"), "explicit_close": True},
    "q65": {"dial": next(p["dl"] for p in bandplan.PRESETS if p["name"] == "Q65-60A"),
           "period_s": q65mod.PERIOD_S, "module": q65mod,
           "make": lambda emit: q65mod.Decoder(emit), "explicit_close": False},
    "js8": {"dial": next(p["dl"] for p in bandplan.PRESETS if p["name"] == "JS8Call"),
           "period_s": js8mod.PERIOD_S, "module": js8mod,
           "make": lambda emit: js8mod.Decoder(emit), "explicit_close": False},
}

# Where PSK31 (or any other continuous digital signal) may legally sit -
# every band-plan segment whose allowed classes include "digital" and are
# not also CW/SSB-only.
_PSK_SEGMENTS = [(lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS
                if classes and "digital" in classes]
PSK_WINDOW_S = BUCKET_S
PSK_CANDIDATE_S = 10.0     # how much audio find_carriers looks at, each window
PSK_PEAKS_PER_SEGMENT = 2


def _channel_audio_chunks(view, scale: float, n: int, fs: float, caps: list, info: dict, dial_hz: float,
                          rx_corr_est: float, beacon_hist: list[dict], part: dict | None = None):
    """12 kHz digital-mode audio at `dial_hz`, yielded one CHUNK_S block at
    a time rather than built as one whole-file array - ohsnb.analyse's own
    FT8 section (_ft8_stream_decode) is built the same way, and for the
    same reason: a three-hour recording's worth of channel audio (12 kHz
    x ~11000 s) is half a gigabyte, and holding one of those per mode -
    four here, more again for PSK31's several segments - is exactly the
    growth that OOM-killed a laptop running this section (07/10/2026). A
    caller that only needs to see each block once (stream a decoder
    straight through, or accumulate a bounded window) pays for one block
    at a time, whatever the file's length.

    `part` ({"warm", "lo", "hi"} grid blocks, ohsnb.analyse._audio_blocks)
    gives one time slice of a parallel run instead: exactly the audio a
    whole-file pass produces for blocks lo..hi-1."""
    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    corr_at = _CorrAt(beacon_hist, rx_corr_est)
    part = part or {}
    for _k, audio in _audio_blocks(view, scale, fs, grid, lambda a, b, dc: dial_hz - (dc - corr_at(b / fs)),
                                   k_lo=part.get("lo", 0), k_hi=part.get("hi"), k_warm=part.get("warm")):
        yield audio


def _decode_slotted(make, chunks, start_utc: float, period_s: float,
                    explicit_close: bool, fs_audio: float = 12_000.0, *, fed0: int = 0,
                    own: tuple[float, float] | None = None, finish: bool = True) -> list[dict]:
    """Every decode `make(emit)`'s Decoder reports, fed `chunks` (an
    iterable of audio blocks, as _channel_audio_chunks yields - or a list,
    for tests that already have the audio in hand) one at a time, as the
    live radio feeds it block by block - `make` builds the mode's own
    Decoder (ohscore.modes.ft8/q65/js8), unchanged. Feeding pauses
    (ohsnb.analyse._wait_for_room) whenever MAX_CONCURRENT_DECODES slots
    are already being decoded: this module reads a file far faster than
    real time, and without that pause every slot's jt9/q65code/js8
    subprocess would be launched at once rather than a handful at a
    time.

    For one time slice of a parallel run: `fed0` is how many audio
    samples a whole-file pass had fed before `chunks` begins (so every
    timestamp, and so every slot, is the same), `own` the slot starts
    this slice reports (ohsnb.analyse._owns), and `finish` False for every
    slice but the last - only the end of the recording flushes its final
    partial slot. Returned in slot order: the decodes arrive from up to
    MAX_CONCURRENT_DECODES threads in whatever order they finish, so
    even a single pass's list order (and the report's dial list built
    from it) varied run to run before this sort."""
    events: list[dict] = []
    lock = threading.Lock()

    def emit(ev):
        with lock:
            events.append(ev)

    decoder = make(emit)
    samples_fed = fed0
    for audio in chunks:
        _wait_for_room(decoder)
        decoder.feed(audio, start_utc + samples_fed / fs_audio)
        samples_fed += len(audio)
    last_t = start_utc + samples_fed / fs_audio
    if not finish:
        pass
    elif explicit_close:
        decoder._close()
    else:
        # Nothing marks the last slot as over until feed() sees a *later*
        # one begin (q65.py/js8.py's own feed(), read closely): one more
        # sample timestamped past this period's end does only that.
        decoder.feed(np.zeros(1, dtype=np.float32), last_t + period_s)
    deadline = time.monotonic() + 60.0
    while decoder._busy and time.monotonic() < deadline:
        time.sleep(0.05)
    decoder.close()
    out = [e for e in events if e.get("text")]
    if own is not None:
        out = [e for e in out if _owns(own, e.get("slot"))]
    out.sort(key=lambda e: e.get("slot", 0.0))
    return out


def _bucket_slotted(events: list[dict], start_utc: float, dial_hz: float, bucket_s: float,
                    total_s: float) -> tuple[list[dict], list[float]]:
    by_bucket: dict[int, int] = {}
    dials = []
    for e in events:
        # A slot's own canonical start (the UTC grid every FT4/Q65/JS8
        # station shares, floor(t/period)*period) can fall a little before
        # `start_utc` even for a transmission wholly inside the recording:
        # one starting 0.5 s into its slot (the usual case - see
        # tests/test_ohsnb_analyse.py's Ft8JT9VsOhsdigi) began, by the slot
        # grid's own reckoning, half a slot earlier than the first sample
        # fed. Clamped to bucket 0 rather than dropped: the decode is
        # still this recording's, just one whose slot started fractionally
        # before it did.
        stream_t = max(0.0, e["slot"] - start_utc)
        idx = int(stream_t // bucket_s)
        by_bucket[idx] = by_bucket.get(idx, 0) + 1
        dials.append(round((dial_hz + e["df"]) / 1e6, 6))
    nbuck = max(1, int(math.ceil(total_s / bucket_s)))
    return [{"t0": round(i * bucket_s, 1), "decodes": by_bucket.get(i, 0)} for i in range(nbuck)], dials


def other_modes_report(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                       beacon_hist: list[dict], start_utc: float, bucket_s: float = BUCKET_S,
                       psk_window_s: float = PSK_WINDOW_S) -> dict:
    """{"ft4"/"q65"/"js8"/"psk31": {"available", "why", "dial_mhz",
    "total", "buckets": [{"t0","decodes"}], "dial_mhz_seen": [...]}}.

    Each mode, and each PSK31 segment, is its own pass over the file with
    nothing shared between them, so a parallel run (ohsnb.analyse_parallel)
    runs them side by side - and also cuts each into time slices:
    _slotted_events/_psk_segment take a `part` for that, and the summaries
    below (_slotted_summary/_psk_summary) are what both paths finish with."""
    out: dict = {}
    for mode in _SLOTTED:
        events = _slotted_events(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, start_utc, mode) \
            if _SLOTTED[mode]["module"].CAN_DECODE else None
        out[mode] = _slotted_summary(mode, events, start_utc, bucket_s, n / fs)
    segs = [_psk_segment(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, si, psk_window_s)
            for si in range(len(_PSK_SEGMENTS))]
    out["psk31"] = _psk_summary(segs, n, fs, bucket_s)
    return out


def _slotted_events(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                    beacon_hist: list[dict], start_utc: float, mode: str, part: dict | None = None) -> list[dict]:
    """One slotted mode's decodes over the whole file, or over one time
    slice (`part`: ohsnb.analyse._ft8_decode_raw describes its keys)."""
    spec = _SLOTTED[mode]
    chunks = _channel_audio_chunks(view, scale, n, fs, caps, info, spec["dial"], rx_corr_est, beacon_hist, part)
    if part is None:
        return _decode_slotted(spec["make"], chunks, start_utc, spec["period_s"], spec["explicit_close"])
    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    k_lo = part.get("lo", 0)
    fed0 = _audio_fed_before(fs, grid[k_lo][0]) if (k_lo and k_lo < len(grid)) else 0
    return _decode_slotted(spec["make"], chunks, start_utc, spec["period_s"], spec["explicit_close"],
                           fed0=fed0, own=part.get("own"), finish=part.get("last", True))


def _slotted_summary(mode: str, events: list[dict] | None, start_utc: float, bucket_s: float,
                     total_s: float) -> dict:
    spec = _SLOTTED[mode]
    if events is None:
        return {"available": False, "why": "jt9 is not installed", "dial_mhz": spec["dial"] / 1e6,
                "total": 0, "buckets": [], "dial_mhz_seen": []}
    buckets, dials = _bucket_slotted(events, start_utc, spec["dial"], bucket_s, total_s)
    return {"available": True, "why": "", "dial_mhz": spec["dial"] / 1e6, "total": len(events),
            "buckets": buckets, "dial_mhz_seen": dials}


def _psk_window_decodes(w: np.ndarray, centre: float) -> list[tuple[float, int]]:
    """Every PSK31 candidate `find_carriers` sees in this one window's
    audio, decoded: [(dial_mhz, characters_decoded)] for whichever
    candidates the decoder's own squelch actually opened for - a tone
    find_carriers notices that is not PSK31 (an FT8/Q65/JS8 signal
    sharing the segment) decodes nothing and so is silently absent, no
    mode identification needed ahead of the decoder itself."""
    snippet_n = min(len(w), int(PSK_CANDIDATE_S * pskmod.FS))
    sa = len(w) // 2 - snippet_n // 2
    candidates = pskmod.find_carriers(w[sa:sa + snippet_n], fs=pskmod.FS, n_peaks=PSK_PEAKS_PER_SEGMENT)
    if not candidates:
        return []
    # One session hears every candidate at once (shack_sdr's psk decoder,
    # several channels; modes/sdrmode.py PskDecoder) rather than a decoder
    # per candidate as psk.py's needed. Candidates closer together than a
    # channel are one station, and it counts once.
    heard: dict[float, int] = {}

    def emit(ev):
        heard[ev["channel"]] = heard.get(ev["channel"], 0) + 1
    try:
        dec = sdrmode.PskDecoder(emit, variant="psk31", center=candidates[0], channels=candidates[1:])
    except RuntimeError:            # no shack_sdr here: _psk_report says so
        return []
    try:
        chunk = int(1.0 * pskmod.FS)
        for k in range(0, len(w), chunk):
            dec.feed(w[k:k + chunk], k / pskmod.FS)
        dec.drain()
    finally:
        dec.close()
    return [(round((centre + c) / 1e6, 6), heard[c]) for c in dec.channels if heard.get(c)]


def _psk_report(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
               beacon_hist: list[dict], bucket_s: float, window_s: float) -> dict:
    """PSK31's decoder (shack_sdr's, through ohscore.modes.sdrmode, and
    psk.find_carriers before it) both work on *demodulated* real audio - the same generic 100-
    3200 Hz digital passband every mode here uses live (ohscore.dsp.demod.
    passband falls through to DIGITAL_FILTER for any mode string it does
    not special-case, PSK31 included), not the complex IQ Channel.take()
    gives directly. _channel_audio_chunks already builds exactly that for
    FT4/Q65/JS8; this section asks it for the same thing, accumulating
    only one window_s-long buffer per candidate segment at a time (not
    the whole file's worth - the same bounded-memory reasoning as
    _channel_audio_chunks's own docstring) and finding/decoding candidates
    once each buffer fills."""
    segs = [_psk_segment(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, si, window_s)
            for si in range(len(_PSK_SEGMENTS))]
    return _psk_summary(segs, n, fs, bucket_s)


def _psk_segment(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                 beacon_hist: list[dict], si: int, window_s: float,
                 part: dict | None = None) -> list[tuple[float, list]]:
    """[(t_mid, [(dial_mhz, characters)])] per window of PSK segment `si`,
    in order. With `part` ({"warm", "lo", "hi"} grid blocks and "w0",
    "w1"), only windows w0..w1-1, for one slice of a parallel run: the
    windows are consecutive window_s blocks of one continuous audio
    stream, each decoded on its own with a fresh find_carriers and
    Decoder, so a slice that reproduces the stream from w0's first
    sample (ohsnb.analyse._audio_blocks) decodes the same windows. A
    recording shorter than one window is decoded as one partial window,
    which is never sliced."""
    seg_lo, seg_hi = _PSK_SEGMENTS[si]
    centre = (seg_lo + seg_hi) / 2.0
    win_n = int(window_s * pskmod.FS)
    out: list[tuple[float, list]] = []
    buf = np.zeros(0, np.float32)
    if part is None:
        win_i = 0
        produced_any_window = False
        for audio in _channel_audio_chunks(view, scale, n, fs, caps, info, centre, rx_corr_est, beacon_hist):
            buf = np.concatenate([buf, audio]) if len(buf) else audio
            while len(buf) >= win_n:
                w, buf = buf[:win_n], buf[win_n:]
                t_mid = (win_i * win_n + win_n / 2) / pskmod.FS
                out.append((t_mid, _psk_window_decodes(w, centre)))
                win_i += 1
                produced_any_window = True
        if not produced_any_window and len(buf) >= 256:
            out.append(((len(buf) / 2) / pskmod.FS, _psk_window_decodes(buf, centre)))
        return out
    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    win_i, w1 = part["w0"], part["w1"]
    skip = win_i * win_n - _audio_fed_before(fs, grid[part["lo"]][0])
    for audio in _channel_audio_chunks(view, scale, n, fs, caps, info, centre, rx_corr_est, beacon_hist, part):
        if skip > 0:
            drop = min(skip, len(audio))
            audio, skip = audio[drop:], skip - drop
            if not len(audio):
                continue
        buf = np.concatenate([buf, audio]) if len(buf) else audio
        while len(buf) >= win_n and win_i < w1:
            w, buf = buf[:win_n], buf[win_n:]
            t_mid = (win_i * win_n + win_n / 2) / pskmod.FS
            out.append((t_mid, _psk_window_decodes(w, centre)))
            win_i += 1
        if win_i >= w1:
            break
    return out


def _psk_summary(segs: list[list[tuple[float, list]]], n: int, fs: float, bucket_s: float) -> dict:
    total = 0
    by_bucket: dict[int, int] = {}
    dials: list[float] = []
    for windows in segs:
        for t_mid, decodes in windows:
            for dial_mhz, count in decodes:
                total += count
                idx = int(t_mid // bucket_s)
                by_bucket[idx] = by_bucket.get(idx, 0) + count
                dials.append(dial_mhz)
    nbuck = max(1, int(math.ceil((n / fs) / bucket_s)))
    buckets = [{"t0": round(i * bucket_s, 1), "decodes": by_bucket.get(i, 0)} for i in range(nbuck)]
    ok = sdr.available()
    return {"available": ok, "why": sdr.why(), "dial_mhz": None, "total": total, "buckets": buckets,
            "dial_mhz_seen": dials}
