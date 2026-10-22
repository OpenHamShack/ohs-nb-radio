"""PTT sequencing (docs/ham/DESIGN-HAM.md section 6.1): the lines that key
a PA, a mast-head preamp's bypass relay or a transverter switch, in the
right order around the RF.

    key-up:   line on -> wait seqDelayMs -> device TX start at zero drive -> drive up -> RF
    key-down: device's queue sent -> drive -> 0 -> device TX stop -> wait seqDelayMs -> line off

RF never starts before the line has been on for the delay, and the line
never drops while RF can still be coming out. The engine calls `key_up`
before it starts the device and `key_down` after it has stopped it, on
the transmit thread, so the waits are monotonic-clock sleeps there and the
UI never blocks. On a normal end the engine has let the device's queue go
out first (Engine._tx_drain), so `key_down`'s delay is counted from the
true end of RF, not from the last block written; an emergency unkey drops
the queue and comes straight here.

Outputs ("drivers"), each defined so that **process death leaves it
unkeyed**:

- `none`: nothing to switch (the device's own T/R is enough: a Pluto
  barefoot into a dummy load, the simulator).
- `serial`: a USB-serial adapter's RTS and/or DTR, through the kernel's
  modem-control ioctls (no pyserial). When the process dies the kernel
  closes the port, and with HUPCL (the default) both lines drop. **Opening
  a serial port on Linux asserts DTR and RTS** before any program can
  stop it; the port is therefore opened once, at start, and both lines
  cleared at once - a glitch of well under a millisecond on the lines,
  with no RF, which a PA's relay does not follow. A line that must never
  glitch needs a pull-down and an inverter, which the Settings page says.

The HL2's open-collector outputs, Pi GPIO and the Pluto's GPO are the
design's other drivers; they come with the hardware that has them.

States published as `seqState`: rx, seq (line on, waiting), tx, hang
(RF off, waiting to drop the line).
"""
from __future__ import annotations

import logging
import os
import struct
import time

log = logging.getLogger("ohsradio.sequencer")

# Set / clear modem-control bits. The numbers differ between kernels -
# Linux's are 0x5416/0x5417, a Mac's (BSD's _IOW encoding) 0x8004746c/
# 0x8004746b - so they come from the termios module, which has the running
# system's. Hard-coded Linux values, as this was until macOS arrived on
# 07/10/2026, make the Mac's ioctl fail with ENOTTY at the first key-up,
# after the port has opened with both lines asserted. The fallback is for
# Windows, which has no termios and no serial PTT here (fcntl is missing
# there too, and SerialOutput says so when it is chosen).
try:
    import termios as _termios
    TIOCMBIS, TIOCMBIC = _termios.TIOCMBIS, _termios.TIOCMBIC
    TIOCM_DTR, TIOCM_RTS = _termios.TIOCM_DTR, _termios.TIOCM_RTS
except (ImportError, AttributeError):
    TIOCMBIS, TIOCMBIC = 0x5416, 0x5417
    TIOCM_DTR, TIOCM_RTS = 0x002, 0x004


class SequencerError(RuntimeError):
    """A PTT output could not be set up; the sentence says which and why."""


class NoOutput:
    name = "none"

    def set(self, on: bool) -> None:
        pass

    def close(self) -> None:
        pass


class SerialOutput:
    """RTS and/or DTR of a serial port as the PTT line."""

    def __init__(self, port: str, line: str = "rts"):
        if not port:
            raise SequencerError("The PTT sequencer is set to a serial line but no port is named (Settings)")
        self.port, self.line = port, line
        self.bits = {"rts": TIOCM_RTS, "dtr": TIOCM_DTR, "both": TIOCM_RTS | TIOCM_DTR}[line]
        self.name = f"serial:{port}:{line}"
        try:
            import fcntl
            self._fcntl = fcntl
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except (ImportError, OSError) as e:
            raise SequencerError(f"Could not open {port} for the PTT line: {e}") from e
        # Opening asserted both lines; clear them at once (module docstring).
        self._ioctl(TIOCMBIC, TIOCM_RTS | TIOCM_DTR)
        self.on = False

    def _ioctl(self, req: int, bits: int) -> None:
        self._fcntl.ioctl(self.fd, req, struct.pack("I", bits))

    def set(self, on: bool) -> None:
        self._ioctl(TIOCMBIS if on else TIOCMBIC, self.bits)
        self.on = on

    def close(self) -> None:
        try:
            self._ioctl(TIOCMBIC, TIOCM_RTS | TIOCM_DTR)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def make_output(cfg: dict):
    kind = cfg.get("seqOutput", "none")
    if kind == "serial":
        return SerialOutput(cfg.get("seqPort", ""), cfg.get("seqLine", "rts"))
    return NoOutput()


class Sequencer:
    """`output` is a driver above (or a test's recording fake); `on_state`
    receives each state name as it is entered."""

    def __init__(self, output, delay_ms: float = 25.0, on_state=None, sleep=time.sleep, clock=time.monotonic):
        self.out = output
        self.delay = max(0.0, float(delay_ms)) / 1000.0
        self.on_state = on_state or (lambda s: None)
        self.sleep, self.clock = sleep, clock
        self.state = "rx"
        self.converter = None

    def use(self, converter) -> None:
        """The converter (ohscore/converters.py) the next over goes out
        through, or None: told before key_up. The hook for per-band and
        per-transverter outputs - DESIGN-HAM section 6.1's "profiles per
        band/transverter": a transverter's own PTT line, a relay that
        switches the radio's output to it - which are not built, because
        the sequencer has one output and Brian's station has no
        transverter yet (decisions of 05/10/2026). Today it is only
        recorded, so a profile can be chosen here without the engine
        changing."""
        self.converter = converter

    def _enter(self, s: str) -> None:
        self.state = s
        self.on_state(s)

    def key_up(self, still_wanted=lambda: True) -> bool:
        """Line on, then wait the delay. False (and the line dropped again)
        if keying was cancelled during the wait - the watchdog, Esc - so no
        RF ever follows."""
        if isinstance(self.out, NoOutput):
            self._enter("tx")
            return True
        self.out.set(True)
        self._enter("seq")
        end = self.clock() + self.delay
        while self.clock() < end:
            if not still_wanted():
                self.out.set(False)
                self._enter("rx")
                return False
            self.sleep(min(0.005, max(0.0, end - self.clock())))
        self._enter("tx")
        return True

    def key_down(self) -> None:
        """After RF has stopped: wait the delay, then drop the line. Always
        drops it, whatever happened before."""
        if isinstance(self.out, NoOutput):
            self._enter("rx")
            return
        self._enter("hang")
        try:
            end = self.clock() + self.delay
            while self.clock() < end:
                self.sleep(min(0.005, max(0.0, end - self.clock())))
        finally:
            try:
                self.out.set(False)
            finally:
                self._enter("rx")

    def close(self) -> None:
        try:
            self.out.set(False)
        except Exception:  # noqa: BLE001 - closing must never raise
            pass
        self.out.close()
