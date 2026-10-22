"""A fake rigctld: Hamlib's line protocol over TCP, standing in for an IC-9700.

It speaks the subset of rigctld(1)'s default protocol that matters here,
as the manual describes it (docs/ic9700-research.md): `f` answers the
frequency in Hz, `F <Hz>` sets it and answers `RPRT 0`, `t` answers the
PTT state, `m` answers the mode and passband on two lines, `M <mode> <Hz>`
sets the mode (recorded in `mode_sets`), `T <0|1>`
sets PTT, `\\chk_vfo` answers `CHKVFO 0` (or 1 with `vfo_mode=True`, as
`rigctld --vfo` would, and then those commands want a VFO name first or
answer `RPRT -1`). Anything else answers `RPRT -11` (Hamlib's "not
available"). It is written from the same document as the
driver, so it checks the driver's use of the protocol, not Hamlib itself.

Every line received is recorded (`lines`), so a test can prove that the
driver never sent `T` (set PTT) - the emulator accepts it, as a real
rigctld would, precisely so that such a test has something to catch.
The operator's hands are `turn(hz)` (the knob) and `key(on)` (the
radio's own PTT); `stall(True)` makes it stop answering, like a rigctld
whose radio has gone.

    python3 -m ohscore.rig.rigctlsim --port 4532

runs one until Ctrl-C for a session against the real program.
"""
from __future__ import annotations

import argparse
import socket
import threading
import time


VFO_TOKENS = ("VFOA", "VFOB", "VFOC", "currVFO", "VFO", "MEM", "Main", "Sub", "MainA", "MainB", "SubA", "SubB",
              "TX", "RX")


class RigctldSim:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, freq: int = 1_268_200_000, mode: str = "USB",
                 vfo_mode: bool = False):
        self.lock = threading.Lock()
        self.freq = int(freq)
        self.mode = mode
        self.passband = 2400
        self.ptt = False
        self.vfo_mode = vfo_mode
        self.stalled = False
        self.lines: list[str] = []
        self.tx_log: list[tuple[float, bool]] = []      # (monotonic, on) for each T obeyed
        self.sets: list[int] = []
        self.mode_sets: list[str] = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(4)
        self.host, self.port = self.srv.getsockname()
        self.running = False
        self.conns: list[socket.socket] = []

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    def start(self) -> "RigctldSim":
        self.running = True
        threading.Thread(target=self._accept, name="rigctlsim", daemon=True).start()
        return self

    def stop(self) -> None:
        self.running = False
        try:
            self.srv.close()
        except OSError:
            pass
        for c in list(self.conns):
            try:
                c.close()
            except OSError:
                pass

    # -------------------------------------------------- the operator's hands
    def turn(self, hz: int) -> None:
        with self.lock:
            self.freq = int(hz)

    def key(self, on: bool) -> None:
        with self.lock:
            self.ptt = bool(on)

    def stall(self, on: bool) -> None:
        self.stalled = bool(on)

    def ptt_commands(self) -> list[str]:
        """Every line that would have changed the PTT state."""
        return [ln for ln in self.lines if ln.split()[:1] in (["T"], ["\\set_ptt"])]

    # -------------------------------------------------- the server
    def _accept(self) -> None:
        while self.running:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conns.append(c)
            threading.Thread(target=self._serve, args=(c,), name="rigctlsim-conn", daemon=True).start()

    def _serve(self, c: socket.socket) -> None:
        buf = b""
        try:
            while self.running:
                data = c.recv(4096)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    line = raw.decode("ascii", "replace").strip()
                    with self.lock:
                        self.lines.append(line)
                    if self.stalled:
                        continue
                    out = self._answer(line)
                    if out:
                        c.sendall(out.encode("ascii"))
        except OSError:
            return
        finally:
            try:
                c.close()
            except OSError:
                pass

    def _answer(self, line: str) -> str:
        parts = line.split()
        if not parts:
            return ""
        cmd, args = parts[0], parts[1:]
        with self.lock:
            if cmd == "\\chk_vfo":
                return f"CHKVFO {1 if self.vfo_mode else 0}\n"
            if self.vfo_mode and cmd in ("f", "F", "t", "T", "m", "M"):
                # Started with --vfo, these want a VFO first.
                if not args or args[0] not in VFO_TOKENS:
                    return "RPRT -1\n"
                args = args[1:]
            if cmd == "f":
                return f"{self.freq}\n"
            if cmd == "F" and args:
                try:
                    self.freq = int(float(args[-1]))
                except ValueError:
                    return "RPRT -1\n"
                self.sets.append(self.freq)
                return "RPRT 0\n"
            if cmd == "t":
                return f"{1 if self.ptt else 0}\n"
            if cmd == "T" and args:
                self.ptt = args[-1] not in ("0",)
                self.tx_log.append((time.monotonic(), self.ptt))
                return "RPRT 0\n"
            if cmd == "m":
                return f"{self.mode}\n{self.passband}\n"
            if cmd == "M" and len(args) == 2:
                self.mode = args[0]
                self.mode_sets.append(args[0])
                return "RPRT 0\n"
            return "RPRT -11\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="A fake rigctld standing in for an IC-9700 (ohscore/rig/rigctlsim.py).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4532)
    ap.add_argument("--mhz", type=float, default=1268.2)
    a = ap.parse_args(argv)
    sim = RigctldSim(a.host, a.port, int(a.mhz * 1e6)).start()
    print(f"rigctlsim: fake rigctld on {sim.host}:{sim.port} - in OpenHamShack QO-100 NB choose Hamlib rigctld, "
          f"host {sim.host}, port {sim.port}. Ctrl-C stops.", flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()


if __name__ == "__main__":
    main()
