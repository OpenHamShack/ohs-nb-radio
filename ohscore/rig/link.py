"""RigLink: one external rig, polled on its own thread.

The engine never waits on a serial port or a socket: a rig that has been
unplugged answers nothing for a timeout per command, and that must cost
the poll thread its time, never receive. So the link owns the rig on a
thread of its own, and talks to its owner through two callables:

- `want() -> int | None`: the frequency the owner wants the rig on now
  (None: leave it alone). Asked every cycle; the link sets the rig when
  the answer differs from where the rig is. Level-triggered rather than a
  queue of requests, so a burst of dial moves costs one write - the last -
  and a write that failed is simply tried again next cycle.
- `want_mode(mode) -> str | None`: given the mode just read from the rig,
  "usb" or "lsb" to put it in that instead (None: leave it). Asked only
  after a fresh mode read, so at most once per `mode_every_s`.
- `report(snapshot)`: called every cycle with what was read, and whether
  the rig moved by itself (the operator turned its knob).

Decisions:

- **Polling, not transceive.** CI-V transceive announces frequency
  changes, but not the transmit state, which needs polling anyway (and
  rigctld has no announcements at all), so the link polls frequency and
  transmit state every cycle and treats announced frequencies only as the
  same news a little earlier. It works the same with the radio's
  transceive setting on or off. The poll interval is therefore the
  latency of everything that follows the rig - the TX marker, muting
  receive audio while it transmits - and is a setting.
- **Knob or echo.** The link remembers the frequency it last saw or set
  (`expected`). A read that differs from it is the operator's knob; a read
  equal to it is the rig confirming our own write. The owner is told which.
- **A refused write is not retried** until `want()` asks for something
  else: a radio answering NG to one frequency answers NG to it every
  cycle, and the operator needs one sentence, not ten a second.
- **A mode write is tried once per mode the rig is found in**: refused
  (or failing) in FM, it is not asked again until the rig has been in
  some other mode - the same one sentence, not one a second.
- **Writes while transmitting** happen only when `may_set_keyed` is True
  (the owner decides; QO-100 NB's reasons are in ohsnb/extrig.py). The
  transmit state read at the top of a cycle is stale by the time the
  cycle writes: the owner's digital over may have keyed through `ptt()`
  in between, or the operator pressed PTT. So the transmit state is read
  again, under the same lock, straight before each write a cycle makes
  (frequency, SSB mode, DATA mode), and a keyed rig gets none of them
  until it is back on receive. One extra 1C 00 per write, and writes are
  rare. Added 18/10/2026 while looking into Ray's chopped IC-9700
  downlink: that turned out not to be this (captured against the
  emulator, nothing was written mid-over), but the window was real, and
  a retune mid-over is the one thing the radio must never get from us.
- **PTT** (`ptt()`, since 12/10/2026): called by the owner's digital
  over path from its own thread, under the link's lock like every other
  transaction, with the permit the drivers demand (base.py). It reads the
  transmit state straight back (1C 00, rigctld `t`) and returns what the
  radio says, so the caller acts on the radio's word rather than on
  having asked. With `read_mod_input` the link also reads, every
  `mod_every_s`, where the radio takes its transmit audio from.
- **Pause** (`pause()`/`resume()`, 12/10/2026): the setup assistant
  (ohsnb/rigsetup.py) needs the port to itself for a few seconds - to look
  for the radio at other CI-V addresses, and to read and write its menus
  with a permit of its own - and Windows refuses a second open of a
  serial port. So the link stops polling, closes the rig and waits until
  resumed; nothing is reported meanwhile, and anything that needs the rig
  (PTT included) fails as it does with the link down.
- **Meters** (`read_meters()`): Po and ALC through the open rig, for the
  assistant's level set while NB's own over keys the radio.
- **Lost link.** When nothing has been answered for `lost_after` seconds
  the link reports `link: "lost"` and `keyed: False` - the rig's transmit
  state is then unknown, and an owner that muted receive audio while the
  rig transmitted must not stay muted on a guess. It closes the rig and
  reopens it every `retry_s` until it answers again.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .base import Rig, RigError, RigTimeout

log = logging.getLogger("ohscore.rig")


def describe(rig) -> str:
    """A rig's link as a log line names it: the CI-V port, baud rate and
    address, or rigctld's host and port - what to compare first with the
    radio's own menu when a remote operator's link will not come up."""
    if rig is None:
        return "the rig"
    if hasattr(rig, "port_name"):
        return f"CI-V {rig.port_name} at {rig.baud} baud, address {rig.addr:02X}h"
    if hasattr(rig, "host"):
        return f"rigctld {rig.host}:{rig.port}"
    return getattr(rig, "name", type(rig).__name__)


class RigLink:
    def __init__(self, make_rig: Callable[[], Rig], want: Callable[[], int | None],
                 report: Callable[[dict], None], *, poll_s: float = 0.1, mode_every_s: float = 1.0,
                 lost_after: float = 1.5, retry_s: float = 2.0, may_set_keyed: bool = False,
                 want_mode: Callable[[str], str | None] | None = None, name: str = "ohscore-rig",
                 read_mod_input: bool = False, mod_every_s: float = 5.0):
        self.make_rig = make_rig
        self.want = want
        self.want_mode = want_mode
        self.report = report
        self.poll_s = float(poll_s)
        self.mode_every_s = float(mode_every_s)
        self.lost_after = float(lost_after)
        self.retry_s = float(retry_s)
        self.may_set_keyed = may_set_keyed
        self.name = name
        self.rig: Rig | None = None
        self.io = threading.Lock()          # one transaction at a time on the rig
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "connecting"
        self.error = ""
        self.freq: int | None = None
        self.keyed = False
        self.mode = ""
        self.data = False
        self.expected: int | None = None
        self.refused: int | None = None
        self.mode_tried = ""                # the rig mode a mode write was last tried from
        self.last_ok = time.monotonic()
        self.next_mode = 0.0
        self.cycles = 0
        self.writes = 0
        self.read_mod_input = read_mod_input
        self.mod_every_s = float(mod_every_s)
        self.next_mod = 0.0
        self.mod_input: dict | None = None
        self.mode_request: tuple[str, bool] | None = None
        self.paused = threading.Event()
        self.idle = threading.Event()       # the loop has seen `paused` and stopped touching the rig
        # The open failure last logged: a link retrying every 2 s logs a
        # failure when it starts or changes, not every attempt.
        self.said_open_error = ""
        self.described = ""

    # ------------------------------------------------------------- lifecycle
    def start(self) -> "RigLink":
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stop_ev.set()
        if self.thread:
            self.thread.join(timeout=3)
        self._close()

    def _close(self) -> None:
        with self.io:
            if self.rig is not None:
                try:
                    self.rig.close()
                except Exception:  # noqa: BLE001
                    pass
                self.rig = None

    def read_now(self) -> int:
        """One frequency read through the open rig, for Settings' "Test
        connection" while the link runs (a second open of the same serial
        port would be refused on Windows). Raises RigError."""
        with self.io:
            if self.rig is None:
                raise RigError(self.error or "The rig link is not connected yet")
            return self.rig.read_freq()

    def pause(self, timeout: float = 3.0) -> None:
        """Stop polling and let go of the port until resume() (module
        docstring). Returns once the loop has stopped touching the rig."""
        self.idle.clear()
        self.paused.set()
        if self.thread is not None and self.thread.is_alive():
            self.idle.wait(timeout)
        self._close()

    def resume(self) -> None:
        self.paused.clear()

    def call(self, fn):
        """fn(rig) under the link's lock, through the open rig: one read the
        owner needs now (the setup assistant's USB MOD Level). Raises
        RigError when the link has no rig open."""
        with self.io:
            if self.rig is None:
                raise RigError(self.error or "The rig link is not connected")
            return fn(self.rig)

    def read_meters(self) -> dict:
        """{"po", "alc"}: the rig's meters, 0-255 (CI-V only). Raises RigError."""
        with self.io:
            if self.rig is None:
                raise RigError(self.error or "The rig link is not connected")
            if not hasattr(self.rig, "read_meter"):
                raise RigError("This link cannot read the radio's meters")
            return {"alc": self.rig.read_meter("alc"), "po": self.rig.read_meter("po")}

    def ptt(self, on: bool, permit) -> bool:
        """Key or unkey the rig under `permit` and return the transmit state
        it reports straight afterwards. Raises RigError (ForbiddenCommand
        without a valid permit, before anything is sent)."""
        with self.io:
            if self.rig is None:
                raise RigError(self.error or "The rig link is not connected")
            self.rig.set_ptt(on, permit)
            keyed = self.rig.read_tx()
        self.keyed = keyed
        return keyed

    def set_data_mode_now(self, mode: str, data: bool,
                          on_receive_only: bool = False) -> tuple[str, bool] | None:
        """Put the rig in `mode` ("usb"/"lsb") with DATA on or off, now, and
        return the (mode, data) it then reports. For a key-up, which must
        know before keying. With `on_receive_only` (the poll's one-shot
        request) nothing is sent, and None returned, when the rig reads
        back transmitting. Raises RigError."""
        with self.io:
            if self.rig is None:
                raise RigError(self.error or "The rig link is not connected")
            if on_receive_only and not self._receiving(self.rig):
                return None
            self.rig.set_data_mode(mode, data)
            got = self.rig.read_mode()
        self.mode, self.data = got
        self.mode_tried = ""
        self.writes += 1
        return got

    def request_data_mode(self, mode: str, data: bool) -> None:
        """Ask for the rig in `mode` with DATA on or off, once: the poll
        thread does it on its next cycle with the rig on receive (never
        while it transmits), and then forgets the request. One-shot rather
        than level-triggered like `want()`, so an operator who changes the
        mode on the radio afterwards is not fought every cycle."""
        self.mode_request = (mode, bool(data))

    def _receiving(self, rig: Rig) -> bool:
        """Under self.io, straight before one of a cycle's writes: whether it
        may go (module docstring, "Writes while transmitting")."""
        if self.may_set_keyed:
            return True
        if rig.read_tx():
            self.keyed = True
            return False
        return True

    # ------------------------------------------------------------- the loop
    def _run(self) -> None:
        while not self.stop_ev.is_set():
            if self.paused.is_set():
                self.idle.set()
                self.stop_ev.wait(0.05)
                continue
            if self.rig is None:
                if not self._open():
                    self.stop_ev.wait(self.retry_s)
                    continue
            t0 = time.monotonic()
            try:
                self._cycle()
                self.last_ok = time.monotonic()
                if self.state != "ok":
                    self.state, self.error = "ok", ""
            except RigTimeout as e:
                self._failed(e)
            except RigError as e:
                self._failed(e)
            except Exception as e:  # noqa: BLE001 - a driver bug must not kill the link silently
                log.exception("rig link")
                self._failed(e)
            self.cycles += 1
            self.stop_ev.wait(max(0.0, self.poll_s - (time.monotonic() - t0)))

    def _open(self) -> bool:
        rig = None
        try:
            rig = self.make_rig()
            rig.open()
        except Exception as e:  # noqa: BLE001 - ImportError (pyserial), OSError, RigError alike
            self.error = str(e)
            if self.error != self.said_open_error:
                self.said_open_error = self.error
                log.warning("rig link: could not open %s: %s", describe(rig), e)
            was = self.state
            self.state = "lost" if was in ("ok", "lost") else "error"
            self.keyed = False
            self._report(moved=False)
            return False
        with self.io:
            self.rig = rig
        # INFO the first time only: a radio switched off behind a USB port
        # that still opens is reopened every retry_s, for hours.
        d = describe(rig)
        log.log(logging.INFO if d != self.described else logging.DEBUG, "rig link opened: %s", d)
        self.described = d
        self.last_ok = time.monotonic()
        self.expected = None
        self.refused = None
        self.mode_tried = ""
        self.next_mode = 0.0
        self.next_mod = 0.0
        return True

    def _failed(self, e: Exception) -> None:
        self.error = str(e)
        if time.monotonic() - self.last_ok >= self.lost_after:
            # Unknown is not "transmitting": see the module docstring.
            if self.state != "lost":
                log.warning("rig link lost: %s, no answer for %.1f s: %s", self.described,
                            time.monotonic() - self.last_ok, e)
            self.state = "lost"
            self.keyed = False
            self._report(moved=False)
            self._close()

    def _cycle(self) -> None:
        with self.io:
            rig = self.rig
            if rig is None:
                return
            pushed = rig.pushed()
            f = rig.read_freq()
            keyed = rig.read_tx()
            now = time.monotonic()
            fresh = now >= self.next_mode
            if fresh:
                self.mode, self.data = rig.read_mode()
                self.next_mode = now + self.mode_every_s
            if self.read_mod_input and now >= self.next_mod:
                self.mod_input = rig.read_mod_input()
                self.next_mod = now + self.mod_every_s
        moved = self.expected is not None and f != self.expected
        if moved:
            self.refused = None
        self.freq, self.keyed = f, keyed
        self.expected = f
        if self.state != "ok":
            # Here, not in _run: this is where the state turns "ok", and
            # the report below already tells the owner so.
            log.info("rig link up: %s (was %s%s)", self.described, self.state,
                     f": {self.error}" if self.error else "")
            self.said_open_error = ""
        self.state = "ok"
        self._report(moved=moved, pushed=len(pushed))
        if fresh:
            self._set_mode(keyed)
        req = self.mode_request
        if req is not None and not keyed:
            was = (self.mode, self.data)
            try:
                got = self.set_data_mode_now(*req, on_receive_only=True)
            except RigTimeout:
                raise
            except RigError as e:
                self.mode_request = None
                self.error = str(e)
                self._report(moved=False, data_mode_refused=req)
            else:
                if got is None:
                    return              # keyed after all: the request waits for the unkey
                self.mode_request = None
                self._report(moved=False, data_mode_from=was, data_mode_to=got)
        target = self.want()
        if target is None or target == f or target == self.refused:
            return
        if keyed and not self.may_set_keyed:
            return
        with self.io:
            if self.rig is None or not self._receiving(self.rig):
                return
            try:
                self.rig.set_freq(int(target))
            except RigTimeout:
                raise
            except RigError as e:
                self.refused = int(target)
                self.error = str(e)
                self._report(moved=False, refused=int(target))
                return
        self.writes += 1
        self.error = ""
        self.expected = int(target)
        self.freq = int(target)
        self._report(moved=False, wrote=int(target))

    def _set_mode(self, keyed: bool) -> None:
        if self.mode != self.mode_tried:
            self.mode_tried = ""
        if self.want_mode is None or self.mode_tried or (keyed and not self.may_set_keyed):
            return
        to = self.want_mode(self.mode)
        if to is None or to == self.mode:
            return
        was = self.mode
        with self.io:
            if self.rig is None or not self._receiving(self.rig):
                return              # asked again at the next mode read, on receive
            self.mode_tried = self.mode
            try:
                self.rig.set_ssb(to)
            except RigTimeout:
                raise
            except RigError as e:
                self.error = str(e)
                self._report(moved=False, mode_refused=to)
                return
        self.writes += 1
        self.mode = to
        self.next_mode = 0.0                # read it back next cycle
        self._report(moved=False, mode_from=was, mode_to=to)

    def _report(self, moved: bool, **extra) -> None:
        snap = {"link": self.state, "error": self.error, "freq": self.freq, "keyed": self.keyed,
                "mode": self.mode, "data": self.data, "modInput": self.mod_input, "moved": moved, **extra}
        try:
            self.report(snap)
        except Exception:  # noqa: BLE001
            log.exception("rig link report")
