"""The device interface every SDR implements (DESIGN.md "Devices")."""
from __future__ import annotations

import numpy as np


class DeviceError(RuntimeError):
    """A device problem with a sentence the operator can act on."""


class Device:
    kind = "none"
    can_tx = False
    fs = 0.0
    # True for a radio whose own receive buffering is short (a Pluto's four
    # 75 ms kernel buffers): the engine then reads it on a thread of its
    # own into a two-second queue, so a receive thread the window has
    # starved of the GIL falls behind and catches up rather than losing
    # samples at the radio (ohscore/rxprefetch.py says why and how).
    rx_prefetch = False
    # Whether what this device transmits leaves the computer. Only a
    # simulator says False: an app may then let it key without the licence
    # acknowledgement (QO-100 NB does). Anything that does not say -
    # every real radio, and any device written later - radiates.
    radiates = True

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def set_rx_if(self, hz: float) -> None:
        """Receiver centre (DC of the IQ stream), at IF: dl - lnbLo - rxCorr."""
        raise NotImplementedError

    def read(self, n: int) -> np.ndarray:
        """complex64, blocks until n samples are available."""
        raise NotImplementedError

    def set_rx_gain(self, mode: str, db: float) -> None:
        """The receiver's front-end gain, applied to the open device: `mode`
        is "manual", "slow_attack" or "fast_attack" (the AD936x's own
        names), `db` the gain used when manual. open() applies the
        configured values; the engine calls this when they change while
        running, so a gain change never needs a restart. A device with no
        such control (the Hermes-Lite 2 has its own LNA setting) ignores it.
        Raises DeviceError if the device refused."""

    def rx_gain_now(self) -> float | None:
        """The front-end gain in use now, dB - under the device's own AGC,
        what the AGC has chosen - or None if the device cannot say. Called
        on the receive thread, between two reads. NB's dish alignment fixes
        the gain here while it is open: an AGC would take back exactly the
        change in signal that peaking a dish is looking for."""
        return None

    def set_tx_freq(self, hz: float) -> None:
        raise DeviceError("This device cannot transmit")

    def set_tx_gain(self, db: float) -> None:
        raise DeviceError("This device cannot transmit")

    def tx_start(self) -> None:
        raise DeviceError("This device cannot transmit")

    def tx_stop(self) -> None:
        """Stop transmitting now. Whatever is still queued is discarded:
        this is the emergency path (Escape, the watchdog, a guard or a
        protection trip) as well as the last step of a normal end, which
        first lets the queue go out (tx_finish, tx_queued)."""

    def tx_finish(self) -> None:
        """Nothing more will be written this over. Send on anything held
        back waiting for a whole block, and stop counting the queue running
        dry as an underrun; tx_queued() then falls to zero as the rest goes
        out. The engine calls it once, on a normal end, before it waits."""

    def tx_queued(self) -> float:
        """Seconds of transmit samples already written that tx_stop() would
        still discard - the queue between write() and the antenna, as the
        device measures it, down to the last sample written (not padding
        the device adds after it). 0.0 for a device that holds nothing."""
        return 0.0

    def write(self, iq: np.ndarray) -> None:
        raise DeviceError("This device cannot transmit")

    def tx_latency(self) -> float:
        """Seconds between write() returning and those samples leaving the
        antenna, as well as the device can tell. TxMonitor uses it to line
        our transmit history up with what comes back."""
        return 0.0

    def status(self) -> dict:
        return {"kind": self.kind}

    # -- what OpenHamShack Radio asks of a device (docs/ham/DESIGN-HAM.md 4.1) -------
    # Defaults keep NB's devices unchanged: NB never calls these.

    # Frequencies the device can tune, Hz: receive and transmit.
    rx_range: tuple[float, float] = (0.0, 6e9)
    tx_range: tuple[float, float] = (0.0, 6e9)

    def tx_full_w(self, hz: float) -> float:
        """Output at full drive at `hz`, watts, as the device's own figure
        (an estimate unless the operator measures it)."""
        return 0.0

    def set_drive(self, x: float) -> None:
        """Transmit drive, 0..1 of full output amplitude. Default: as a gain
        in dB on devices whose level is an attenuator (the Pluto)."""
        import math
        self.set_tx_gain(-89.75 if x <= 0 else max(-89.75, min(0.0, 20 * math.log10(x))))

    def telemetry(self) -> dict:
        """Measured transmit telemetry: fwd/rev (W), temp (deg C), current
        (A), supply (V) - whichever the device has; {} if none."""
        return {}

    def set_outputs(self, bits: int) -> None:
        """Open-collector / GPO lines (a sequencer driver); most devices have none."""
