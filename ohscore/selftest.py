"""Can this installation decode every mode the app offers? One table, and
an exit status that says so.

    python3 -m ohscore.selftest ohsnb|ohsradio [--json]

Written after 0.1.10-beta.1's store images shipped with no FT8 decoder:
tools/build-store.sh removed a developer's own ohsdigi from the staged tree
and nothing put the release one in its place, so on Brian's controller FT8
was listed, chosen, and silently never decoded a slot. Every test passed,
because every test ran in a tree that had ohsdigi. The only place that
could have caught it is the built image itself, so this runs there: in the
store Containerfile, as the user the app runs as, which fails the build
(and so the package) when a decoder is missing; and from
tools/store-check.sh against an image already built (podman run
--entrypoint python3 -w /opt/shack-<app>, GUIDE §5).

For each mode in the app's own list (<app>.state.MODES) that ohscore.modes
decodes, it builds the decoder exactly as the engine does (modes_glue) and
closes it again; FreeDV once per waveform the registry knows. A decoder
that is listed as available but will not construct is a failure, as is one
listed as unavailable. FT8, FT4, Q65 and JS8 go further: a message
encoded here is decoded through the very function the slot decoder calls
with ohsdigi, so a module that imports but cannot decode is caught too;
RTTY likewise through shack_sdr's decoder.

Every mode the app offers must decode, in the store form too. Q65 and JS8
were "not carried" there until ohsdigi decoded them (10/10/2026): they
needed WSJT-X's and JS8Call's own programs, which bring Qt. The mechanism
for a mode the store form may lack (STORE_NOT_CARRIED, ohscore/host.py
_STORE_HINTS) stays, empty.

Nothing here opens a radio, a sound card or the network, and nothing is
written but a temporary folder (SSTV and HSmodem decoders want one) that
is removed again.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile

import numpy as np

from . import host, modes_glue

# Modes the store image does not carry, and the host hint naming why.
STORE_NOT_CARRIED: dict[str, str] = {}

# A standard message each slot mode must decode back to.
ROUND_TRIP = "CQ GM4BRI IO75"


def _decodes_slot(variant: str) -> str:
    """'' if ohsdigi decodes a slot of `variant` this installation encoded,
    else why not. Decoding with ohsdigi is the store form's only way (no
    jt9), so this asks ohsdigi directly, through ft8._ohsdigi_decode."""
    from .modes import ft8
    if ft8._OHSDIGI_DEC is None:
        return f"ohsdigi has no decoder here ({ft8.OHSDIGI_WHY_NOT or 'built without one'})"
    audio = ft8.Encoder().render(text=ROUND_TRIP, variant=variant, offset=1500.0)
    pcm = np.zeros(int(round(ft8.SLOT_S[variant] * ft8.FS)), dtype=np.float32)
    lead = int(0.5 * ft8.FS)
    n = min(len(audio), len(pcm) - lead)
    pcm[lead:lead + n] = 0.3 * audio[:n]
    got = [ev.get("text", "") for ev in
           ft8._ohsdigi_decode(ft8._OHSDIGI_DEC, variant, ft8._pcm16(pcm), 0.0, "", "")]
    if ROUND_TRIP not in got:
        return f"ohsdigi decoded {got!r} from {ROUND_TRIP!r}"
    return ""


def _decodes_q65() -> str:
    """'' if ohsdigi decodes a Q65-60A period this installation made, else
    why not (q65._ohsdigi_decode, the slot decoder's own call)."""
    from .modes import q65
    lb = q65._OHSDIGI_Q65
    if lb is None:
        return f"ohsdigi has no Q65 decoder here ({q65._NO_OHSDIGI})"
    audio = q65.Encoder(ohsdigi=lb).render(text=ROUND_TRIP, offset=1500.0)
    pcm = np.zeros(int(round(q65.PERIOD_S * q65.FS)), dtype=np.float32)
    lead = int(q65.START_S * q65.FS)
    pcm[lead:lead + len(audio)] = 0.3 * audio[:len(pcm) - lead]
    got = [ev.get("text", "") for ev in q65._ohsdigi_decode(lb, q65._pcm16(pcm), 0.0, "", "")]
    return "" if ROUND_TRIP in got else f"ohsdigi decoded {got!r} from {ROUND_TRIP!r}"


def _decodes_js8() -> str:
    """'' if ohsdigi decodes a JS8 period this installation made, else why
    not. Asked of ohsdigi directly, through js8._ohsdigi_decode, as FT8's
    check does: the store form has no js8 to fall back on."""
    from .modes import js8
    lb = js8._OHSDIGI_JS8
    if lb is None:
        return f"ohsdigi has no JS8 decoder here ({js8._NO_OHSDIGI})"
    (frame, i3bit), = lb.js8_frames("HB IO75", "GM4BRI", "IO75")
    audio = np.frombuffer(lb.js8_encode_audio(frame, i3bit, "normal", 1500.0), np.float32)
    pcm = np.zeros(int(round(js8.PERIOD_S * js8.FS)), dtype=np.float32)
    lead = int(0.5 * js8.FS)
    pcm[lead:lead + len(audio)] = 0.3 * audio[:len(pcm) - lead]
    got = [ev.get("text", "") for ev in js8._ohsdigi_decode(lb, js8._pcm16(pcm), 0.0)]
    want = "GM4BRI: @HB HEARTBEAT IO75"
    return "" if want in got else f"ohsdigi decoded {got!r} from {want!r}"


def _decodes_rtty() -> str:
    """'' if RTTY this installation encoded comes back through the mode
    decoder - shack_sdr's Rust decoder in its own host (modes/sdrmode.py) -
    else why not. The store image carries shack_sdr as a wheel unpacked
    at build time, the same way 0.1.10-beta.1 lost ohsdigi, so a module
    that imports but cannot decode is caught here too."""
    from .modes import rtty, sdrmode
    from . import sdr
    if not sdr.available():
        return sdr.why()
    audio = rtty.Encoder().render(text=ROUND_TRIP, center=1000.0)
    pcm = np.concatenate([np.zeros(6000, np.float32), 0.3 * audio, np.zeros(6000, np.float32)])
    dec = sdrmode.rtty_decoder(lambda ev: None)
    try:
        for i in range(0, len(pcm), 1200):
            dec.feed(pcm[i:i + 1200], i / 12_000.0)
        dec.drain()
        got = dec.text
    finally:
        dec.close()
    return "" if ROUND_TRIP in got else f"shack_sdr decoded {got!r} from {ROUND_TRIP!r}"


def _construct(mode: str, freedv_mode: str, folder: str) -> str:
    """'' if the engine's decoder for `mode` constructs, else why not."""
    info, missing = modes_glue._entry(mode, freedv_mode)
    if info is None or missing:
        return missing or f"{mode} is not in ohscore.modes"
    opts: dict = {}
    if mode == "sstv":
        opts["out_dir"] = folder
    if mode == "hsmodem":
        opts["folder"] = folder
    if mode == "freedv":
        opts["audio_out"] = lambda pcm: None
    if mode in ("ft8", "ft4", "q65", "js8"):
        opts["calls"] = lambda: ("", "")
    dec = modes_glue.decoder(mode, lambda ev: None, freedv_mode=freedv_mode, **opts)
    if dec is None:
        return "listed as available, but its decoder did not start (see the log above)"
    close = getattr(dec, "close", None)
    if close is not None:
        close()
    return ""


def check(app: str) -> list[dict]:
    """[{mode, ok, required, why}] for every decoded mode `app` offers.
    `required` is False for what may be absent: a mode in STORE_NOT_CARRIED
    in the store form (none at present), and a FreeDV waveform the installed codec2 does not offer
    (modes.freedv.available probes each one; Debian 13's codec2 has no
    working 700E) - unless it is the app's default waveform."""
    state = importlib.import_module(f"{app}.state")
    default_wf = state.REG.defaults().get("freedvMode", "700d")
    registry = modes_glue._registry()
    rows = []
    with tempfile.TemporaryDirectory(prefix="ohscore-selftest-") as folder:
        for mode in state.MODES:
            if mode in modes_glue.NATIVE:
                continue
            waveforms = [None]
            if mode == "freedv":
                waveforms = [k[len("freedv_"):] for k in registry if k.startswith("freedv_")]
            for wf in waveforms:
                label = f"freedv {wf}" if wf else mode
                required = not (host.STORE and mode in STORE_NOT_CARRIED)
                if wf and wf != default_wf and not registry[f"freedv_{wf}"].available:
                    required = False
                try:
                    why = _construct(mode, wf or "700d", folder)
                    if not why and mode in ("ft8", "ft4"):
                        why = _decodes_slot(mode)
                    if not why and mode == "js8":
                        why = _decodes_js8()
                    if not why and mode == "q65":
                        why = _decodes_q65()
                    if not why and mode == "rtty":
                        why = _decodes_rtty()
                except Exception as e:  # noqa: BLE001 - a crash is a failure to report, not to hide
                    why = f"{type(e).__name__}: {e}"
                rows.append({"mode": label, "ok": not why, "required": required, "why": why})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ohscore.selftest", description=__doc__.splitlines()[0])
    ap.add_argument("app", choices=["ohsnb", "ohsradio"], help="the app whose mode list to check")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    a = ap.parse_args(argv)
    rows = check(a.app)
    failed = [r for r in rows if not r["ok"] and r["required"]]
    if a.json:
        print(json.dumps({"app": a.app, "store": host.STORE, "rows": rows, "ok": not failed}, indent=1))
    else:
        print(f"{a.app} decoders ({'store form' if host.STORE else 'this installation'}):")
        for r in rows:
            mark = "ok" if r["ok"] else ("FAIL" if r["required"] else "absent")
            print(f"  {mark:<12} {r['mode']:<12} {r['why']}")
        print("selftest: " + ("PASS" if not failed else f"FAIL ({len(failed)})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
