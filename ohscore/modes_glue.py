"""The one place the engine touches ohscore.modes.

The engine and the modes were written in parallel, so this file first guessed
at several registry shapes. Now both exist it binds to the real one:
`ohscore.modes.MODES[id]` is a ModeInfo with `available`, `why`, `make_decoder`
and `make_encoder`. Guessing had a cost worth remembering - a ModeInfo matched
none of the guessed shapes, so every mode silently reported "no decoder" and
the end-to-end FT8 test skipped instead of failing.

Engine mode names differ from registry ids in one place: the engine has a
single "freedv" mode, the waveform is the `freedvMode` state key, and the
registry lists each waveform as `freedv_<waveform>`.

Every encoder takes **opts and ignores what it does not know, but the audio
offset is spelt three ways (cw: freq, ft8: offset, psk/rtty: center); the
engine says it once and all spellings are passed.
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("ohsnb.modes_glue")

OFFSET_NAMES = ("freq", "offset", "center")
# Demodulated (and, but for AM, modulated) by the engine itself. FM is in
# the list for OpenHamShack Radio; NB does not offer it, so never asks.
NATIVE = {"usb", "lsb", "am", "fm"}


def _registry() -> dict:
    try:
        from .modes import MODES
    except Exception as e:  # noqa: BLE001 - a broken modes package must not stop the radio
        log.warning("ohscore.modes not importable: %s", e)
        return {}
    return MODES


def _entry(name: str, freedv_mode: str = "700d"):
    """(ModeInfo or None, sentence explaining why it cannot run, "" if it can)."""
    key = f"freedv_{freedv_mode}" if name == "freedv" else name
    info = _registry().get(key)
    if info is None:
        return None, f"{key} is not built into this version."
    return info, ("" if info.available else info.why)


def why_not(name: str, freedv_mode: str = "700d") -> tuple[str, str]:
    """(the mode's label, the sentence saying why it cannot be decoded
    here, '' if it can), for the engine to tell the operator when a mode
    is chosen that has no decoder."""
    info, missing = _entry(name, freedv_mode)
    return (info.label if info is not None else name), missing


def available(names, freedv_mode: str = "700d") -> dict:
    """{mode: {decode, encode, missing}}. USB/LSB/AM are the engine's own;
    CW is keyed and heard by the engine, and decoded by ohscore.modes."""
    out = {}
    for n in names:
        if n in NATIVE:
            out[n] = {"decode": True, "encode": n != "am", "missing": ""}
            continue
        info, missing = _entry(n, freedv_mode)
        out[n] = {"decode": info is not None and not missing,
                  "encode": info is not None and not missing and info.make_encoder is not None,
                  "missing": missing}
    if "freedv" in names:
        out["freedv"]["waveforms"] = {k[len("freedv_"):]: (v.why if not v.available else "")
                                     for k, v in _registry().items() if k.startswith("freedv_")}
    return out


def decoder(name: str, emit: Callable[[dict], None], freedv_mode: str = "700d", **opts):
    info, missing = _entry(name, freedv_mode)
    if info is None or missing:
        return None

    def tagged(ev: dict, _n=name):
        ev = dict(ev)
        ev.setdefault("mode", _n)
        emit(ev)

    try:
        return info.make_decoder(tagged, **opts)
    except Exception as e:  # noqa: BLE001 - a decoder that will not start costs decoding, not receive
        log.warning("%s decoder failed to start: %s", name, e)
        return None


class _Render:
    def __init__(self, render):
        self._render = render

    def render(self, **opts):
        # Radio.send(mode, **msg) takes the engine mode as `mode`, so the SSTV
        # encoder's own `mode` (robot36, martinm1 ...) cannot travel in msg
        # under that name; it is sent as `sstvMode` and renamed here.
        if "sstvMode" in opts:
            opts["mode"] = opts.pop("sstvMode")
        for k in OFFSET_NAMES:
            if k in opts:
                for other in OFFSET_NAMES:
                    opts.setdefault(other, opts[k])
                break
        return self._render(**opts)


def encoder(name: str):
    """An object with render(**opts) -> 12 kHz float32 audio for the whole
    message, or None. FreeDV transmits as a stream: see streamer()."""
    if name == "freedv":
        return None
    info, missing = _entry(name)
    if info is None or missing or info.make_encoder is None:
        return None
    return _Render(info.make_encoder)


def streamer(name: str, freedv_mode: str = "700d"):
    """FreeDV's transmitter: process(12 kHz speech) -> 12 kHz modem audio
    (its frames do not divide the engine's blocks, so it cannot render once)."""
    info, missing = _entry(name, freedv_mode)
    if info is None or missing or info.make_encoder is None:
        return None
    try:
        return info.make_encoder()
    except Exception as e:  # noqa: BLE001
        log.warning("%s transmitter failed to start: %s", name, e)
        return None
