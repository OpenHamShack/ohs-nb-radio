"""FT8/FT4's second decoder: run beside the one whose decodes the operator
sees, on the same samples, and say where the two disagree.

History. Brian's rule (06/10/2026) was that ohsdigi, our own FT8/FT4
decoder (rust/ohsdigi), would replace jt9 only once it decoded as much as
jt9 did on real slots as well as simulated ones. This module was how real
slots got measured: with OHSDIGI_SHADOW=1, every slot jt9 decoded was also
handed to ohsdigi and the two compared in the log. On 07/10/2026 a
three-hour QO-100 recording gave 2,659 decodes, every one found by both,
and ohsdigi became the decoder (ohscore/modes/ft8.py). The comparison now
runs the other way: ohsdigi decodes, jt9 is the shadow.

It stays on by default wherever both decoders are installed - the
evidence so far is one band, one recording, and a disagreement on the air
is worth seeing - and costs a jt9 run per decode pass, after the
operator's decodes have gone out. OHSDIGI_SHADOW=0 turns it off (the name
is kept from when it named the shadow; "1" is the default now). The shadow
never emits, and any fault in it is logged and swallowed.

What is kept: one log line per decode pass where the decoders disagree
(INFO; agreement is DEBUG, or the log would carry eight lines a minute
saying nothing), and running counts for the diagnostics report (summary()).

Decodes are paired by message text (both unpack with WSJT-X's rules) and,
so that a message heard twice in one slot pairs with the right copy, by
frequency and DT within jt9's printing resolution: whole hertz and tenths
of a second, so 1 Hz and 0.11 s.
"""

from __future__ import annotations

import collections
import logging
import os
import threading
import time

ENV = "OHSDIGI_SHADOW"
log = logging.getLogger("ohscore.modes.ohsdigi")
OFF = ("0", "false", "no", "off")

# How many recent disagreements the diagnostics report quotes.
KEEP_RECENT = 10


def enabled() -> bool:
    """Shadow decoding is on unless the environment turns it off. Whether
    there is a second decoder to run is the caller's question."""
    return os.environ.get(ENV, "").strip().lower() not in OFF


def _freq(ev: dict) -> float:
    # Events carry jt9's whole-hertz "df"; ohsdigi's own decode dicts (as
    # ohsnb.analyse handled them before the switch) carry "freq".
    return float(ev["df"] if "df" in ev else ev["freq"])


def pair(first: list[dict], second: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """(pairs, first only, second only): same text, then the closest frequency."""
    left = list(second)
    pairs = []
    only_first = []
    for ev in first:
        best = None
        for o in left:
            dfreq = abs(_freq(o) - _freq(ev))
            if (o["text"] == ev["text"] and dfreq <= 1.0 and abs(o["dt"] - ev["dt"]) <= 0.11
                    and (best is None or dfreq < best[0])):
                best = (dfreq, o)
        if best is None:
            only_first.append(ev)
        else:
            left.remove(best[1])
            pairs.append((ev, best[1]))
    return pairs, only_first, left


def _where(ev: dict) -> str:
    return f'{ev["text"]} @{_freq(ev):.0f} Hz {ev["dt"]:+.1f} s'


class _Tally:
    """Running counts for one mode and one (decoder, shadow) pairing - kept
    apart so that changing the setting mid-run does not mix "ohsdigi only"
    with "jt9 only"."""

    def __init__(self):
        self.passes = 0
        self.found = [0, 0]           # decodes: the decoder's, the shadow's
        self.both = 0
        self.alone = [0, 0]           # found by that one only
        self.disagreed = 0            # passes with any decode found by one only
        self.secs = [0.0, 0.0]
        self.worst = [0.0, 0.0]
        self.recent: collections.deque[str] = collections.deque(maxlen=KEEP_RECENT)


_lock = threading.Lock()
_tally: dict[tuple[str, str, str], _Tally] = {}
_failures: dict[tuple[str, str], int] = {}


def record(variant: str, slot_t0: float, primary: str, primary_events: list[dict], primary_s: float,
           shadow: str, shadow_events: list[dict], shadow_s: float) -> dict:
    """Compare one decode pass's results, log a disagreement, count both.
    Never raises: a fault here must not touch decoding."""
    try:
        pairs, only_p, only_s = pair(primary_events, shadow_events)
        res = {
            "variant": variant,
            "slot": slot_t0,
            primary: len(primary_events),
            shadow: len(shadow_events),
            "both": len(pairs),
            f"{primary}_only": [_where(e) for e in only_p],
            f"{shadow}_only": [_where(e) for e in only_s],
            f"{primary}_s": round(primary_s, 3),
            f"{shadow}_s": round(shadow_s, 3),
        }
        stamp = time.strftime("%H:%M:%S", time.gmtime(slot_t0))
        line = (f"{variant} {stamp}: {primary} {len(primary_events)}, {shadow} {len(shadow_events)}, "
                f"both {len(pairs)}; {primary} {primary_s:.3f} s, {shadow} {shadow_s:.3f} s"
                + (f"; {primary} only: " + "; ".join(res[f"{primary}_only"]) if only_p else "")
                + (f"; {shadow} only: " + "; ".join(res[f"{shadow}_only"]) if only_s else ""))
        with _lock:
            t = _tally.setdefault((variant, primary, shadow), _Tally())
            t.passes += 1
            for i, (evs, alone, secs) in enumerate(((primary_events, only_p, primary_s),
                                                    (shadow_events, only_s, shadow_s))):
                t.found[i] += len(evs)
                t.alone[i] += len(alone)
                t.secs[i] += secs
                t.worst[i] = max(t.worst[i], secs)
            t.both += len(pairs)
            if only_p or only_s:
                t.disagreed += 1
                t.recent.append(line)
        if only_p or only_s:
            log.info("decoder shadow %s", line)
        else:
            log.debug("decoder shadow %s", line)
        return res
    except Exception:  # noqa: BLE001 - see docstring
        log.exception("decoder shadow comparison failed")
        return {}


def failed(variant: str, shadow: str, exc: BaseException) -> None:
    """The shadow decoder raised: counted, and logged in full the first
    time for each mode and decoder (it would otherwise repeat every pass)."""
    with _lock:
        n = _failures[(variant, shadow)] = _failures.get((variant, shadow), 0) + 1
    if n == 1:
        log.warning("decoder shadow %s: %s failed: %s", variant, shadow, exc, exc_info=exc)


def summary() -> dict:
    """For the diagnostics report: per mode and pairing, the passes
    compared, the decodes each decoder found and found alone, their mean
    and worst decode times, and the last few disagreements; and how often
    a shadow decoder failed. Empty when nothing has been compared."""
    out: dict = {}
    with _lock:
        tallies = sorted(_tally.items())
        fails = sorted(_failures.items())
        for (variant, p, s), t in tallies:
            n = max(t.passes, 1)
            text = (f"{t.passes} passes; decodes {p} {t.found[0]}, {s} {t.found[1]}, both {t.both}, "
                    f"{p} only {t.alone[0]}, {s} only {t.alone[1]}; passes that disagreed {t.disagreed}; "
                    f"{p} {t.secs[0] / n:.3f} s mean, {t.worst[0]:.3f} s worst; "
                    f"{s} {t.secs[1] / n:.3f} s mean, {t.worst[1]:.3f} s worst")
            out[f"{variant}: {p}, {s} shadowing"] = text
            if t.recent:
                out[f"{variant}: {p}, {s} shadowing, last disagreements"] = list(t.recent)
    for (variant, s), count in fails:
        out[f"{variant}: {s} shadow failures"] = count
    return out


def reset() -> None:
    """Forget the counts (tests)."""
    with _lock:
        _tally.clear()
        _failures.clear()
