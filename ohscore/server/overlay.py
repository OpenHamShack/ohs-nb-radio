"""overlay/1 items (CLIENT-UI-PLAN.md §3, docs/SERVER-API.md "overlay/1"):
what a client draws on top of its waterfall, from what the app already
has - nothing is invented for the overlay (§3.3).

The plan has each app convert its routes through a shared helper in
ohs-libs (`shack_spectrum.overlay`). That helper does not exist yet
(shack_spectrum 0.2.0 has the row, reduce, levels and sender only), so
this is the conversion for Radio and NB in one module of their own
server, as §3.3 allows; it moves to the helper when there is one.

Layers, and where each comes from:

| layer | kind | source |
|---|---|---|
| band | segment | the plan in force for the station profile (txguard.GUARD's shack_bandplan context) |
| dial | dial, passband, tx | the state: the dial, the passband the scopes draw, the transmit dial when keyed |
| channels | channel | Radio's local frequencies (api/local-frequencies), all but the beacons |
| beacons | beacon | the NCDXF/IARU beacons in the same list (its `beacon` category) |
| stations | station | the band scan's FM and DAB lists (api/fm/stations, api/dab/stations) |
| sessions | session | the decoder sessions (api/decoders) |

NB has no local frequencies or band scan (those layers are simply
absent); spots, bookmarks, alerts and signals are not produced yet.

Every action only tunes or plays, at Control level (§3.2, §5.6: never a
transmit action). Labels are in the server's language, like every other
sentence this server sends; the band plan's segment labels are the
dataset's own (English). Paths in actions are relative to the app's base,
and deliberately not given `url`s by with_urls: an item is the same
whether it comes on the socket or over HTTP.
"""
from __future__ import annotations

import logging
import re
import threading
import time

from .. import txguard
from ..dsp.demod import passband
from ..i18n.text import _

log = logging.getLogger("ohscore.server.overlay")

# The label shows once the view is at or below this many Hz a pixel
# (§3.2); the band's segments always (None). A channel at 400 Hz/px is the
# plan's example; FM stations are 100 kHz apart, DAB blocks 1.7 MHz.
READ_AT = {"segment": None, "dial": None, "passband": None, "tx": None, "channel": 400.0, "beacon": 400.0,
           "station": 2000.0, "session": 1000.0}
PRIO = {"segment": 10, "beacon": 40, "station": 50, "channel": 60, "session": 80, "passband": 90, "dial": 100,
        "tx": 100}
# A session decoding now is drawn as active (§3.2).
ACTIVE_STATES = ("running", "synced")


def _role_part(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", str(s).lower()).strip("-")
    return s if s and s[0].isalpha() else "other"


def in_range(item: dict, lo: float, hi: float) -> bool:
    return item["hiHz"] >= lo and item["loHz"] <= hi


def with_margin(lo: float, hi: float) -> tuple[float, float]:
    """The range items are sent for: the view plus half its own span each
    side (§3.1 "a margin of half a span"; the plan does not say which
    span, and the view's is the one that makes a small pan need nothing
    new)."""
    half = (hi - lo) / 2
    return lo - half, hi + half


def _item(id_: str, kind: str, layer: str, lo: float, hi: float, label: str, *, source: str, short=None,
          detail="", role=None, active=False, actions=None, centre=None) -> dict:
    out = {"id": id_, "kind": kind, "layer": layer, "loHz": float(lo), "hiHz": float(hi),
           "centreHz": float((lo + hi) / 2 if centre is None else centre), "label": label,
           "short": short if short is not None else label, "detail": detail, "prio": PRIO[kind],
           "readAtHzPerPx": READ_AT[kind], "role": role or kind, "active": bool(active), "expires": None,
           "source": source}
    if actions:
        out["actions"] = actions
    return out


def _tune(freq: float, mode: str) -> dict:
    return {"id": "tune", "label": _("Tune"), "do": "post", "path": "api/set",
            "body": {"changes": {"vfo": freq, "mode": mode}}, "level": "control"}


class Overlay:
    """The items of every layer an app has, for a range. The slow layers
    (band, channels, beacons, stations) are kept for SLOW_S per range,
    since a local-frequencies listing is tens of milliseconds and a socket
    asks every EVERY_S for the fast ones (dial, sessions)."""

    EVERY_S = 0.25
    SLOW_S = 10.0

    def __init__(self, radio, clock=time.monotonic):
        self.radio, self.clock = radio, clock
        self.lock = threading.Lock()
        self._slow: dict = {}       # (lo, hi) -> (at, items)

    def items(self, lo: float, hi: float) -> list[dict]:
        """Items touching lo..hi plus the half-span margin."""
        a, b = with_margin(lo, hi)
        st = self.radio.state()
        now = self.clock()
        key = (round(a), round(b))
        with self.lock:
            hit = self._slow.get(key)
            if hit is None or now - hit[0] >= self.SLOW_S:
                self._slow = {k: v for k, v in self._slow.items() if now - v[0] < self.SLOW_S}
                hit = (now, self._layers(("band", "channels", "stations"), st, a, b))
                self._slow[key] = hit
        out = list(hit[1]) + self._layers(("dial", "sessions"), st, a, b)
        return [i for i in out if in_range(i, a, b)]

    def _layers(self, names, st, lo, hi) -> list[dict]:
        out = []
        for name in names:
            try:
                out += getattr(self, "_" + name)(st, lo, hi)
            except Exception:  # noqa: BLE001  one source failing never takes the overlay with it
                log.exception("overlay layer %s failed", name)
        return out

    # ------------------------------------------------------------ layers
    def _band(self, st, lo, hi) -> list[dict]:
        plan = st.get("plan") or ""
        ctx = txguard.GUARD.context(txguard.profile(st), "" if plan == "auto" else plan)
        if ctx.plan is None:
            return []
        out = []
        for seg in txguard.GUARD.bp.limits(ctx, lo, hi)["segments"]:
            modes = seg.get("modes") or []
            role = "segment." + _role_part(seg.get("kind") or ("all" if len(modes) >= 4 else "-".join(sorted(modes))
                                                                or "other"))
            out.append(_item(f"seg:{ctx.plan['id']}:{seg['loHz']}-{seg['hiHz']}", "segment", "band", seg["loHz"],
                             seg["hiHz"], seg.get("label") or "", source=f"bandplan:{ctx.plan['id']}", role=role))
        return out

    def _dial(self, st, lo, hi) -> list[dict]:
        vfo = st.get("vfo")
        if not vfo:
            return []
        mode = str(st.get("mode") or "")
        out = [_item("dial", "dial", "dial", vfo, vfo, mode.upper(), source="state", role="dial")]
        try:
            a, b = passband(mode, st["filterLo"], st["filterHi"], st["cwPitch"], st["cwWidth"], st["amWidth"])
            out.append(_item("passband", "passband", "dial", vfo + a, vfo + b, "", source="state", role="passband",
                             centre=vfo))
        except KeyError:
            pass
        if st.get("keyed") and st.get("txDial"):
            tx = st["txDial"]
            out.append(_item("tx", "tx", "dial", tx, tx, _("TX"), source="state", role="tx", active=True))
        return out

    def _channels(self, st, lo, hi) -> list[dict]:
        if not hasattr(type(self.radio), "localfreq"):
            return []
        out = []
        for e in self.radio.local_frequencies(None, None)["entries"]:
            f = e["freqHz"]
            if not lo <= f <= hi:
                continue
            beacon = e["category"] == "beacon"
            cat = e.get("userCategory") or e["category"]
            detail = " · ".join(x for x in (e.get("sub") or "", e.get("notes") or "") if x)
            out.append(_item("lf:" + e["id"], "beacon" if beacon else "channel", "beacons" if beacon else "channels",
                             f, f, e["name"], source="local-frequencies:" + e.get("source", ""), detail=detail,
                             role="beacon." + _role_part(e.get("source") or cat) if beacon
                             else "channel." + _role_part(cat),
                             actions=[_tune(f, e["mode"])]))
        return out

    def _stations(self, st, lo, hi) -> list[dict]:
        scan = getattr(self.radio, "bandscan", None)
        if scan is None:
            return []
        out = []
        for s in scan.view("fm").get("stations") or []:
            f = (s.get("best") or {}).get("hz")
            if f is None or not lo <= f <= hi:
                continue
            ps = (s.get("ps") or "").strip()
            label = ps or f"{f / 1e6:.2f}"
            out.append(_item(f"fm:{s.get('pi') or int(f)}", "station", "stations", f, f, label,
                             source="band-scan:fm", detail=s.get("ptyName") or "", role="station.fm",
                             actions=[_tune(f, "wfm")]))
        for e in scan.view("dab").get("ensembles") or []:
            f = e.get("freqHz")
            if f is None or not lo <= f <= hi:
                continue
            services = e.get("services") or []
            # Each service is an action, the first being the item's own
            # (§3.2): a DAB station is played by a decoder session.
            acts = [{"id": f"play:{x['sid']}", "label": x.get("label") or x["sid"], "do": "post",
                     "path": "api/decoders/sessions",
                     "body": {"decoder": "dab", "freqHz": f, "params": {"block": e.get("block"), "service": x["sid"]}},
                     "level": "control"} for x in services if x.get("sid")]
            out.append(_item(f"dab:{e.get('block') or int(f)}", "station", "stations", f, f,
                             e.get("label") or e.get("block") or "", short=e.get("block"), source="band-scan:dab",
                             detail=", ".join(x.get("label") or x.get("sid", "") for x in services),
                             role="station.dab", actions=acts or None))
        return out

    def _sessions(self, st, lo, hi) -> list[dict]:
        dec = getattr(self.radio, "decoders", None)
        if dec is None:
            return []
        out = []
        for s in dec.sessions():
            f = s.get("freqHz")
            # The mode's own decoder (`vfo`) sits on the dial, drawn already.
            if s.get("id") == "vfo" or f is None or not lo <= f <= hi:
                continue
            name = str(s.get("decoder") or "").upper()
            out.append(_item("ds:" + s["id"], "session", "sessions", f, f, name, source="decoders",
                             detail=s.get("whyText") or s.get("state") or "",
                             role="session." + _role_part(s.get("decoder") or ""),
                             active=s.get("state") in ACTIVE_STATES))
        return out
