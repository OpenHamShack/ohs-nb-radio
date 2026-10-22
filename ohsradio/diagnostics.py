"""What OpenHamShack Radio adds to the shared diagnostics report (ohscore/diag.py,
Help › Save diagnostics…).

The shared report already carries the versions, the log, the redacted
config, the engine state and the open radio's IIO attributes. What it
cannot know is what HAM needs to explain the commonest HAM failure - a
Pluto that works in NB and not on 2 m (05/10/2026) - and it has nothing
to say when the radio would not open, which is when the report is wanted
most. So HAM adds, under the report's "more" section:

- **Find, fresh**: what discovery sees now, Pluto and Hermes-Lite 2.
- **The Pluto**: from the open device when there is one, else from a fresh
  IIO context - reachable or why not, model, serial, firmware, chip
  identity, tuning range, FIR, and whether the AD9364 fix can run on that
  firmware or only manual steps apply.

Every probe runs on its own thread with a deadline and records its failure
as a sentence: findings() never raises and never takes more than about
twenty seconds, which is why the window runs it off the UI thread.
"""
from __future__ import annotations

from . import plutofix

DISCOVERY_TIMEOUT_S = 12.0
PROBE_TIMEOUT_S = 4.0


def discovery(timeout_s: float = DISCOVERY_TIMEOUT_S) -> list[str]:
    """Find's list, fresh, as lines; failures as lines too."""
    lines: list[str] = []

    def pluto_find():
        from ohscore.devices import pluto
        notes: list[str] = []
        return pluto.discover(1.0, notes), notes

    ok, val = plutofix._call_with_timeout(pluto_find, timeout_s)
    if ok:
        found, notes = val
        lines += [f"Pluto: {u}  {d}" for u, d in found] or ["Pluto: none found"]
        lines += [f"Pluto note: {n}" for n in notes]
    else:
        lines.append(f"Pluto: discovery failed ({val})")

    def hl2_find():
        from ohscore.devices import hl2
        return hl2.discover(1.0)

    ok, val = plutofix._call_with_timeout(hl2_find, 5.0)
    if ok:
        lines += [f"HL2: {r}" for r in val] or ["HL2: none found"]
    else:
        lines.append(f"HL2: discovery failed ({val})")
    return lines


def pluto_findings(uri: str, dev=None, timeout_s: float = PROBE_TIMEOUT_S, identify=None) -> list[str]:
    """The Pluto's side of the report, as lines."""
    info = plutofix.from_device(dev) if dev is not None and getattr(dev, "uri", None) == uri else None
    source = "the open radio"
    if info is None:
        try:
            info = (identify or (lambda u: plutofix.probe(u, timeout_s)))(uri)
        except Exception as e:  # noqa: BLE001 - the report must survive a probe that misbehaves
            info = plutofix.PlutoInfo(uri, error=f"{type(e).__name__}: {e}")
        source = "a fresh connection"
    out = [f"address: {uri}", f"read from: {source}",
           "reachable: yes" if info.reachable else f"reachable: no ({info.error or 'no answer'})"]
    if not info.reachable:
        return out
    rng = info.rx_range
    plan = plutofix.firmware_plan(info.fw_version)
    out += [f"model: {info.model or '?'}", f"hw_serial: {info.serial or '?'}",
            f"firmware: {info.fw_version or '?'}", f"ad9361-phy model: {info.identity or 'not reported'}",
            f"tuning range: {rng[0] / 1e6:g}-{rng[1] / 1e6:g} MHz" if rng else "tuning range: unknown",
            f"AD9364 fix: {plan.method or 'manual only - ' + plan.reason}"]
    if dev is not None and getattr(dev, "kind", "") == "pluto":
        out.append(f"FIR: {getattr(dev, 'fir', '') or '?'}")
    else:
        out.append("FIR: unknown until the radio is open")
    out += [f"out of reach: {plutofix.band_label(b)}" for b in plutofix.bands.BANDS
            if not b.deferred and plutofix.out_of_reach(info.identity, b)]
    return out


def findings(radio, discover: bool = True, identify=None) -> dict:
    """HAM's additions to the report, for ohscore.ui.diagnostics.gather(more=)."""
    cfg = getattr(radio, "cfg", {}) or {}
    dev = getattr(radio, "dev", None)
    out: dict = {}
    if discover:
        out["find (fresh)"] = discovery()
    if cfg.get("device") == "pluto" or getattr(dev, "kind", "") == "pluto":
        uri = getattr(dev, "uri", None) if getattr(dev, "kind", "") == "pluto" else None
        out["pluto"] = pluto_findings(uri or cfg.get("plutoUri") or plutofix.DEFAULT_URI, dev,
                                      identify=identify)
    return out
