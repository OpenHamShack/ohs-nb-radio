"""civsim: an IC-9700 emulated at the CI-V level, over TCP.

It exists so that ohscore/rig/civ.py - the code that will meet Ray's radio -
runs end to end without one, as hl2sim does for the Hermes-Lite 2. The
driver reaches it as `socket://127.0.0.1:<port>`, the same spelling
pyserial uses for a network serial port, so the driver's real open, frame
and parse paths are exercised, not a stand-in.

Written from the same pages as the driver (docs/ic9700-research.md), so
it cannot catch a misreading the two share. What it does:

- **Frames** as CIV p.3 lays them out, to and from address A2 (settable),
  FB for an accepted set, FA for anything refused or not emulated.
- **Commands**: 03 read frequency, 05 set frequency (refused with FA
  outside the band limits of the radio's version, EUR by default, as the
  radio refuses an out-of-band frequency), 04 read mode, 1A 06 read DATA
  mode and 1A 06 <data> <filter> set it (recorded in `data_sets`), 06 set mode
  (recorded in `mode_sets`; it turns DATA off here), 1C 00 read transmit state - and 1C 00 <data>, the *set* form that
  keys the radio, which it obeys and records, as a real radio would, so a
  test that no PTT command was ever sent has something to catch.
  `ptt_commands()` lists every received frame that could have keyed it
  (1C 00 with data, 17 send CW, 28 voice memory TX). 1A 05 01 15 and
  1A 05 01 16 read the MOD Input menu (DATA OFF MOD, DATA MOD), held in
  `mod_plain` and `mod_data` as base.MOD_INPUTS words; with a value byte
  they are menu writes, recorded in `menu_writes` - DATA MOD's and USB
  MOD Level's obeyed (the setup assistant's, ohsnb/rigsetup.py), DATA OFF
  MOD's refused with FA. The sim's defaults, MIC without DATA and USB
  with it, are a common WSJT-X setup, not a claim about the factory's
  [unverified].
- **The setup assistant's items** (12/10/2026): 19 00 answers the
  address as the ID; 1A 05 01 13 USB MOD Level (`usb_mod`, 0-255, 128 =
  50 %); 14 0A RF POWER (`rf_power`, read only: its write is
  answered FA, recorded in `received` like everything); 16 5A satellite mode (`satellite`); two bands, MAIN (`freq`,
  as before) and SUB (`sub_freq`), with `selected` saying which one 03
  and 05 act on, 07 D0 / D1 selecting, 07 D2 reading it, 07 B0
  exchanging them and 25 00 reading MAIN (FA in satellite mode, as CIV
  p.23 says the radio does).
- **Meters while it transmits**: 15 11 (Po) and 15 13 (ALC) from a
  model of the modulator: `drive()` - set by a test to the dBFS of the
  audio reaching the USB input now - plus the USB MOD Level (0 dB at
  50 %); ALC stays at 0 up to ALC_KNEE and rises 12 per dB above it, Po
  follows the drive's power up to 100 % (0213), scaled by RF POWER
  (`rf_power`, 14 0A, 0-255; never below 1 %, the 9700's 0.1 W of 10 W
  on 23 cm). Both read 0 on receive.
  A model, not a measurement: the knee and slopes are invented, the
  shape (nothing, then ALC once the drive passes a point) is the 9700's.
- **The IC-9700 as measured** (`real_9700()`, 12/10/2026, after Ray's
  first level set read the ALC "moving at -40 dB"; the tables are in
  openhamshack-nb docs/ic9700-research.md): the ALC is what holds the output
  to RF POWER, so `alc_tracks_power` makes the output min(setting,
  drive), the drive reaching full power at `full_drive_dbfs` (-25 dBFS
  at USB MOD 50 %: Ray's knee was -31 dBFS at 23 %, Brian's near -28 at
  50 %); Po reads 213 x power^0.576 (CIV p.4's 0143 = 50 %, 0213 =
  100 %). The ALC two ways, both seen: Ray's 9700 on 23 cm at 23 % read
  its keyed baseline (`alc_offset`, 5) until the knee and then rose about
  9 per dB (13 at -31, 39 at -28, 99 at -20 dBFS) - the default; Brian's
  on 2 m at 5 % read high with any audio at all (`alc_any_audio`: 80 at
  the knee, 4 per dB either side, 0 to 160). Also `po_dropouts`, Po
  readings to answer next in place of the model (Brian's meter read 3 at
  a level whose neighbours read 26 and 70), and `meter_attack_s` /
  `meter_release_s`, meters that follow with those time constants. Each
  is off by default, so the plain model above stays as it was. The sound
  card's queue is the test's `drive()` to model: the audio playing now,
  not the audio last written.
- **Unkey on a dead link**: none. A radio keyed by CI-V stays keyed
  until told otherwise, which is what a lost link tests need.
- **Transceive**: when on (the radio's default), a change of frequency
  made on the radio itself (`turn()`, the knob) is announced to every
  client as an 00 frame addressed to 00.
- **Echo**: optional (`echo=True`), like the radio's "CI-V USB Echo Back"
  (default OFF) or the REMOTE jack's single wire: every frame received is
  sent straight back before the answer.
- **The operator's hands**: `turn(hz)` and `key(on)`; `set_mode()`.
- **Faults**: `stall(True)` stops answering (an unplugged cable, a radio
  switched off); `noise=True` puts a garbage byte and a jammed frame
  before every answer, as a busy single-wire bus can.

    python3 -m ohscore.rig.civsim --port 50001

runs one until Ctrl-C for a session against the real program: then set
Transmitter to IC-9700 (CI-V) and the port to socket://127.0.0.1:50001.
"""
from __future__ import annotations

import argparse
import math
import socket
import threading
import time

from . import civ
from .base import MOD_INPUTS

BANDS = {
    # The IC-9700's transmit ranges by version (docs/ic9700-research.md, item A).
    "EUR": ((144_000_000, 146_000_000), (430_000_000, 440_000_000), (1_240_000_000, 1_300_000_000)),
    "USA": ((144_000_000, 148_000_000), (430_000_000, 450_000_000), (1_240_000_000, 1_300_000_000)),
}
MODE_BYTES = {v: k for k, v in civ.MODES.items()}
ALC_KNEE = -12.0        # dBFS at the USB input, USB MOD Level 50 %: where ALC starts to move (invented)


class CivSim:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, address: int = civ.IC9700,
                 freq: int = 1_268_200_000, mode: str = "usb", version: str = "EUR", transceive: bool = True,
                 echo: bool = False, noise: bool = False):
        self.address = address
        self.lock = threading.Lock()
        self.freq = int(freq)
        self.mode = mode
        self.data = False
        self.tx = False
        self.bands = BANDS[version]
        self.transceive = transceive
        self.echo = echo
        self.noise = noise
        self.stalled = False
        self.received: list[bytes] = []          # every frame body addressed to the radio
        self.sets: list[int] = []
        self.mode_sets: list[str] = []
        self.mod_plain, self.mod_data = "mic", "usb"
        self.menu_writes: list[bytes] = []
        self.data_sets: list[bool] = []
        self.tx_log: list[tuple[float, bool]] = []      # (monotonic, on) for each PTT command obeyed
        self.usb_mod = 128
        self.satellite = False
        self.sub_freq = 145_500_000
        self.selected = "main"
        self.drive = None                               # () -> dBFS at the USB input, or None: silence
        self.rf_power = 255                             # 14 0A, 0-255
        self.alc_offset = 0                             # what the ALC meter reads with no ALC action
        self.alc_tracks_power = False
        self.meter_attack_s = 0.0
        self.meter_release_s = 0.0
        self.full_drive_dbfs = ALC_KNEE
        self.alc_any_audio = False
        self.po_dropouts: list[int] = []
        self._meter_held: dict[str, tuple[float, float]] = {}   # meter -> (monotonic, value) last answered
        self.meter_reads: list[tuple[str, int]] = []    # (meter, value) for each meter read answered
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(4)
        self.host, self.port = self.srv.getsockname()
        self.conns: list[socket.socket] = []
        self.running = False

    @property
    def url(self) -> str:
        return f"socket://{self.host}:{self.port}"

    def start(self) -> "CivSim":
        self.running = True
        threading.Thread(target=self._accept, name="civsim", daemon=True).start()
        return self

    def stop(self) -> None:
        self.running = False
        # shutdown() before close(): on Linux, closing a listening socket
        # does not wake a thread blocked in its accept(), so every stopped
        # simulator left its accept thread behind for the life of the
        # process - one per test, 70 in a full run of the suite. shutdown
        # makes the accept() fail (EINVAL), and _accept returns.
        try:
            self.srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass                    # not listening, or not on this platform: close() is enough there
        try:
            self.srv.close()
        except OSError:
            pass
        for c in list(self.conns):
            try:
                c.close()
            except OSError:
                pass

    # ------------------------------------------------ the operator's hands
    def turn(self, hz: int) -> None:
        """The main dial: moves the frequency and, with transceive on,
        announces it."""
        with self.lock:
            self.freq = int(hz)
        if self.transceive:
            self._broadcast(civ.frame(civ.BROADCAST, self.address, bytes([civ.C_FREQ_PUSH]) + civ.to_bcd(hz)))

    def key(self, on: bool) -> None:
        with self.lock:
            self.tx = bool(on)

    def set_mode(self, mode: str, data: bool = False) -> None:
        with self.lock:
            self.mode, self.data = mode, data

    def stall(self, on: bool) -> None:
        self.stalled = bool(on)

    def ptt_commands(self) -> list[bytes]:
        """Every received command that could have made the radio transmit."""
        with self.lock:
            return [b for b in self.received
                    if (b[:2] == bytes([civ.C_TX, 0x00]) and len(b) > 2) or b[:1] in (b"\x17", b"\x28")]

    # ------------------------------------------------ the bus
    def _broadcast(self, data: bytes) -> None:
        for c in list(self.conns):
            try:
                c.sendall(data)
            except OSError:
                pass

    def _accept(self) -> None:
        while self.running:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.conns.append(c)
            threading.Thread(target=self._serve, args=(c,), name="civsim-conn", daemon=True).start()

    def _serve(self, c: socket.socket) -> None:
        reader = civ.FrameReader()
        try:
            while self.running:
                data = c.recv(4096)
                if not data:
                    return
                for to, frm, body in reader.feed(data):
                    if to != self.address:
                        continue
                    with self.lock:
                        self.received.append(body)
                    if self.stalled:
                        continue
                    out = b""
                    if self.echo:
                        out += civ.frame(to, frm, body)
                    if self.noise:
                        out += b"\x00" + civ.PRE + bytes([frm, self.address, civ.JAM, civ.JAM]) + bytes([civ.EOM])
                    out += civ.frame(frm, self.address, self._answer(body))
                    c.sendall(out)
        except OSError:
            return
        finally:
            if c in self.conns:
                self.conns.remove(c)
            try:
                c.close()
            except OSError:
                pass

    def _in_band(self, hz: int) -> bool:
        return any(lo <= hz <= hi for lo, hi in self.bands)

    def _meter_now(self, which: str) -> float:
        """The meter's value if it followed the drive at once."""
        if not self.tx:
            return 0.0
        drive = self.drive() if self.drive is not None else None
        zero = float(self.alc_offset) if which == "alc" else 0.0
        if drive is None or self.usb_mod <= 0:
            return zero
        power = max(0.01, self.rf_power / 255.0)
        eff = drive + 20 * math.log10(self.usb_mod / 128.0)
        if self.alc_tracks_power:
            knee = self.full_drive_dbfs + 10 * math.log10(power)
            if which == "alc" and self.alc_any_audio:
                return min(160.0, zero + max(0.0, 80 + 4 * (eff - knee)))
            if which == "alc":
                return min(160.0, zero + max(0.0, 9 * (eff - knee)))
            out = min(power, 10 ** ((eff - self.full_drive_dbfs) / 10))
            return min(213.0, 213 * out ** 0.576)
        if which == "alc":
            return min(120.0, zero + max(0.0, (eff - ALC_KNEE) * 12))
        return min(213.0, 213 * power * 10 ** ((min(eff, ALC_KNEE) - ALC_KNEE) / 10))

    def real_9700(self, rf_power: int | None = None, alc_any_audio: bool = False) -> "CivSim":
        """The meters as the real IC-9700s measured (module docstring):
        Ray's ALC shape by default, Brian's 2 m one with `alc_any_audio`."""
        with self.lock:
            self.alc_tracks_power, self.full_drive_dbfs, self.alc_offset = True, -25.0, 5
            self.alc_any_audio = bool(alc_any_audio)
            if rf_power is not None:
                self.rf_power = int(rf_power)
        return self

    def meter(self, which: str) -> int:
        """The modulator model (module docstring): Po or ALC, 0-255, as
        the meter shows it now - following the model with the attack and
        release time constants, when they are set."""
        if which == "po" and self.po_dropouts:
            return int(self.po_dropouts.pop(0))
        target = self._meter_now(which)
        now = time.monotonic()
        last = self._meter_held.get(which)
        v = target
        if last is not None:
            tau = self.meter_attack_s if target > last[1] else self.meter_release_s
            if tau > 0:
                v = target + (last[1] - target) * math.exp(-(now - last[0]) / tau)
        self._meter_held[which] = (now, v)
        return int(round(v))

    def _answer(self, body: bytes) -> bytes:
        ok, ng = bytes([civ.OK]), bytes([civ.NG])
        cmd = body[:1]
        with self.lock:
            if body == civ.READ_FREQ:
                return civ.READ_FREQ + civ.to_bcd(self.freq if self.selected == "main" else self.sub_freq)
            if cmd == bytes([civ.C_SET_FREQ]) and len(body) == 6:
                try:
                    hz = civ.from_bcd(body[1:6])
                except ValueError:
                    return ng
                if not self._in_band(hz):
                    return ng
                if self.selected == "main":
                    self.freq = hz
                else:
                    self.sub_freq = hz
                self.sets.append(hz)
                return ok
            if body == civ.READ_ID:
                return civ.READ_ID + bytes([self.address])
            if body in (civ.READ_PO, civ.READ_ALC):
                which = "po" if body == civ.READ_PO else "alc"
                v = self.meter(which)
                self.meter_reads.append((which, v))
                return body + civ.level_bcd(v)
            if body == civ.READ_SAT:
                return body + bytes([0x01 if self.satellite else 0x00])
            if body[:2] == civ.READ_SAT and len(body) == 3:
                if body[2] not in (0, 1):
                    return ng
                self.satellite = body[2] == 1
                return ok
            if body == civ.READ_SELECTED:
                return body + bytes([0x01 if self.selected == "sub" else 0x00])
            if body in (civ.SELECT_MAIN, civ.SELECT_SUB):
                self.selected = "main" if body == civ.SELECT_MAIN else "sub"
                return ok
            if body == civ.EXCHANGE_BANDS:
                self.freq, self.sub_freq = self.sub_freq, self.freq
                return ok
            if body == civ.READ_MAIN_FREQ:
                # CIV p.23: FA in satellite mode.
                return ng if self.satellite else body + civ.to_bcd(self.freq)
            if body == civ.READ_USB_MOD:
                return body + civ.level_bcd(self.usb_mod)
            if body == civ.READ_RF_POWER:
                return body + civ.level_bcd(self.rf_power)
            if body[:4] == civ.READ_USB_MOD and len(body) == 6:
                self.menu_writes.append(body)
                try:
                    v = civ.from_level(body[4:])
                except ValueError:
                    return ng
                if v > 255:
                    return ng
                self.usb_mod = v
                return ok
            if cmd == bytes([civ.C_SET_MODE]) and len(body) in (2, 3):
                mode = civ.MODES.get(body[1])
                if mode is None:
                    return ng
                self.mode = mode
                # A mode set leaves DATA off here [unverified on a real
                # 9700], so a driver that wants USB-D must say so after.
                self.data = False
                self.mode_sets.append(mode)
                return ok
            if body[:2] == civ.READ_DATA and len(body) == 4:
                # 1A 06 <data> <filter>: CIV p.17 (filter 00 with data off).
                if body[2] not in (0, 1) or (body[2] == 1) != (body[3] in (1, 2, 3)) \
                        or (body[2] == 0 and body[3] != 0):
                    return ng
                self.data = body[2] == 1
                self.data_sets.append(self.data)
                return ok
            if body == civ.READ_MODE:
                return civ.READ_MODE + bytes([MODE_BYTES.get(self.mode, 0x01), 0x01])
            if body == civ.READ_DATA:
                return civ.READ_DATA + bytes([0x01 if self.data else 0x00, 0x01])
            if body == civ.READ_TX:
                return civ.READ_TX + bytes([0x01 if self.tx else 0x00])
            if body[:2] == civ.READ_TX and len(body) == 3:
                # The set form: it keys (or unkeys) the radio.
                self.tx = body[2] != 0
                self.tx_log.append((time.monotonic(), self.tx))
                return ok
            for name, read in (("mod_plain", civ.READ_MOD_PLAIN), ("mod_data", civ.READ_MOD_DATA)):
                if body == read:
                    return read + bytes([MOD_INPUTS.index(getattr(self, name))])
                if body[:len(read)] == read:
                    self.menu_writes.append(body)
                    # DATA MOD is the assistant's to set; DATA OFF MOD is not.
                    if name == "mod_data" and len(body) == len(read) + 1 and body[-1] < len(MOD_INPUTS):
                        self.mod_data = MOD_INPUTS[body[-1]]
                        return ok
                    return ng
            return ng


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Emulate an IC-9700's CI-V on TCP (ohscore/rig/civsim.py).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=50001)
    ap.add_argument("--mhz", type=float, default=1268.2)
    ap.add_argument("--echo", action="store_true", help="echo every frame back, like CI-V USB Echo Back ON")
    a = ap.parse_args(argv)
    sim = CivSim(a.host, a.port, freq=int(a.mhz * 1e6), echo=a.echo).start()
    print(f"civsim: IC-9700 (CI-V {sim.address:02X}h) on {sim.url} - in OpenHamShack QO-100 NB set Transmitter to "
          f"IC-9700 (CI-V) and the port to {sim.url}. Ctrl-C stops.", flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()


if __name__ == "__main__":
    main()
