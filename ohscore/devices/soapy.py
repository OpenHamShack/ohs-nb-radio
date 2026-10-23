"""Receive-only SDRs through SoapySDR (RTL-SDR, Airspy, HackRF, SDRplay with
its vendor module...). can_tx is False: the engine refuses to key with one of
these, which is safety rule 2.

First run on hardware: an SDRplay RSPdx on Radio's store form (12/10/2026,
SoapySDRPlay3 0.5.2, API 3.15). It refuses 1.2 MS/s (its driver offers 2
MS/s and its decimations, or any rate above 2 MS/s), so Radio runs it at
2.4 MS/s. An RTL-SDR runs at 1.2 MS/s fine; an Airspy's native rates are
higher (2.5/3/6/10 MS/s), so if the driver refuses 1.2 MS/s choose another
rate or add a rational resampler here.

`soapyAntenna` picks the input on a receiver with more than one (an RSPdx
has Antenna A, B and C; C is the HF-only socket). It is checked against the
driver's own list before it is set: SoapySDRPlay3 ignores a name it does
not know and stays on Antenna A, so a typo would otherwise listen to the
wrong antenna with nothing said.

Switching it does not reopen the device: SoapySDRPlay3 (the RSPdx) takes
`setAntenna` on a running stream, and the SoapySDR API has no notion of a
"stream must be idle first" the way a sample rate change does, so
`set_antenna` below is called straight through. A driver that genuinely
cannot change it live would raise from `setAntenna` itself, which the
engine shows as "antenna not changed" rather than acting on - there is
none such known today, so this has not been exercised against a refusal.
"""
from __future__ import annotations

import numpy as np

from .. import host
from .base import Device, DeviceError


class SoapyDevice(Device):
    rx_prefetch = True           # read on its own thread (Device.rx_prefetch)
    kind = "soapy"
    can_tx = False

    def __init__(self, args: str = "", fs: float = 1_200_000.0, cfg: dict | None = None):
        self.args = args
        self.fs = float(fs)
        self.cfg = cfg or {}
        self.sdr = None
        self.stream = None
        self.left = np.zeros(0, np.complex64)
        self.rx_if = None
        self.antenna = ""
        self.antennas: list[str] = []
        self.block = int(self.fs * 0.075)
        self.overflows = 0

    def open(self) -> None:
        try:
            import SoapySDR
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX
        except ImportError as e:
            raise DeviceError(host.hint("soapysdr")) from e
        self.S = SoapySDR
        self.RX = SOAPY_SDR_RX
        try:
            self.sdr = SoapySDR.Device(self.args)
        except RuntimeError as e:
            raise DeviceError(f"No SoapySDR device for {self.args!r} ({e}); SoapySDRUtil --find lists them") from e
        try:
            self._set_antenna(str(self.cfg.get("soapyAntenna", "") or "").strip())
        except DeviceError:
            self.sdr = None             # nothing streams yet; dropping it closes the device
            raise
        self.sdr.setSampleRate(SOAPY_SDR_RX, 0, self.fs)
        got = self.sdr.getSampleRate(SOAPY_SDR_RX, 0)
        if abs(got - self.fs) > 1:
            raise DeviceError(f"The SDR runs at {got:.0f} S/s, not {self.fs:.0f}; choose another sample rate")
        try:
            self.set_rx_gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        except DeviceError:
            pass                    # a driver with no gain control still receives
        self.stream = self.sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self.sdr.activateStream(self.stream)
        self.buf = np.zeros(self.block, np.complex64)

    def _set_antenna(self, want: str) -> None:
        try:
            self.antennas = [str(a) for a in self.sdr.listAntennas(self.RX, 0)]
        except (RuntimeError, AttributeError):
            self.antennas = []
        if want:
            if want not in self.antennas:
                have = ", ".join(self.antennas) or "none it will name"
                raise DeviceError(f"This SDR has no antenna input called {want!r} (it has: {have})")
            try:
                self.sdr.setAntenna(self.RX, 0, want)
            except RuntimeError as e:
                raise DeviceError(f"The SDR refused antenna {want!r} ({e})") from e
        try:
            self.antenna = str(self.sdr.getAntenna(self.RX, 0))
        except (RuntimeError, AttributeError):
            self.antenna = want

    def set_antenna(self, name: str) -> None:
        if self.sdr is None:
            return
        self._set_antenna(str(name or "").strip())

    def set_rx_gain(self, mode: str, db: float) -> None:
        """SoapySDR has one automatic gain switch, not the AD936x's two
        speeds, so both AGC choices mean "automatic". Called on an active
        stream, as any SoapySDR program's gain slider does."""
        try:
            self.sdr.setGainMode(self.RX, 0, mode != "manual")
            if mode == "manual":
                self.sdr.setGain(self.RX, 0, float(db))
        except RuntimeError as e:
            raise DeviceError(f"The SDR refused the gain setting ({e})") from e

    def gain_sense(self) -> dict:
        """SoapySDRPlay3 makes SoapySDR's overall gain a sum of two
        reductions (sdrsource.SoapySdrplayDevice says how); every other
        driver here is a plain gain."""
        try:
            if self.sdr is not None and str(self.sdr.getDriverKey()).lower() == "sdrplay":
                r = self.sdr.getGainRange(self.RX, 0, "RFGR")
                return {"gainIsReduction": True, "gainModel": "soapysdrplay3",
                        "rfgrRange": [int(r.minimum()), int(r.maximum())]}
        except (RuntimeError, AttributeError):
            pass
        return super().gain_sense()

    def rx_gain_now(self) -> float | None:
        # Most drivers report the gain they are at, AGC or not; untried on
        # hardware here, so anything odd is "cannot say".
        try:
            return float(self.sdr.getGain(self.RX, 0))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            return None

    def set_rx_if(self, hz: float) -> None:
        self.rx_if = float(hz)
        self.sdr.setFrequency(self.RX, 0, float(hz))

    def read(self, n: int) -> np.ndarray:
        while len(self.left) < n:
            r = self.sdr.readStream(self.stream, [self.buf], len(self.buf), timeoutUs=1_000_000)
            if r.ret == self.S.SOAPY_SDR_OVERFLOW:
                self.overflows += 1
                continue
            if r.ret < 0:
                raise DeviceError(f"SoapySDR read failed ({self.S.errToStr(r.ret)})")
            self.left = np.concatenate([self.left, self.buf[:r.ret].copy()])
        out, self.left = self.left[:n], self.left[n:]
        return out

    def close(self) -> None:
        if self.sdr is not None and self.stream is not None:
            try:
                self.sdr.deactivateStream(self.stream)
                self.sdr.closeStream(self.stream)
            except RuntimeError:
                pass
        self.sdr = self.stream = None

    def status(self) -> dict:
        st = {"kind": "soapy", "args": self.args, "fs": self.fs, "rxLo": self.rx_if, "overflows": self.overflows,
              "tx": "receive only", "antenna": self.antenna, "antennas": list(self.antennas)}
        if self.sdr is not None:
            try:
                st["driver"] = self.sdr.getDriverKey()
                st["hardware"] = self.sdr.getHardwareKey()
            except (RuntimeError, AttributeError):
                pass
        return st
