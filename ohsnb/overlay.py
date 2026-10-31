"""QO-100 NB's overlay/1 items (CLIENT-UI-PLAN.md §3, docs/SERVER-API.md
"overlay/1"): what a client draws on NB's scopes. The shared producer
(ohscore/server/overlay.py) knows Radio's sources and the terrestrial band
plan, which on 10 GHz is one "satellites" segment the width of the
transponder and nothing else, so before this NB's scopes had a dial line
and no labels at all (parity check, 31/10/2026). This subclass, given to
the server by AppInfo.overlay, swaps the band for NB's own and adds what
the hand-built QO-100 NB screens drew from data NB already has; nothing is
invented for the overlay (§3.3).

| layer | kind | source | kept |
|---|---|---|---|
| band | segment | ohsnb/bandplan.py SEGMENTS, the plan the transmit guard checks | 10 s |
| bookmarks | bookmark | the engine's memories (`GET api/memories`: the band-plan presets, then the operator's), what the old scope ticked and named | 10 s |
| beacons | beacon | ohsnb/bandplan.py BEACONS; the one beacon lock uses is `active` | 10 s |
| dial, sessions | as the shared producer | the state, the decoder sessions | each look |
| signals | signal | the band skimmer's last list (BandSkimmer.last) | each look |
| alerts | alert | the over-power watch's open events (signals over the beacon, LEILA) | each look |

The skimmer is read from its last published list, never by subscribing
to the "skim" feed: a feed drained counts as the user interface being
alive to the transmit watchdog (Engine._supervise; ohsnb/screens.py says
the same of the screens' follower). Every action only tunes, at Control
level (§3.2, §5.6).
"""
from __future__ import annotations

from ohscore.i18n.text import _
from ohscore.server.overlay import Overlay, _item, _tune

from . import bandplan

# Bookmarks within this of a beacon's frequency are the beacon's own
# presets ("Lower beacon", tuned 300 Hz below it for its CW tone). The
# beacon is drawn once, as a beacon (marked when beacon lock follows it),
# with its bookmark's tune as its action; two labels for one carrier was
# what the first look at the emulator showed.
SAME_HZ = 2000.0


def _beside(f: float, memories: list[dict]) -> dict | None:
    for m in memories:
        x = m.get("dl")
        if isinstance(x, (int, float)) and abs(f - x) <= SAME_HZ:
            return m
    return None


def _segment_role(allowed) -> str:
    """By the modes a segment allows, as the shared producer names the
    terrestrial plan's: `segment.beacon` for one nobody may transmit in."""
    if not allowed:
        return "segment.beacon"
    if allowed == {"cw"}:
        return "segment.cw"
    if allowed == {"ssb"}:
        return "segment.ssb"
    if allowed == {"digital", "cw"}:
        return "segment.cw-digi"
    return "segment.all"


class NbOverlay(Overlay):
    SLOW_LAYERS = ("band", "bookmarks", "beacons")
    FAST_LAYERS = ("dial", "sessions", "signals", "alerts")

    def _band(self, st, lo, hi) -> list[dict]:
        return [_item(f"seg:qo100nb:{int(a)}-{int(b)}", "segment", "band", a, b, label, source="bandplan:qo100nb",
                      role=_segment_role(allowed))
                for a, b, label, allowed, _bw in bandplan.SEGMENTS if b >= lo and a <= hi]

    def _bookmarks(self, st, lo, hi) -> list[dict]:
        out = []
        beacons = [b["dl"] for b in bandplan.BEACONS.values()]
        for m in self.radio.memories():
            f = m.get("dl")
            if not isinstance(f, (int, float)) or not lo <= f <= hi or not m.get("name"):
                continue
            if any(abs(f - x) <= SAME_HZ for x in beacons):
                continue                    # drawn as the beacon (SAME_HZ)
            out.append(_item("bm:" + str(m["name"]), "bookmark", "bookmarks", f, f, str(m["name"]),
                             source="memories", detail=str(m.get("mode") or "").upper(),
                             role="bookmark" if m.get("builtin") else "bookmark.mine",
                             actions=[_tune(float(f), str(m.get("mode") or "usb"))]))
        return out

    def _beacons(self, st, lo, hi) -> list[dict]:
        memories = self.radio.memories()
        used = str(st.get("beaconUsed") or "")
        out = []
        for key, b in bandplan.BEACONS.items():
            f = b["dl"]
            if not lo <= f <= hi:
                continue
            name = str(b["name"])
            m = _beside(f, memories)
            out.append(_item("bcn:" + key, "beacon", "beacons", f, f, name.split(" (")[0], short=name.split()[0],
                             source="bandplan:beacons", detail=name, role="beacon.qo100", active=key == used,
                             actions=[_tune(float(m["dl"]), str(m.get("mode") or "usb"))] if m else None))
            # Named at any zoom: there are four, at the band's edges and
            # middle, and the shared default (400 Hz a pixel, for the NCDXF
            # beacons among Radio's channels) is just finer than the wide
            # scope's 500 kHz across a TV.
            out[-1]["readAtHzPerPx"] = None
        return out

    def _signals(self, st, lo, hi) -> list[dict]:
        sk = getattr(self.radio, "skim", None)
        out = []
        for e in list(getattr(sk, "last", None) or []):
            # The skimmer's beacon entries are the beacons layer's. A bare
            # "signal" is a carrier not yet told apart (the simulator's band
            # has a hundred and more): a tick each would be noise over the
            # waterfall that already shows them, so only what the skimmer
            # has named (SSB, FT8, a calling window...) and heard lately.
            if e.get("kind") in ("beacon", "signal") or not e.get("active") \
                    or not isinstance(e.get("f"), (int, float)):
                continue
            a, b = float(e.get("lo") or e["f"]), float(e.get("hi") or e["f"])
            if b < lo or a > hi:
                continue
            calls = e.get("calls") or []
            label = str(calls[0]) if calls else str(e.get("label") or e.get("kind") or "")
            tune = e.get("dial") or e["f"]
            out.append(_item(f"sig:{e.get('id')}", "signal", "signals", a, b, label, short=str(e.get("label") or ""),
                             source="skimmer", detail=", ".join(calls[:4]), role="signal", centre=float(e["f"]),
                             active=bool(e.get("active")), actions=[_tune(float(tune), str(e.get("mode") or "usb"))]))
        return out

    def _alerts(self, st, lo, hi) -> list[dict]:
        view = getattr(self.radio, "overpower_view", None)
        if view is None:
            return []
        out = []
        for e in view().get("events") or []:
            f = e.get("freq")
            if not e.get("active") or not isinstance(f, (int, float)) or not lo <= f <= hi:
                continue
            if e.get("kind") == "leila":
                label, role = _("LEILA?"), "alert.leila"
            else:
                label = _("{db:+.1f} dB over the beacon").format(db=float(e.get("excessDb") or 0.0))
                role = "alert.overpower"
            out.append(_item(f"alert:{e.get('id')}", "alert", "alerts", f, f, label, source="overpower",
                             short=_("Over"), detail=str(e.get("call") or ""), role=role, active=True,
                             actions=[_tune(float(f), str(st.get("mode") or "usb"))]))
        return out


__all__ = ["NbOverlay"]
