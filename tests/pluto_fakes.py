"""A pretend Pluto for the diagnostics and AD9364-fix tests: an IIO module
whose contexts report what the radio's U-Boot environment says it is,
and an SSH side (fake sessions, or a real paramiko server on loopback)
that edits that environment and simulates the reboot. No radio, no
network beyond 127.0.0.1, nothing transmitted."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shlex
import socket
import threading
import time

from ohsradio import plutofix


class Pluto:
    """The radio's state. `down_polls` is how many identity probes after a
    reboot find nothing; None means it never comes back."""

    def __init__(self, fw="v0.38", password="analog", env=None, down_polls=2, serial="104473dc5996000c0d00",
                 report_identity=True):
        self.fw = fw
        self.password = password
        self.env = dict(env or {})
        self.down_polls = down_polls
        self.serial = serial
        self.report_identity = report_identity
        self.booted_env = dict(self.env)         # what the running firmware read at its last boot
        self.down_left = 0
        self.commands: list[str] = []
        self.logins: list[str] = []              # passwords tried, so a test can see what was sent
        self.reboots = 0
        self.lock = threading.Lock()

    # -- what the firmware makes of its environment
    def identity(self) -> str:
        e = self.booted_env
        n = int(self.fw.split(".")[1]) if self.fw.startswith("v0.") else 99
        if n >= 32 and e.get("compatible"):
            return e["compatible"]
        if e.get("attr_name") == "compatible" and e.get("attr_val"):
            return e["attr_val"]
        return "ad9363"

    # -- the IIO side
    @property
    def iio(self):
        radio = self

        class Ctx:
            def __init__(self):
                attrs = {"hw_model": "Analog Devices PlutoSDR Rev.B (Z7010-AD9363)", "hw_serial": radio.serial,
                         "fw_version": radio.fw}
                if radio.report_identity:
                    attrs["ad9361-phy,model"] = radio.identity()
                self.attrs = attrs

            def find_device(self, name):
                return object() if name == "ad9361-phy" else None

            def set_timeout(self, ms):
                pass

        class Module:
            @staticmethod
            def Context(uri):
                with radio.lock:
                    if radio.down_left is None or radio.down_left > 0:
                        if radio.down_left:
                            radio.down_left -= 1
                        raise OSError(113, "No route to host")
                return Ctx()
        return Module

    def identify(self, uri):
        return plutofix.probe(uri, 1.0, iio_mod=self.iio)

    # -- the shell side
    def execute(self, cmd: str) -> tuple[int, str]:
        self.commands.append(cmd)
        words = shlex.split(cmd.split("2>&1")[0])
        if words[:1] == ["fw_printenv"]:
            return 0, "".join(f"{k}={self.env[k]}\n" if k in self.env else f'## Error: "{k}" not defined\n'
                              for k in words[1:])
        if words[:1] == ["fw_setenv"] and len(words) >= 2:
            if len(words) == 2:
                self.env.pop(words[1], None)
            else:
                self.env[words[1]] = " ".join(words[2:])
            return 0, ""
        if words == ["reboot"]:
            self.reboot()
            return 0, ""
        return 127, f"sh: {words[0] if words else ''}: not found\n"

    def reboot(self):
        with self.lock:
            self.reboots += 1
            self.booted_env = dict(self.env)
            self.down_left = self.down_polls

    def connect(self, host, password):
        self.logins.append(password)
        if password != self.password:
            raise plutofix.AuthFailed("Authentication failed.")
        return Session(self)


class Session:
    def __init__(self, radio):
        self.radio = radio
        self.closed = False

    def run(self, cmd, timeout_s=15.0):
        return self.radio.execute(cmd)

    def start(self, cmd):
        self.radio.execute(cmd)

    def close(self):
        self.closed = True


def fixer(radio, uri="ip:192.168.2.1", **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("settle_s", 0.0)
    kw.setdefault("poll_s", 0.0)
    return plutofix.Fixer(uri, connect=radio.connect, identify=radio.identify, **kw)


class SshServer:
    """A real SSH server on 127.0.0.1 (paramiko's server classes) in front
    of a Pluto: password auth as root, exec requests run against its
    environment. For testing ParamikoSession itself."""

    def __init__(self, radio):
        import paramiko
        self.paramiko = paramiko
        self.radio = radio
        self.key = paramiko.RSAKey.generate(2048)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.transports = []
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        paramiko = self.paramiko
        radio = self.radio

        class Server(paramiko.ServerInterface):
            def get_allowed_auths(self, username):
                return "password"

            def check_auth_password(self, username, password):
                radio.logins.append(password)
                ok = username == "root" and password == radio.password
                return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED if kind == "session" else \
                    paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

            def check_channel_exec_request(self, channel, command):
                def reply():
                    # paramiko sends the exec request's success only after
                    # this handler returns; output and exit status sent
                    # before it make the client see a closed channel.
                    time.sleep(0.1)
                    status, out = radio.execute(command.decode())
                    if out:
                        channel.sendall(out.encode())
                    channel.send_exit_status(status)
                    channel.close()
                threading.Thread(target=reply, daemon=True).start()
                return True

        while self.alive:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.key)
            self.transports.append(t)
            try:
                t.start_server(server=Server())
            except Exception:  # noqa: BLE001 - a client that gave up
                pass

    def close(self):
        self.alive = False
        self.sock.close()
        for t in self.transports:
            t.close()
