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

**Antenna input: the setting is `soapyAntenna`/`soapyAntennaLabels` on
every SDR source, not only the SoapySDR path.** Those names stayed from
when soapy.py was the only device with more than one input (RADIO-SDR-PLAN
§6); renaming them now would break the Remote tablet picker being built
against them (see HANDOVER.md), so they are kept and documented as
applying to every source instead - the engine, Settings and the API treat
`sdrplay`/`rtlsdr` the same as `soapy` (see `SourceDevice.open`,
`set_antenna`, `status`). shack_sdr's own antenna names are
SoapySDRPlay3's ("Antenna A/B/C", "Hi-Z", "Tuner 1/2 ...") for an RSP, and
"RX" for an RTL-SDR, so a label saved against one path reads the same
against the other (ohs-libs shack_sdr README "Antenna/input selection").

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
(sdrplayLna; ohs-box's RSPdx on an 80 m dipole wants 4). An RSP reached as
`device soapy` keeps SoapySDRPlay3's quite different sense instead
(SoapySdrplayDevice). Bias-T is never touched: it powers whatever is on the socket.

The engine reads a device on a thread of its own (rx_prefetch): the
sources block until a block is in, which is what that thread is for.
"""
from __future__ import annotations

import numpy as np

from .. import host, hostlibs, sdr
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
        "bad-antenna": _("The {radio} has no such antenna input."),
    }
    text = words.get(reason, _("The {radio} failed ({reason}).")).format(radio=name, reason=reason)
    return f"{text} ({detail})" if detail else text


def sdrplay_missing_sentence() -> str:
    if hostlibs.controller_too_old():
        # The controller mounts no host libraries at all (ohscore/hostlibs.py):
        # nothing its administrator could install would reach this app.
        return hostlibs.update_sentence()
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
    # Which shack_sdr source opens it, for the sentences (_sentence): the
    # same as `kind` except where another device setting reaches the same
    # receiver (SoapySdrplayDevice, kind "soapy").
    source = ""

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
            self._apply_saved_antenna()
        except SdrError as e:
            src, self.src = self.src, None
            if src is not None:
                try:
                    src.close()
                except Exception:  # noqa: BLE001 - tidying up a device that never finished opening
                    pass
            raise DeviceError(_sentence(self.source, e.reason, e.detail)) from e

    def _saved_antenna(self) -> str:
        return str(self.cfg.get("soapyAntenna", "") or "").strip()

    def _apply_saved_antenna(self) -> None:
        """Applied here, at open, so an unknown name fails the open the
        same way an unknown SoapySDR antenna does (soapy.py's open) rather
        than leaving the receiver listening on the wrong input with
        nothing said. `SdrplaySource` already took this in its own
        constructor (RADIO-SDR-PLAN §6, `_make` below), where it is
        validated against the model `open()` found, so by the time we get
        here `self.src.antenna` already matches and this is a no-op;
        `RtlSdrSource` has no such constructor argument (one input, "RX"),
        so for that source this is the only place the saved name is ever
        applied - through the same `set_antenna` (below) the engine calls
        live, which is why a name the receiver does not have fails here
        exactly as it would during a live switch."""
        name = self._saved_antenna()
        if name and name != self.src.antenna:
            self.src.set_antenna(name)

    def set_antenna(self, name: str) -> None:
        """Live switch while running, called by the engine exactly as
        SoapyDevice.set_antenna is (ohscore/engine.py `_configure_rx`): ""
        is the driver's default, already applied at open, so there is
        nothing to change; a name the receiver does not have raises, and
        the engine only toasts that - never retries or falls back - so a
        label saved for a radio later swapped for a different one cannot
        silently try its old antenna's name."""
        if self.src is None:
            return
        name = str(name or "").strip()
        if not name:
            return
        try:
            self.src.set_antenna(name)
        except self._error as e:
            raise DeviceError(_sentence(self.source, e.reason, e.detail)) from e

    def set_rx_if(self, hz: float) -> None:
        self.rx_if = float(hz)
        if self.src is None:
            return
        try:
            self.src.set_centre(hz)
        except self._error as e:
            raise DeviceError(_sentence(self.source, e.reason, e.detail)) from e

    def set_rx_gain(self, mode: str, db: float) -> None:
        if self.src is None:
            return
        try:
            self.src.set_gain(self._gain(mode, db))
        except self._error as e:
            raise DeviceError(_sentence(self.source, e.reason, e.detail)) from e

    def read(self, n: int) -> np.ndarray:
        while len(self.left) < n:
            try:
                block = self.src.read()
            except self._error as e:
                raise DeviceError(_sentence(self.source, e.reason, e.detail)) from e
            if block is None:
                raise DeviceError(_sentence(self.source, "read-failed", ""))
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
    kind = source = "rtlsdr"
    RATES = (1_200_000.0, 2_400_000.0)

    def _make(self):
        from shack_sdr.sources import RtlSdrSource
        serial = str(self.cfg.get("sdrSerial") or "").strip() or None
        gain = self._gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        return RtlSdrSource(self.rx_if or 145_000_000.0, self.fs, gain, serial=serial, search=_search())


class SdrplayDevice(SourceDevice):
    kind = source = "sdrplay"
    RATES = (2_400_000.0,)
    GR_RANGE = (20.0, 59.0)

    def _gain(self, mode: str, db: float):
        if mode != "manual":
            return None
        return min(max(79.0 - float(db), self.GR_RANGE[0]), self.GR_RANGE[1])

    def gain_sense(self) -> dict:
        # rxGain is a gain here (reduction 79 - rxGain), but only inside
        # SDRplay's 20-59 dB: the S-meter takes the clamp into account.
        return {"gainIsReduction": False, "gainModel": "sdrplay"}

    def _make(self):
        from shack_sdr.sources import SdrplaySource
        serial = str(self.cfg.get("sdrSerial") or "").strip() or None
        gain = self._gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        return SdrplaySource(self.rx_if or 145_000_000.0, self.fs, gain, serial=serial,
                             lna_state=int(self.cfg.get("sdrplayLna", 4)),
                             antenna=self._saved_antenna() or None)


def soapy_has_driver(driver: str) -> bool:
    """Whether SoapySDR here has a module for `driver` (looked for by its
    file name, never loaded: loading SoapySDRPlay3 starts talking to
    SDRplay's service)."""
    try:
        import SoapySDR
        modules = [str(p) for p in SoapySDR.listModules()]
    except Exception:  # noqa: BLE001 - no SoapySDR, or one too old to list: no module
        return False
    want = {"sdrplay": "sdrplaysupport"}.get(driver, driver.lower())
    return any(want in m.rsplit("/", 1)[-1].lower() for m in modules)


def soapy_args(args: str) -> dict[str, str]:
    """soapyArgs ("driver=sdrplay,serial=X,rfgain_sel=4") as a dict."""
    out = {}
    for part in str(args or "").split(","):
        k, eq, v = part.strip().partition("=")
        if eq and k:
            out[k.strip()] = v.strip()
    return out


class SoapySdrplayDevice(SdrplayDevice):
    """`device` soapy with `driver=sdrplay`, where SoapySDR has no SDRplay
    module: the same RSP through shack_sdr's own binding to SDRplay's API.

    Why: SoapySDRPlay3 is built against SDRplay's headers, which come only
    inside SDRplay's installer, and Radio's store image no longer carries
    that installer, its API or anything built from it (RADIO-SDR-PLAN 6.3,
    Brian 22/10/2026). The API itself now comes from the controller's host
    library, which stages the library and the service but no headers, and
    the image has no compiler to build against them if it did. So the
    soapy path cannot keep SoapySDRPlay3; instead a station configured as
    ohs-box is (device soapy, soapyArgs driver=sdrplay,rfgain_sel=4,
    soapyAntenna "Antenna C") opens the RSP here with nothing changed in its
    settings: `serial` picks the RSP as sdrSerial does, `rfgain_sel` is the
    LNA state (SoapySDRPlay3's name for the same field sdrplayLna sets),
    and the antenna names are SoapySDRPlay3's own (shack_sdr README). Its
    kind stays "soapy", so the broker's claim, the settings and every
    sentence naming the radio are the ones the station already has; its
    status says which path opened it (`via`).

    Where SoapySDR does have the module (a desktop with SoapySDRPlay3
    installed, an image built with SHACK_STORE_DROP_SDRPLAY=0) SoapyDevice
    opens it as before (ohscore/devices/registry.py).

    **Gain means what it meant under SoapySDRPlay3, not what it means for
    `device sdrplay`.** Store Radio 0.1.22-beta.3 first opened ohs-box's
    RSPdx this way with SdrplayDevice's mapping (gain reduction 79 less
    rxGain, LNA state from rfgain_sel): at the same settings (manual 40,
    rfgain_sel=4, 2 m) that is gRdB 39 at LNA state 4, where SoapySDRPlay3
    had set gRdB 59 at LNA state 1, and the noise floor rose 13 dB (-74.4
    to -61.2 dBFS) with deviceStatus reporting 39. A station that moved
    paths without touching a setting must hear the same thing and keep its
    S-meter calibration, so this class asks `SdrplaySource` for
    SoapySDRPlay3's own gain semantics (`gain_model="soapysdrplay3"`,
    ohs-libs shack_sdr README "SDRplay's gain models and switches") rather
    than computing the split itself:

    - manual: AGC off, then the overall gain split the way SoapySDR's base
      Device::setGain splits it for a driver that does not override it,
      over SoapySDRPlay3's elements IFGR (gRdB, 20-59) then RFGR (LNA
      state, 0..the model's top). Both elements are *reductions*, so a
      higher rxGain here is less gain - SoapySDRPlay3's quirk, kept on
      purpose: changing it would move every station on this path;
    - automatic (either AGC speed): AGC_CTRL_EN at a -30 dBFS set point
      (or soapyArgs' agc_setpoint), with gRdB and the LNA state left where
      they were - rfgain_sel at open, the last manual split after one;
    - the gain reported (status `gain`, rx_gain_now) is SoapySDR's overall
      getGain: (gRdB - 20) + LNA state, read from the API's structure
      (`SdrplaySource.gain_now`).

    This also picks up the source's parity with SoapySDRPlay3's DC-offset
    tracking and overload acknowledgement (ohs-libs shack_sdr README
    "SDRplay: parity with SoapySDRPlay3"), and its `overloads`, `apiGaps`
    and `apiLost` counters, with nothing further to do here: `status()`
    passes the source's own status straight through (SourceDevice.status).

    Without rfgain_sel the LNA state opens at 0, as SoapySDRPlay3 opened it
    (`sdrplayLna` was never read on this path, and is not now). The other
    soapyArgs SoapySDRPlay3 took (iqcorr_ctrl, biasT_ctrl, the notches,
    extref_ctrl) are not carried over: no station is known to set them."""

    kind = "soapy"

    def __init__(self, cfg: dict, fs: float):
        cfg = dict(cfg or {})
        a = soapy_args(cfg.get("soapyArgs", ""))
        if a.get("serial"):
            cfg["sdrSerial"] = a["serial"]
        try:
            cfg["sdrplayLna"] = int(a["rfgain_sel"])
        except (KeyError, ValueError):
            cfg["sdrplayLna"] = 0
        try:
            self.agc_setpoint = int(a["agc_setpoint"])
        except (KeyError, ValueError):
            self.agc_setpoint = SOAPY_AGC_SETPOINT
        super().__init__(cfg, fs)

    def _gain(self, mode: str, db: float):
        # SoapySDR's overall gain: SdrplaySource's own gain_model="soapysdrplay3"
        # splits it, once the model - and so RFGR's range - is known.
        return None if mode != "manual" else float(db)

    def _make(self):
        from shack_sdr.sources import SdrplaySource
        serial = str(self.cfg.get("sdrSerial") or "").strip() or None
        gain = self._gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        return SdrplaySource(self.rx_if or 145_000_000.0, self.fs, gain, serial=serial,
                             lna_state=int(self.cfg.get("sdrplayLna", 0)),
                             antenna=self._saved_antenna() or None,
                             gain_model="soapysdrplay3", agc_setpoint=self.agc_setpoint)

    def gain_sense(self) -> dict:
        # The source already knows SoapySDRPlay3's sense for the model it
        # opened (SdrplaySource.gain_sense); before open there is no model
        # yet, so fall back to an RSPdx's range as the source itself does.
        if self.src is not None:
            return self.src.gain_sense()
        return {"gainIsReduction": True, "gainModel": "soapysdrplay3", "rfgrRange": list(soapy_rfgr_range(4))}

    def rx_gain_now(self) -> float | None:
        src = self.src
        if src is None:
            return None
        try:
            return src.gain_now()
        except Exception:  # noqa: BLE001 - "cannot say", as SoapyDevice.rx_gain_now
            return None

    def status(self) -> dict:
        st = super().status()
        st.update(via="sdrplay-api", args=str(self.cfg.get("soapyArgs", "")))
        return st


# SoapySDRPlay3 0.5.2 (MIT, github.com/pothosware/SoapySDRPlay3, the build
# store Radio carried until 0.1.22-beta.2), Settings.cpp: listGains is
# ["IFGR", "RFGR"]; getGainRange("IFGR") is 20..59 and "RFGR" 0..3 (RSP1),
# 0..8 (RSP2), 0..9 (RSPduo, RSP1A, RSP1B), 0..27 (RSPdx, RSPdx R2), and
# 20..59 for a model it does not name; setGainMode(true) is AGC_CTRL_EN;
# the constructor sets the AGC set point to -30 dBfs.
SOAPY_IFGR = (20, 59)
SOAPY_RFGR_TOP = {1: 3, 2: 8, 3: 9, 255: 9, 6: 9, 4: 27, 7: 27}
SOAPY_AGC_SETPOINT = -30


def soapy_gain_split(gain: float, hw_ver: int) -> tuple[int, int]:
    """(gRdB, LNA state) for SoapySDR's overall setGain(RX, gain) on an RSP
    of hardware id `hw_ver` under SoapySDRPlay3.

    SoapySDRPlay3 overrides only the per-element setGain, so the overall
    call is SoapySDR 0.8.1's base Device::setGain (lib/Device.cpp): for
    receive, each element in listGains order takes g = min(left, max - min),
    is set to g + min, and `left` drops by what the element then reports
    less its min. SoapySDRPlay3's per-element setGain stores `(int)value`
    (truncated toward zero, as Python's int() does), so a fraction carries
    on to RFGR and is truncated there too."""
    return soapy_gain_split_rf(gain, soapy_rfgr_range(hw_ver))


def soapy_rfgr_range(hw_ver: int) -> tuple[int, int]:
    """SoapySDRPlay3's getGainRange("RFGR") for hardware id `hw_ver`."""
    return (0, SOAPY_RFGR_TOP[hw_ver]) if hw_ver in SOAPY_RFGR_TOP else SOAPY_IFGR


def soapy_gain_split_rf(gain: float, rf: tuple[int, int]) -> tuple[int, int]:
    """soapy_gain_split with RFGR's range given rather than the model's:
    what the S-meter uses (ohscore/smeter_cal.py), from the range a device
    reports in its status (`rfgrRange`)."""
    left, got = float(gain), []
    for lo, hi in (SOAPY_IFGR, (int(rf[0]), int(rf[1]))):
        g = min(left, hi - lo)
        v = int(g + lo)
        got.append(v)
        left -= v - lo
    return got[0], got[1]


def soapy_gain_of(grdb: int, lna: int, hw_ver: int) -> float:
    """SoapySDR's overall getGain under SoapySDRPlay3: each element's value
    less its range's minimum, summed (lib/Device.cpp getGain)."""
    rf_lo = 0 if hw_ver in SOAPY_RFGR_TOP else SOAPY_IFGR[0]
    return float((grdb - SOAPY_IFGR[0]) + (lna - rf_lo))
