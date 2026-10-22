"""What a pad's keys and knobs do in these apps (CONTROLLER-PAD.md section 3):
the actions each app declares in <app>/pad-actions.json, performed on the
engine. One implementation for both forms: the desktop window calls it in
process through shack_pad's DesktopPad (ohscore/ui/padlink.py), and the
store form's server calls it for the controller's input host
(POST /api/shack/pad/action, ohscore/server/app.py).

`ptt` is not here and never will be: a pad keys only through the app's
transmit lease, like any other client (CONTROLLER-PAD.md section 7.1), so
it reaches Engine.ptt with every check a key-up gets. `halt` stops a
transmission and needs no lease. `power` changes what goes on air, so on
the platform it needs the Transmit level (PAD_TX_ACTIONS).

No Qt: the server runs this headless.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import modegroups
from .i18n.text import _

STEPS_HZ = (10, 100, 1000, 5000, 10000)
# `filter`, one detent: which setting is the passband's width in each mode,
# and by how much it moves. The digital modes and FM have a fixed filter
# (ohscore/dsp/demod.py passband), so the knob says so rather than moving a
# setting that changes nothing. SSB moves the high edge, as the rail's
# "high" slider does: the low edge is where the voice starts, not a width.
FILTER_STEP = {"usb": ("filterHi", 100.0), "lsb": ("filterHi", 100.0), "cw": ("cwWidth", 50.0),
               "am": ("amWidth", 250.0)}
PAD_TX_ACTIONS = frozenset({"power"})


def declaration(package_dir: Path) -> tuple[dict, dict]:
    """(pad-actions.json, pad-layout.json) an app package carries."""
    return (json.loads((package_dir / "pad-actions.json").read_text(encoding="utf-8")),
            json.loads((package_dir / "pad-layout.json").read_text(encoding="utf-8")))


def mode_order(modes: list[str]) -> list[str]:
    """The order the MODE key steps through `modes` (an app's radio modes):
    the groups' order, as the Mode card shows them (ohscore/modegroups.py),
    so a press goes from one button to the one beside it - USB, LSB, CW,
    AM, FreeDV, then FT8, FT4 ... - instead of the app's state-list order,
    which had FreeDV after RTTY. Not the recent modes, as the card's
    compact form uses: the store form has no window preferences to keep
    them in, and a key that cycles must cycle the same way every time. A
    mode no group has (none today) comes last rather than being lost."""
    grouped = [m for _g, ms in modegroups.groups(modes) for m in ms]
    return grouped + [m for m in modes if m not in grouped]


class PadActions:
    """`modes`: the app's mode list in order; `bands`: band names in order
    for apps that have bands (Radio), else None; `power`: (state key, step
    per detent, lowest, highest) for the power knob."""

    def __init__(self, radio, modes: list[str], power: tuple[str, float, float, float], bands: list[str] | None = None):
        self.radio, self.power, self.bands = radio, power, bands
        self.modes = mode_order(modes)
        self.step_i = 1

    @property
    def step_hz(self) -> int:
        return STEPS_HZ[self.step_i % len(STEPS_HZ)]

    def perform(self, action: str, kind: str = "press", step: int = 1) -> None:
        """Do one action. ValueError (a sentence) when it cannot be done
        here and now; an unknown action is ignored, as a layout naming an
        action this version lacks must not stop the pad."""
        r, s = self.radio, self.radio.state()
        n = int(step or 1)
        if action == "halt":
            r.halt()
        elif action == "tune":
            r.set(vfo=s["vfo"] + n * self.step_hz)
        elif action == "step":
            self.step_i = (self.step_i + 1) % len(STEPS_HZ)
        elif action == "mode:next":
            i = self.modes.index(s["mode"]) if s["mode"] in self.modes else -1
            r.set(mode=self.modes[(i + 1) % len(self.modes)])
        elif action == "mute":
            r.set(mute=not s["mute"])
        elif action == "volume":
            r.set(volume=min(1.0, max(0.0, round(s["volume"] + 0.05 * n, 2))))
        elif action == "record":
            if r.rec is not None:
                r.stop_recording()
            else:
                r.start_recording()
        elif action == "channel":
            mems = r.memories()
            if not mems:
                raise ValueError(_("There are no memories to step through"))
            names = [m["name"] for m in mems]
            cur = getattr(self, "_mem", -1)
            self._mem = (cur + n) % len(names)
            r.recall(names[self._mem])
        elif action == "auto-tune" and hasattr(r, "auto_tune"):
            r.auto_tune()
        elif action in ("band", "band:next") and self.bands:
            here = s.get("band") or ""
            i = self.bands.index(here) if here in self.bands else -1
            r.band(self.bands[(i + (n if action == "band" else 1)) % len(self.bands)])
        elif action == "power":
            key, per, lo, hi = self.power
            r.set(**{key: min(hi, max(lo, round(s[key] + per * n, 3)))})
        elif action == "nr":
            r.set(nr=not s.get("nr"))
        elif action == "filter":
            if s.get("mode") not in FILTER_STEP:
                raise ValueError(_("The filter is fixed in {mode}").format(mode=str(s.get("mode", "")).upper()))
            key, per = FILTER_STEP[s["mode"]]
            spec = r.STATE.spec[key]
            r.set(**{key: min(spec["max"], max(spec["min"], round(s[key] + per * n, 1)))})
        elif action == "beacon-hold" and "beaconMode" in s:
            # The window's H key: Hold, or back to Auto from it; Manual goes
            # to Hold too, because the key means "stop following now".
            r.set(beaconMode="auto" if s["beaconMode"] == "hold" else "hold")

    def faces(self) -> dict:
        """Live faces for keys whose value is worth seeing (shack_pad's
        `faces()`), and whether the app is on the air."""
        s = self.radio.state()
        rec = getattr(self.radio, "rec", None) is not None
        key, _per, _lo, _hi = self.power
        p = s.get(key)
        return {"onAir": bool(s.get("keyed")),
                "faces": {"step": {"l1": "STEP", "l2": f"{self.step_hz} Hz"},
                          "mode:next": {"l1": "MODE", "l2": str(s.get("mode", "")).upper()},
                          "mute": {"l1": "MUTE", "l2": "ON" if s.get("mute") else "", "tone": "warn" if s.get("mute") else ""},
                          "power": {"l1": "PWR", "l2": f"{p:g}" if isinstance(p, (int, float)) else ""},
                          "nr": {"l1": "NR", "l2": "ON" if s.get("nr") else "", "tone": "active" if s.get("nr") else ""},
                          "beacon-hold": {"l1": "BEACON", "l2": str(s.get("beaconMode", "")).upper()},
                          # Recording is amber with a filled dot (Brian, 17/10/2026, overhaul
                          # decision 7). It took the transmit red until then, as a recorder's REC
                          # lamp does, but red on a pad key is read as on the air from across
                          # the room, and red is kept for that alone. Amber still stands out, and
                          # a forgotten recording, which fills the disk, is still seen.
                          "record": {"l1": "REC", "l2": "\u25cf ON" if rec else "",
                                     "tone": "warn" if rec else ""},
                          "halt": self._halt_face(s)}}

    def _halt_face(self, s: dict) -> dict:
        """HALT TX dimmed (tone "disabled") in a run that can never
        transmit - started --receive-only, or a receive-only device - so
        the pad looks like what it is (overhaul section 5.9). Dimmed is a
        face only: perform("halt") still halts, whatever the face says,
        because halting never gets harder (section 7.1). A recording being
        played has no transmitter for now, not for the run, so it keeps
        the ordinary face."""
        never = bool(getattr(self.radio, "receive_only", False)) or (
            bool(s.get("running")) and not s.get("canTx", True) and not s.get("playing"))
        return {"l1": "HALT", "l2": "TX", "tone": "disabled" if never else ""}
