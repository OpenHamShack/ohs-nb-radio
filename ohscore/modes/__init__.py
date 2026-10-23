"""Mode registry: one entry per mode the console can offer, whether or not
its optional package is actually installed on this host. DESIGN.md's rule
for all of them is the same -- list it anyway, with the sentence saying
what to install, rather than making the mode vanish -- so an operator who
opens the console on a bare laptop sees the whole roster and why half of
it is greyed out, instead of wondering if the build is broken.

`available` and `why` are computed once, here, at import time -- not on
every console connection. That's still "lazy" in the sense DESIGN.md
means it: nothing is probed until something imports ohscore.modes (which
itself only happens once the daemon starts), and every submodule that
needs a real probe (freedv's codec2 handles; ft8's shutil.which) caches
its own result, so re-importing this package within one process is free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Callable

from . import cw, rtty, psk, ft8, freedv, js8, q65, sstv, hsmodem, kgstv, sdrmode
from .. import sdr


@dataclass(frozen=True)
class ModeInfo:
    id: str
    label: str
    kind: str  # "voice" | "text" | "slot" | "image" | "data"
    available: bool
    why: str  # empty when available; the sentence to show the operator otherwise
    offset_hz: float  # default audio offset (or passband centre, for wideband modes)
    passband_hz: tuple[float, float]
    make_decoder: Callable[..., object]
    make_encoder: Callable[..., object] | None  # None where there's no sensible standalone encoder (FT8/FT4 use jt9's wrapper itself; SSTV decode-only modes)
    # Decoded by a shack_sdr session (modes/sdrmode.py): the engine hands
    # its decoder a link to the engine's own decoder host.
    hosted: bool = False


def _text_entry(id_: str, label: str, module, offset: float, passband: tuple[float, float], **fixed) -> ModeInfo:
    return ModeInfo(
        id=id_, label=label, kind="text", available=True, why="",
        offset_hz=offset, passband_hz=passband,
        make_decoder=partial(module.Decoder, **fixed),
        make_encoder=partial(module.Encoder().render, **fixed) if hasattr(module, "Encoder") else None,
    )


# RTTY: shack_sdr's Rust decoder (RADIO-SDR-PLAN §8.1) for receive, in both
# apps; rtty.py's encoder for Enable TX and send(), unchanged. Listed with
# the reason on a package built for no particular processor, which carries
# no shack_sdr (ohscore/sdr.py).
_rtty_entry = ModeInfo(
    id="rtty", label="RTTY 45.45/170", kind="text", available=sdr.available(), why=sdr.why(),
    offset_hz=1000.0, passband_hz=(830.0, 1170.0),
    make_decoder=sdrmode.rtty_decoder,
    make_encoder=rtty.Encoder().render,
    hosted=True,
)


def _psk_entry(variant: str, label: str, passband: tuple[float, float]) -> ModeInfo:
    """PSK31/63/125: shack_sdr's Rust `psk` decoder for receive (RADIO-SDR-PLAN
    §8.5 M2), several stations at once (modes/sdrmode.py PskDecoder);
    psk.py's encoder for Enable TX and send(), unchanged - it renders all
    three speeds, so PSK125 transmits as the other two do."""
    return ModeInfo(
        id=variant, label=label, kind="text", available=sdr.available(), why=sdr.why(),
        offset_hz=1000.0, passband_hz=passband,
        make_decoder=partial(sdrmode.psk_decoder, variant=variant),
        make_encoder=partial(psk.Encoder().render, variant=variant),
        hosted=True,
    )


_ft8_entry = ModeInfo(
    id="ft8", label="FT8", kind="slot",
    available=ft8.CAN_ENCODE["ft8"], why="" if ft8.CAN_ENCODE["ft8"] else ft8.WHY_UNAVAILABLE,
    offset_hz=1500.0, passband_hz=(200.0, 3000.0),
    make_decoder=partial(ft8.Decoder, variant="ft8"),
    make_encoder=partial(ft8.Encoder().render, variant="ft8"),
)
_ft4_entry = ModeInfo(
    id="ft4", label="FT4", kind="slot",
    # Receive needs only jt9. Sending needs ohsdigi or WSJT-X's ft4code;
    # with neither (WSJT-X for Windows has no ft4code) there is no
    # encoder, which modes_glue reports as decode-only.
    available=ft8.CAN_DECODE, why="" if ft8.CAN_DECODE else ft8.WHY_UNAVAILABLE,
    offset_hz=1500.0, passband_hz=(200.0, 3000.0),
    make_decoder=partial(ft8.Decoder, variant="ft4"),
    make_encoder=partial(ft8.Encoder().render, variant="ft4") if ft8.CAN_ENCODE["ft4"] else None,
)

_js8_entry = ModeInfo(
    # Decoded by ohsdigi (or js8); sent by ohsdigi alone, one frame per over
    # (js8.py's module docstring). Without ohsdigi the encoder is still wired
    # in so send() reaches a clear sentence (js8.WHY_NO_ENCODER).
    id="js8", label="JS8", kind="slot",
    available=js8.CAN_DECODE, why="" if js8.CAN_DECODE else js8.WHY_UNAVAILABLE,
    offset_hz=1500.0, passband_hz=(200.0, 3000.0),
    make_decoder=js8.AllSpeedsDecoder,
    make_encoder=js8.Encoder().render,
)

_q65_entry = ModeInfo(
    # One fixed submode/period for now (Q65-60A: see ohscore/modes/q65.py's
    # docstring for why) rather than a chooser; Brian can ask for one later.
    id="q65", label="Q65-60A", kind="slot",
    available=q65.CAN_ENCODE, why="" if q65.CAN_ENCODE else q65.WHY_UNAVAILABLE,
    offset_hz=1500.0, passband_hz=(200.0, 3000.0),
    make_decoder=q65.Decoder,
    make_encoder=q65.Encoder().render,
)

# FreeDV: probe every mode this module knows how to open, once, and only
# list the ones that actually came up usable -- "whatever modes the
# installed codec2 offers" per DESIGN.md, found out rather than assumed.
_FREEDV_LABELS = {"1600": "FreeDV 1600", "700c": "FreeDV 700C", "700d": "FreeDV 700D",
                  "700e": "FreeDV 700E", "2020": "FreeDV 2020"}
_freedv_entries: dict[str, ModeInfo] = {}
for _name, _label in _FREEDV_LABELS.items():
    _ok, _why = freedv.available(_name)
    _freedv_entries[f"freedv_{_name}"] = ModeInfo(
        id=f"freedv_{_name}", label=_label, kind="voice",
        available=_ok, why=_why,
        offset_hz=1500.0, passband_hz=(300.0, 2700.0),
        make_decoder=partial(freedv.Decoder, mode=_name),
        make_encoder=partial(freedv.FreeDVTx, mode=_name),  # .process(block), not .render() -- see freedv.py
    )

# SSTV: shack_sdr's Rust `sstv` decoder for receive, in fourteen modes
# (modes/sdrmode.py SstvDecoder); sstv.py's encoder for sending, unchanged,
# in its four (sstv.MODES; pass mode= to pick one).
_sstv_entry = ModeInfo(
    id="sstv", label="SSTV", kind="image", available=sdr.available(), why=sdr.why(),
    offset_hz=1900.0, passband_hz=(1100.0, 2300.0),
    make_decoder=sdrmode.sstv_decoder,
    make_encoder=sstv.Encoder().render,
    hosted=True,
)

# HSmodem station to station (DJ0ABR's modem, the multimedia beacon's): files,
# pictures and text, at the speed the engine's hsSpeed says. Its modem is
# ohsdigi's; without ohsdigi the mode is listed with the reason.
_hsmodem_entry = ModeInfo(
    id="hsmodem", label="HSmodem", kind="data",
    available=hsmodem.AVAILABLE, why="" if hsmodem.AVAILABLE else hsmodem.WHY_NOT,
    offset_hz=hsmodem.CENTRE, passband_hz=(100.0, 2950.0),
    make_decoder=hsmodem.Decoder,
    make_encoder=hsmodem.Encoder().render,
)

# KG-STV (JJ0OBZ's digital pictures, 1200 Bd MSK): NB sends it from its
# KG-STV view whatever mode the radio is in (Engine.OVER_MODES) and hears it
# in the background (ohsnb/kgstvrx.py); the decoder here takes a radio's own
# audio, for an app that tunes to it as a mode.
_kgstv_entry = ModeInfo(
    id="kgstv", label="KG-STV", kind="image", available=True, why="",
    offset_hz=kgstv.CENTRE, passband_hz=(1000.0, 2000.0),
    make_decoder=kgstv.Decoder,
    make_encoder=kgstv.Encoder().render,
)

MODES: dict[str, ModeInfo] = {
    "cw": _text_entry("cw", "CW", cw, offset=700.0, passband=(400.0, 1000.0)),
    "rtty": _rtty_entry,
    "psk31": _psk_entry("psk31", "PSK31", (970.0, 1030.0)),
    "psk63": _psk_entry("psk63", "PSK63", (940.0, 1060.0)),
    "psk125": _psk_entry("psk125", "PSK125", (875.0, 1125.0)),
    "ft8": _ft8_entry,
    "ft4": _ft4_entry,
    "q65": _q65_entry,
    "js8": _js8_entry,
    "sstv": _sstv_entry,
    "hsmodem": _hsmodem_entry,
    "kgstv": _kgstv_entry,
    **_freedv_entries,
}
