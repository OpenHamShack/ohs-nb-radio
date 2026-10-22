"""Receive-only SDRs through shack_sdr's own sources (RADIO-SDR-PLAN §6): an
RTL-SDR through librtlsdr, an SDRplay RSP through the SDRplay API the
operator installed, each over ctypes.

Why not SoapySDR, which already reaches both on Linux: its Python bindings
are SWIG modules that would have to be built for each frozen Python, so
the Windows and macOS builds have never carried it and could receive only
from a Pluto or an HL2. shack_sdr's bindings need nothing compiled per
Python and were already proven in Packet Radio (they moved from
shack_packet.sdr into shack_sdr for this), so every desktop OS gets both
radios. SoapySDR stays as the generic route on Linux (`soapy`).

**Receive only, by construction.** can_tx is False and the sources have no
transmit method: the engine refuses an over before anything else is asked
("This radio can only receive"), as it does for SoapySDR receivers.

**SDRplay's API is never ours** (Brian, 22/10/2026: use if installed, on
every form). Without it, opening the RSP says "Install SDRplay's API to use
this radio" - on a controller, ask the administrator, whose controller
stages it as a host library (§6.3).

**Rates and gain** (§6.2). Each source offers its own rates: the RTL 1.2
and 2.4 MS/s, the RSP 2.4 (SoapySDRPlay3 refused 1.2, and the RSPdx has
only ever run at 2.4), so an RSP asked for 1.2 opens at 2.4 and says so in
its status. Radio's one gain control maps onto each: automatic is the
tuner's AGC (RTL) or the API's 50 Hz AGC (RSP); manual is the nearest tuner
step (RTL) or, for the RSP, a gain *reduction* of 79 dB less the gain asked
for, held to SDRplay's 20-59 dB, with the LNA state its own setting
(sdrplayLna; ohs-box's RSPdx on an 80 m dipole wants 4). Bias-T is never
touched: it powers whatever is on the socket.

The engine reads a device on a thread of its own (rx_prefetch): the
sources block until a block is in, which is what that thread is for.
"""
from __future__ import annotations

import numpy as np

from .. import host, sdr
from ..i18n.text import _
from .base import Device, DeviceError

RECEIVE_ONLY = "This radio can only receive"


def _sentence(kind: str, reason: str, detail: str) -> str:
    """The operator's sentence for a source's SdrError reason (shack_sdr
    sources REASONS: keys, never words)."""
    name = {"rtlsdr": "RTL-SDR", "sdrplay": "SDRplay RSP"}.get(kind, kind)
    if reason == "no-library":
        if kind == "sdrplay":
            return sdrplay_missing_sentence()
        return _("The RTL-SDR library (librtlsdr) is not installed: on Debian or Ubuntu, install librtlsdr0.")
    words = {
        "no-device": _("No {radio} was found. Is it plugged in?"),
        "busy": _("The {radio} is in use by another program, or (Windows) still has Windows' own driver: "
                  "fit the WinUSB driver once with Zadig."),
        "open-failed": _("The {radio} could not be opened."),
        "setup-failed": _("The {radio} would not take a setting."),
        "rate-unsupported": _("The {radio} cannot run at that sample rate."),
        "out-of-range": _("The {radio} cannot tune that frequency."),
        "read-failed": _("The {radio} stopped sending samples."),
        "disconnected": _("The {radio} was unplugged."),
    }
    text = words.get(reason, _("The {radio} failed ({reason}).")).format(radio=name, reason=reason)
    return f"{text} ({detail})" if detail else text


def sdrplay_missing_sentence() -> str:
    if host.STORE:
        return _("Ask your controller's administrator to install SDRplay's API (Controller › Optional "
                 "libraries) to use this radio.")
    return _("Install SDRplay's API to use this radio: SDRplay's own installer, from sdrplay.com. Radio never "
             "includes it.")


def availability(kind: str) -> tuple[bool, str]:
    """(usable here, the sentence when not) for the Settings page, without
    opening any device."""
    m = sdr.load()
    if m is None:
        return False, sdr.why()
    from shack_sdr.sources import rtlsdr, sdrplay
    a = sdrplay.availability() if kind == "sdrplay" else rtlsdr.availability(search=_search())
    if a["available"]:
        return True, ""
    return False, _sentence(kind, a["why"] if a["why"] != "sdrplay_api_missing" else "no-library", "")


def _search() -> list[str]:
    """Where a frozen build carries librtlsdr: _internal/rtlsdr on Windows
    (build-windows.ps1), beside the app's own libraries on macOS."""
    out = []
    for d in host._bundle_dirs():
        out += [str(d / "rtlsdr"), str(d)]
    return out


class SourceDevice(Device):
    rx_prefetch = True
    can_tx = False
    tx_refusal = RECEIVE_ONLY
    RATES: tuple[float, ...] = ()

    def __init__(self, cfg: dict, fs: float):
        self.cfg = dict(cfg or {})
        want = float(fs)
        self.note = ""
        if self.RATES and want not in self.RATES:
            # The nearest rate this receiver offers (RADIO-SDR-PLAN §6.2).
            got = min(self.RATES, key=lambda r: abs(r - want))
            self.note = f"runs at {got / 1e6:g} MS/s (it cannot run at {want / 1e6:g})"
            want = got
        self.fs = want
        self.src = None
        self.left = np.zeros(0, np.complex64)
        self.rx_if = None
        self.lost = 0

    def _make(self):
        raise NotImplementedError

    def _gain(self, mode: str, db: float):
        """The source's gain for Radio's gain control: None for its AGC."""
        return None if mode != "manual" else float(db)

    def open(self) -> None:
        m = sdr.load()
        if m is None:
            raise DeviceError(sdr.why())
        from shack_sdr.sources import SdrError
        self._error = SdrError
        self.src = self._make()
        try:
            self.src.open()
        except SdrError as e:
            self.src = None
            raise DeviceError(_sentence(self.kind, e.reason, e.detail)) from e

    def set_rx_if(self, hz: float) -> None:
        self.rx_if = float(hz)
        if self.src is None:
            return
        try:
            self.src.set_centre(hz)
        except self._error as e:
            raise DeviceError(_sentence(self.kind, e.reason, e.detail)) from e

    def set_rx_gain(self, mode: str, db: float) -> None:
        if self.src is None:
            return
        try:
            self.src.set_gain(self._gain(mode, db))
        except self._error as e:
            raise DeviceError(_sentence(self.kind, e.reason, e.detail)) from e

    def read(self, n: int) -> np.ndarray:
        while len(self.left) < n:
            try:
                block = self.src.read()
            except self._error as e:
                raise DeviceError(_sentence(self.kind, e.reason, e.detail)) from e
            if block is None:
                raise DeviceError(_sentence(self.kind, "read-failed", ""))
            self.lost += block.dropped
            self.left = np.concatenate([self.left, block.samples])
        out, self.left = self.left[:n], self.left[n:]
        return out

    def close(self) -> None:
        src, self.src = self.src, None
        if src is not None:
            try:
                src.close()
            except Exception:  # noqa: BLE001 - a radio already gone is closed
                pass

    def status(self) -> dict:
        st = {"kind": self.kind, "fs": self.fs, "rxLo": self.rx_if, "tx": "receive only", "lost": self.lost}
        if self.note:
            st["notes"] = [self.note]
        if self.src is not None:
            try:
                st.update({k: v for k, v in self.src.status().items() if k not in ("kind", "rate", "centre")})
            except Exception:  # noqa: BLE001 - status is best effort
                pass
        return st


class RtlSdrDevice(SourceDevice):
    kind = "rtlsdr"
    RATES = (1_200_000.0, 2_400_000.0)

    def _make(self):
        from shack_sdr.sources import RtlSdrSource
        serial = str(self.cfg.get("sdrSerial") or "").strip() or None
        gain = self._gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        return RtlSdrSource(self.rx_if or 145_000_000.0, self.fs, gain, serial=serial, search=_search())


class SdrplayDevice(SourceDevice):
    kind = "sdrplay"
    RATES = (2_400_000.0,)
    GR_RANGE = (20.0, 59.0)

    def _gain(self, mode: str, db: float):
        if mode != "manual":
            return None
        return min(max(79.0 - float(db), self.GR_RANGE[0]), self.GR_RANGE[1])

    def _make(self):
        from shack_sdr.sources import SdrplaySource
        serial = str(self.cfg.get("sdrSerial") or "").strip() or None
        gain = self._gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        return SdrplaySource(self.rx_if or 145_000_000.0, self.fs, gain, serial=serial,
                             lna_state=int(self.cfg.get("sdrplayLna", 4)))
