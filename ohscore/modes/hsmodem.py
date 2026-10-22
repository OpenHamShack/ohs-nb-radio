"""HSmodem's content layer: what the frames of DJ0ABR's high-speed modem
carry, read and written. The modem itself - demodulator, frame, FEC - is
ohsdigi's (rust/ohsdigi/src/hsmodem); this is the few hundred bytes a second
above it. Every format here is from HSmodem's source and is cited in
docs/hsmodem-research.md section 5; what is not settled there is marked
[unverified] here too.

Receive (QO-100's multimedia beacon, in QO-100 NB):

    rx = BeaconReceiver(rate=12000.0, emit=callback, folder=Path(...))
    rx.feed_iq(iq)        # complex64 baseband, the beacon at 0 Hz
    -> callback({"mode": "mmb", "kind": "bulletin" | "file" | "image" | "dx" | "cw"
                 | "nbspec" | "wbspec" | "station" | "frame", ...})

The frame types (HSmodem's frame "type" nibble): 2 image (a JPEG, not
zipped), 3 ASCII, 4 HTML, 5 binary (each a ZIP holding one file of the same
name), 7 user info, 8 external data - the beacon's streams, whose first
payload byte says which: 0 DX cluster, 1 NB spectrum, 2 CW skimmer, 3 WB
spectrum. Files arrive as a 55-byte header (name, ID = CRC-16 of the file,
size) and the file, cut into 219-byte payloads numbered by the frame
counter; blocks are kept across repeats until every one is in, as
HSmodem's GUI does.

Station to station (the "hsmodem" mode, any of HSmodem's ten speeds):

    dec = Decoder(emit, speed=4410, folder=Path(...))   # the engine's decoder
    dec.feed(audio, t)    # 12 kHz SSB audio, the signal centred at 1500 Hz
    -> emit({"mode": "hsmodem", "kind": "file_start" | "file_progress" | "image"
             | "bulletin" | "file" | "station" | "stats" | ...})
    audio = Encoder().render(name=..., data=... | text=..., speed=4410, callsign=...)
    plan(name, data, speed=...) -> {"frames", "seconds", "bytes", "ftype"}

A transmission follows HSmodem's own (hsmodem.cpp, the GUI's ArraySend.cs):
the file's first frame sent and then repeated while the transmitter was
idle (about six seconds: the preamble every receiver locks on), two
frames of station information (type 7: call, locator, name), each further
frame once, and the last one five times more.

Send (the simulator's beacon): `file_payloads`, `dx_payload`,
`spectrum_payload`, `cw_payload` and `Packer`-style framing through ohsdigi.
"""
from __future__ import annotations

import importlib
import io
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np

from ..i18n.text import _

log = logging.getLogger("ohscore.hsmodem")

PAYLOAD = 219
HEADER = 55              # file header: 50 name, 2 ID, 3 size
FIRST_DATA = PAYLOAD - HEADER   # 164 bytes of the file in its first frame

T_IMAGE, T_ASCII, T_HTML, T_BINARY, T_AUDIO, T_USER, T_EXT = 2, 3, 4, 5, 6, 7, 8
FILE_TYPES = (T_IMAGE, T_ASCII, T_HTML, T_BINARY)
S_FIRST, S_NEXT, S_LAST, S_SINGLE = 0, 1, 2, 3
X_DX, X_NBSPEC, X_CW, X_WBSPEC, X_GENERIC = 0, 1, 2, 3, 25

# The beacon's spectra (extdata.cpp). NB: 275 6-bit values, 2 kHz apart; the
# code puts the first at 10489.475 MHz (its comment elsewhere says 10489.525:
# [unverified]). WB: 266 values, 30 kHz apart from 10491.500 MHz.
NB_SPEC = {"n": 275, "start": 10_489_475_000.0, "step": 2_000.0}
WB_SPEC = {"n": 266, "start": 10_491_500_000.0, "step": 30_000.0}


# HSmodem's speed modes (hsmodem.cpp sr[]; ohsdigi's speed.rs, which a test
# holds this copy to), by the line speed its GUI names them by: bit/s ->
# (speed mode, constellation, symbols a second). The copy is here so the
# band plan and the UI can describe a speed where ohsdigi is not built.
SPEEDS = {
    1200: (0, "BPSK", 1200.0), 2400: (1, "BPSK", 2400.0),
    3000: (2, "QPSK", 1500.0), 4000: (3, "QPSK", 2000.0), 4410: (4, "QPSK", 2205.0), 4800: (5, "QPSK", 2400.0),
    5500: (6, "8APSK", 1837.5), 6000: (7, "8APSK", 2000.0), 6600: (8, "8APSK", 2205.0), 7200: (9, "8APSK", 2400.0),
}
# HSmodem's GUI calls 4410 bit/s QPSK the "QO-100 Standard" and starts on it
# (oscardata Form1.Designer.cs): what a station on the air is most likely
# set to, and 2.42 kHz wide by NB's measure, inside the 2.7 kHz limit.
DEFAULT_SPEED = 4410
CENTRE = 1500.0         # HSmodem's audio centre (liquid_if.cpp FREQUENCY)
AUDIO_RATE = 12_000.0   # the engine's audio rate, both ways
BITS = {"BPSK": 1, "QPSK": 2, "8APSK": 3}
FRAME_BYTES = 258


def speed_info(bps: int) -> dict:
    """What the UI and the guide say about a speed."""
    mode, scheme, baud = SPEEDS[int(bps)]
    return {"bps": int(bps), "mode": mode, "scheme": scheme, "baud": baud,
            "net": baud * BITS[scheme] * PAYLOAD / FRAME_BYTES}


def idle_repetitions(bps: int) -> int:
    """modem_sendPSKData(): how often a first frame is repeated when the
    transmitter was idle - `6 * ((caprate / txinterpolfactor) * bits / 8)
    / 258 + 1`, about six seconds of frames, in its integer arithmetic."""
    _mode, scheme, baud = SPEEDS[int(bps)]
    return 6 * (int(baud) * BITS[scheme] // 8) // FRAME_BYTES + 1


def _load_ohsdigi():
    """ohscore.ohsdigi with HSmodem in it, or None and why not."""
    try:
        m = importlib.import_module(".ohsdigi", __package__.rpartition(".")[0])
    except ImportError as exc:
        return None, f"ohsdigi is not built ({exc})"
    if not hasattr(m, "HsReceiver"):
        return None, "this ohsdigi predates HSmodem (rebuild it: tools/build-ohsdigi.sh)"
    return m, ""


OHSDIGI, WHY_NOT = _load_ohsdigi()
AVAILABLE = OHSDIGI is not None


def crc16(data: bytes) -> int:
    """HSmodem's CRC-16 (reflected 0x8408, init 0xFFFF, no final XOR) - the
    file ID. ohsdigi has it; this copy keeps the content layer usable without."""
    if OHSDIGI is not None:
        return int(OHSDIGI.hs_crc16(bytes(data)))
    reg = 0xFFFF
    for b in data:
        for _ in range(8):
            reg = (reg >> 1) ^ 0x8408 if (reg ^ b) & 1 else reg >> 1
            b >>= 1
    return reg


# ------------------------------------------------------------------ 6-bit packing

def unpack6(data: bytes, n: int) -> np.ndarray:
    """extdata.cpp handleNBSpecData/handleWBSpecData: 6-bit values packed LSB
    first from byte 0 of `data`."""
    bits = np.unpackbits(np.frombuffer(bytes(data), np.uint8), bitorder="little")
    bits = bits[: n * 6]
    if len(bits) < n * 6:
        bits = np.concatenate([bits, np.zeros(n * 6 - len(bits), np.uint8)])
    return (bits.reshape(n, 6) * (1 << np.arange(6))).sum(axis=1).astype(np.uint8)


def pack6(values) -> bytes:
    """The inverse (makeSpecData's bit loop)."""
    v = np.clip(np.asarray(values, int), 0, 63).astype(np.uint8)
    bits = ((v[:, None] >> np.arange(6)) & 1).astype(np.uint8).reshape(-1)
    return np.packbits(bits, bitorder="little").tobytes()


# ------------------------------------------------------------------ payloads (send)

def _pad(b: bytes) -> bytes:
    return bytes(b[:PAYLOAD]).ljust(PAYLOAD, b"\0")


def zip_file(name: str, data: bytes) -> bytes:
    """filesend.cpp zipfile(): one member, named as the file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


def file_payloads(name: str, data: bytes, ftype: int | None = None) -> list[tuple[int, int, bytes]]:
    """filesend.cpp sendFile(): (type, status, payload) for each frame of a
    file. Type from the extension as the beacon chooses it (.jpg image,
    .htm/.html HTML, .blt/.txt ASCII, else binary); all but images are
    zipped first. The header's ID is the CRC-16 of the bytes sent."""
    if ftype is None:
        low = name.lower()
        ftype = (T_HTML if low.endswith((".html", ".htm")) else T_ASCII if low.endswith((".blt", ".txt"))
                 else T_IMAGE if low.endswith(".jpg") else T_BINARY)
    body = data if ftype == T_IMAGE else zip_file(name, data)
    if len(body) > 0xFFFFFF:
        raise ValueError(_("a file is at most 16 MB in HSmodem's 24-bit size field"))
    head = name.encode("latin-1", "replace")[:50].ljust(50, b"\0")
    fid = crc16(body)
    blob = head + bytes([fid >> 8, fid & 0xFF, len(body) >> 16, (len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body
    if len(blob) <= PAYLOAD:
        return [(ftype, S_SINGLE, _pad(blob))]
    n = (len(blob) + PAYLOAD - 1) // PAYLOAD
    if n > 1024:
        raise ValueError(_("a file needs more than HSmodem's 1024 frames"))
    return [(ftype, S_FIRST if i == 0 else S_LAST if i == n - 1 else S_NEXT, _pad(blob[i * PAYLOAD:(i + 1) * PAYLOAD]))
            for i in range(n)]


def dx_payload(reporter: str, qrg_khz: float, dxcall: str, comment: str, utc: str, loc: str = "") -> bytes:
    """ams_extension.cpp FormatAndSendMessage(): byte 0 = 0, byte 1 the
    length of the cluster line it was cut from (a "DX de" line is ~75
    characters; the receiver does not use it), then the fields joined by
    '~' with its truncations."""
    text = "%.20s~%.20s~%.20s~%.40s~%.20s~%.20s" % (reporter, f"{qrg_khz:.1f}", dxcall, comment, utc, loc)
    return _pad(bytes([X_DX, 75]) + text.encode("latin-1", "replace") + b"\0")


def spectrum_payload(kind: int, values) -> bytes:
    """makeSpecData / makeWBSpecData: the stream byte, then 6-bit values."""
    return _pad(bytes([kind]) + pack6(values))


def cw_payload(text: str) -> bytes:
    """A CW-skimmer frame: byte 0 = 2, then the feeding program's bytes. That
    program is not published; plain text is what the simulator sends
    [unverified that the beacon's is plain text]."""
    return _pad(bytes([X_CW]) + text.encode("latin-1", "replace") + b"\0")


# ------------------------------------------------------------------ payloads (receive)

def _cstr(b: bytes) -> str:
    return bytes(b).split(b"\0", 1)[0].decode("latin-1")


def parse_dx(p: bytes) -> dict | None:
    """A DX-cluster frame's fields: reporter, qrg (kHz), dxcall, comment, utc,
    loc. None if it does not have the six fields."""
    f = _cstr(p[2:]).split("~")
    if len(f) != 6:
        return None
    try:
        qrg = float(f[1])
    except ValueError:
        return None
    return {"reporter": f[0].strip().rstrip(":"), "qrg_khz": qrg, "dxcall": f[2].strip(), "comment": f[3].strip(),
            "utc": f[4].strip(), "loc": f[5].strip()}


def printable(b: bytes) -> str:
    s = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in _cstr(b))
    return re.sub(r" {2,}", " ", s).strip()


class FileAssembly:
    """One file being received: blocks by frame counter until all are in."""

    def __init__(self, ftype: int, name: str, fid: int, size: int):
        self.ftype, self.name, self.fid, self.size = ftype, name, fid, size
        self.nblocks = max(1, (size + HEADER + PAYLOAD - 1) // PAYLOAD)
        self.blocks: dict[int, bytes] = {}
        self.t = time.time()

    def add(self, counter: int, payload: bytes) -> None:
        if counter < self.nblocks:
            self.blocks[counter] = bytes(payload)
            self.t = time.time()

    def complete(self) -> bool:
        return len(self.blocks) == self.nblocks

    def data(self) -> bytes | None:
        """The file's bytes (as sent: a ZIP for types 3-5) if every block is
        in and its CRC-16 is the ID, else None."""
        if not self.complete():
            return None
        blob = b"".join(self.blocks[i] for i in range(self.nblocks))[HEADER:HEADER + self.size]
        return blob if crc16(blob) == self.fid else None


def unzip_one(zdata: bytes) -> tuple[str, bytes] | None:
    """A received ZIP: its first member's name (no path) and bytes."""
    try:
        with zipfile.ZipFile(io.BytesIO(zdata)) as z:
            names = z.namelist()
            if not names:
                return None
            return Path(names[0]).name, z.read(names[0])
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        log.info("hsmodem: a received ZIP did not open: %s", exc)
        return None


_SAFE = re.compile(r"[^A-Za-z0-9._ -]")


def safe_name(name: str) -> str:
    """A received file name made safe to write: no path, no odd characters."""
    base = Path(name.replace("\\", "/")).name.strip() or "unnamed"
    base = _SAFE.sub("_", base)
    return base[:80] if not base.startswith(".") else "_" + base[:79]


class Content:
    """Frames in, events out: files assembled (and saved when a folder is
    given), streams decoded. `emit` gets dicts with "mode": `tag` ("mmb"
    for the beacon, "hsmodem" for a station). `keep_both`: a received file
    whose name is already in the folder with other contents is saved as
    name-2, name-3 ... rather than over it (stations send what they like;
    the beacon's bulletins replace themselves)."""

    KEEP_PARTIAL = 1800.0       # an incomplete file is kept this long (s) for the next repeat

    def __init__(self, emit: Callable[[dict], None], folder: Path | None = None, tag: str = "mmb",
                 keep_both: bool = False):
        self.emit = emit
        self.tag = tag
        self.keep_both = keep_both
        self.folder = Path(folder) if folder else None
        self.current: FileAssembly | None = None
        self.partial: dict[tuple, FileAssembly] = {}
        self.done: set[tuple] = set()
        self.last_ext: dict[int, bytes] = {}

    def frame(self, f: dict) -> None:
        t = int(f["type"])
        p = bytes(f["payload"])
        if t == T_EXT:
            self._ext(p)
        elif t in FILE_TYPES:
            self._file(t, int(f["status"]), int(f["counter"]), p)
        elif t == T_USER:
            self.emit({"mode": self.tag, "kind": "station", "call": printable(p[:20]), "loc": printable(p[20:30]),
                       "name": printable(p[30:50])})

    # -- streams -----------------------------------------------------------
    def _ext(self, p: bytes) -> None:
        kind = p[0]
        if kind in (X_DX, X_CW):
            # ext_modemRX: a DX or CW frame identical to the last one is a
            # repeat, not news.
            if self.last_ext.get(kind) == p:
                return
            self.last_ext[kind] = p
        if kind == X_DX:
            d = parse_dx(p)
            if d is not None:
                self.emit({"mode": self.tag, "kind": "dx", **d})
        elif kind == X_CW:
            text = printable(p[1:])
            if text:
                self.emit({"mode": self.tag, "kind": "cw", "text": text})
        elif kind == X_NBSPEC:
            self.emit({"mode": self.tag, "kind": "nbspec", "values": unpack6(p[1:], NB_SPEC["n"]),
                       "start": NB_SPEC["start"], "step": NB_SPEC["step"]})
        elif kind == X_WBSPEC:
            self.emit({"mode": self.tag, "kind": "wbspec", "values": unpack6(p[1:], WB_SPEC["n"]),
                       "start": WB_SPEC["start"], "step": WB_SPEC["step"]})

    # -- files -------------------------------------------------------------
    def _file(self, t: int, status: int, counter: int, p: bytes) -> None:
        now = time.time()
        for k in [k for k, a in self.partial.items() if now - a.t > self.KEEP_PARTIAL]:
            del self.partial[k]
        if status in (S_FIRST, S_SINGLE):
            name = _cstr(p[:50])
            fid = (p[50] << 8) | p[51]
            size = (p[52] << 16) | (p[53] << 8) | p[54]
            key = (t, name, fid, size)
            if key in self.done:
                # Already have it: a repeat of a file we kept.
                self.current = None
                self.emit({"mode": self.tag, "kind": "repeat", "name": name, "ftype": t})
                return
            a = self.partial.get(key)
            if a is None:
                a = self.partial[key] = FileAssembly(t, name, fid, size)
                self.emit({"mode": self.tag, "kind": "file_start", "name": name, "ftype": t, "size": size,
                           "blocks": a.nblocks})
            self.current = a
            a.add(0, p)
        else:
            a = self.current
            if a is None or a.ftype != t:
                return          # its first frame was missed: nothing says which file this is
            a.add(counter, p)
        a = self.current
        if a is None:
            return
        self.emit({"mode": self.tag, "kind": "file_progress", "name": a.name, "have": len(a.blocks),
                   "blocks": a.nblocks})
        if a.complete() or status in (S_LAST, S_SINGLE):
            data = a.data()
            if data is None:
                if a.complete():
                    # Every block in but the CRC disagrees: start over on the
                    # next repeat rather than keep a block that is wrong.
                    self.partial.pop((a.ftype, a.name, a.fid, a.size), None)
                    self.emit({"mode": self.tag, "kind": "file_bad", "name": a.name})
                return
            self.partial.pop((a.ftype, a.name, a.fid, a.size), None)
            self.done.add((a.ftype, a.name, a.fid, a.size))
            self.current = None
            self._deliver(a, data)

    def _deliver(self, a: FileAssembly, data: bytes) -> None:
        name, body = a.name, data
        if a.ftype != T_IMAGE:
            got = unzip_one(data)
            if got is None:
                self.emit({"mode": self.tag, "kind": "file_bad", "name": a.name})
                return
            name, body = got
        path = None
        if self.folder is not None:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                path = self.folder / safe_name(name)
                if self.keep_both:
                    path = _free_path(path, body)
                path.write_bytes(body)
            except OSError as exc:
                log.warning("hsmodem: could not save %s: %s", name, exc)
                path = None
        ev = {"mode": self.tag, "name": name, "data": body, "path": str(path) if path else "", "ftype": a.ftype}
        low = name.lower()
        if a.ftype == T_IMAGE:
            ev["kind"] = "image"
        elif low.endswith((".blt", ".txt")) or a.ftype == T_ASCII:
            ev["kind"] = "bulletin"
            ev["text"] = body.decode("utf-8", "replace") if _looks_utf8(body) else body.decode("latin-1")
        else:
            ev["kind"] = "file"
        self.emit(ev)


def _free_path(path: Path, body: bytes) -> Path:
    """`path`, or name-2.ext, name-3.ext ... - the first that is free or
    already holds exactly `body` (a file received twice is one file)."""
    k = 1
    p = path
    while p.exists():
        try:
            if p.read_bytes() == body:
                return p
        except OSError:
            pass
        k += 1
        p = path.with_name(f"{path.stem}-{k}{path.suffix}")
    return p


def _looks_utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


class BeaconReceiver:
    """ohsdigi's HSmodem receiver on complex baseband, with the content layer
    above it and decode quality reported as events of kind "stats" (about
    once a second of signal)."""

    def __init__(self, rate: float, emit: Callable[[dict], None], folder: Path | None = None, afc: bool = True):
        if OHSDIGI is None:
            raise RuntimeError(WHY_NOT)
        self.rate = float(rate)
        self.rx = OHSDIGI.HsReceiver(self.rate, afc=afc)
        self.emit = emit
        self.content = Content(emit, folder)
        self.samples = 0
        self.next_stats = 0
        self.last_frame_t = 0.0

    def feed_iq(self, iq: np.ndarray, t: float | None = None) -> None:
        x = np.ascontiguousarray(iq, np.complex64)
        frames = self.rx.feed(x.tobytes())
        self.samples += len(x)
        now = time.time() if t is None else t
        for f in frames:
            self.last_frame_t = now
            self.emit({"mode": "mmb", "kind": "frame", "type": int(f["type"]), "counter": int(f["counter"]),
                       "corrected": int(f["corrected"])})
            try:
                self.content.frame(f)
            except Exception:  # noqa: BLE001 - a malformed payload must not stop the receiver
                log.exception("hsmodem: content of a frame could not be read")
        if self.samples >= self.next_stats:
            self.next_stats = self.samples + int(self.rate)
            s = self.rx.stats()
            self.emit({"mode": "mmb", "kind": "stats", "mer": round(float(s["mer_db"]), 1),
                       "ok": int(s["frames_ok"]), "failed": int(s["frames_lost"]),
                       "sync": bool(s["in_sync"]), "freq": round(float(s["freq_hz"]), 1),
                       "last": self.last_frame_t, "resets": int(s["resets"])})


def beacon_frames(items: list[tuple[int, int, bytes]]) -> bytes:
    """(type, status, payload) list -> 258-byte frames with HSmodem's
    counter rules (ohsdigi's Packer)."""
    if OHSDIGI is None:
        raise RuntimeError(WHY_NOT)
    pk = OHSDIGI.HsPacker()
    return b"".join(pk.pack(p, t, s, t == T_EXT) for t, s, p in items)


# ------------------------------------------------------------------ station to station

def station_payload(call: str, locator: str = "", name: str = "") -> bytes:
    """hsmodem.cpp sendStationInfo(): call (20 bytes), locator (10), name
    (20), NUL padded - what Content reads back as kind "station"."""
    def field(v: str, n: int) -> bytes:
        return v.encode("latin-1", "replace")[:n].ljust(n, b"\0")
    return _pad(field(call.upper(), 20) + field(locator, 10) + field(name, 20))


def file_type(name: str) -> int:
    """The frame type a file goes as: HSmodem's GUI sends a picture as an
    image (a JPEG, type 2), text as ASCII (3), .htm/.html as HTML (4) and
    anything else as binary (5) - the beacon's rule (filesend.cpp)."""
    low = name.lower()
    if low.endswith((".jpg", ".jpeg")):
        return T_IMAGE
    if low.endswith((".html", ".htm")):
        return T_HTML
    if low.endswith((".txt", ".blt")):
        return T_ASCII
    return T_BINARY


def transmission_items(items: list[tuple[int, int, bytes]], bps: int, call: str = "", locator: str = "",
                       name: str = "") -> list[tuple[int, int, bytes, bool]]:
    """One file's frames as HSmodem puts them on the air, (type, status,
    payload, repeat): hsmodem.cpp's handling of what the GUI hands it.

    - The first (or only) frame: modem_sendPSKData(..., repeat=5) with the
      transmitter idle, so once and then idle_repetitions() more - about six
      seconds of the same frame, the preamble a receiver's loops settle on
      (and a later frame cannot be missed for want of lock). Then
      sendStationInfo(): type 7, status 1, as a repeat, twice.
    - A middle frame: once.
    - The last frame: once and five more (repeat=5 while playing).
    Pack()'s counter rules (ohsdigi's Packer) number them: the repeats keep
    the counter of the frame they repeat."""
    out: list[tuple[int, int, bytes, bool]] = []
    for t, st, p in items:
        if st in (S_FIRST, S_SINGLE):
            out.append((t, st, p, False))
            out += [(t, st, p, True)] * idle_repetitions(bps)
            if call:
                out += [(T_USER, 1, station_payload(call, locator, name), True)] * 2
        elif st == S_LAST:
            out.append((t, st, p, False))
            out += [(t, st, p, True)] * 5
        else:
            out.append((t, st, p, False))
    return out


def transmission_frames(items, bps: int, call: str = "", locator: str = "", name: str = "") -> bytes:
    """transmission_items() packed: 258-byte frames back to back."""
    if OHSDIGI is None:
        raise RuntimeError(WHY_NOT)
    pk = OHSDIGI.HsPacker()
    return b"".join(pk.pack(p, t, s, r) for t, s, p, r in transmission_items(items, bps, call, locator, name))


def message_of(name: str | None = None, data: bytes | None = None, text: str | None = None,
               ftype: int | None = None) -> tuple[str, bytes, int]:
    """(name, bytes, frame type) for a file, a picture or typed text. Text
    goes as HSmodem's GUI sends a text file: ASCII, named message.txt."""
    if text is not None and data is None:
        if not text.strip():
            raise ValueError(_("Nothing to send: the text is empty"))
        return (name or "message.txt"), text.encode("utf-8"), T_ASCII
    if not name or data is None:
        raise ValueError(_("Nothing to send: choose a file or a picture, or type some text"))
    return name, bytes(data), (file_type(name) if ftype is None else int(ftype))


def plan(name: str | None = None, data: bytes | None = None, text: str | None = None, ftype: int | None = None,
         speed: int = DEFAULT_SPEED, call: str = "x") -> dict:
    """What sending this would take: frames on the air, seconds, the bytes
    actually sent (a ZIP for all but pictures), the frame type."""
    name, body, t = message_of(name, data, text, ftype)
    items = file_payloads(name, body, t)
    n = len(transmission_items(items, speed, call))
    _mode, scheme, baud = SPEEDS[int(speed)]
    sent = len(body) if t == T_IMAGE else len(zip_file(name, body))
    return {"frames": n, "seconds": n * FRAME_BYTES * 8 / (baud * BITS[scheme]), "bytes": sent, "ftype": t,
            "name": name, "size": len(body)}


class Encoder:
    """The "hsmodem" mode's transmitter: a file, a picture or text to the
    engine's 12 kHz audio, the signal centred at 1500 Hz - where HSmodem
    puts it, so an HSmodem station on the same dial hears it where it
    expects (ohsdigi's ssb_audio: HSmodem's own RRC pulse, resampled)."""

    def render(self, name: str | None = None, data: bytes | None = None, text: str | None = None,
               ftype: int | None = None, speed: int = DEFAULT_SPEED, callsign: str = "", locator: str = "",
               opname: str = "", **_opts) -> np.ndarray:
        if OHSDIGI is None:
            raise RuntimeError(WHY_NOT)
        if int(speed) not in SPEEDS:
            raise ValueError(_("HSmodem has no {speed} bit/s speed").format(speed=speed))
        name, body, t = message_of(name, data, text, ftype)
        frames = transmission_frames(file_payloads(name, body, t), int(speed), callsign, locator, opname)
        mode = SPEEDS[int(speed)][0]
        # No lead-in of silence: HSmodem sends none, and its receiver, given
        # a clean signal after digital silence, locked only after its 5 s
        # watchdog (rust/ohsdigi/harness/hsmodem/compare.py speeds).
        a = OHSDIGI.hs_ssb_audio(frames, mode, AUDIO_RATE, CENTRE, 0.85, 0, 8)
        return np.frombuffer(a, np.float32).copy()


class Decoder:
    """The "hsmodem" mode's receiver, fed the engine's 12 kHz audio: ohsdigi's
    receiver at `speed` (its SSB path: mix from 1500 Hz, filter, resample,
    the coarse frequency search), the content layer above it saving files
    to `folder`. Events carry "mode": "hsmodem"; about once a second of
    audio a "stats" event says how decoding goes."""

    def __init__(self, emit: Callable[[dict], None], speed: int = DEFAULT_SPEED, folder: str | Path | None = None,
                 **_opts):
        if OHSDIGI is None:
            raise RuntimeError(WHY_NOT)
        self.speed = int(speed) if int(speed) in SPEEDS else DEFAULT_SPEED
        self.emit = emit
        self.rx = OHSDIGI.HsReceiver(AUDIO_RATE, ssb=True, centre=CENTRE, speed=SPEEDS[self.speed][0])
        self.content = Content(emit, Path(folder) if folder else None, tag="hsmodem", keep_both=True)
        self.samples = 0
        self.next_stats = 0
        self.last_frame_t = 0.0
        self.name = "hsmodem"

    def feed(self, audio: np.ndarray, t: float | None = None) -> None:
        a = np.ascontiguousarray(audio, np.float32)
        frames = self.rx.feed(a.tobytes())
        self.samples += len(a)
        now = time.time() if t is None else float(t)
        for f in frames:
            self.last_frame_t = now
            try:
                self.content.frame(f)
            except Exception:  # noqa: BLE001 - a malformed payload must not stop the receiver
                log.exception("hsmodem: content of a frame could not be read")
        if self.samples >= self.next_stats:
            self.next_stats = self.samples + int(AUDIO_RATE)
            s = self.rx.stats()
            self.emit({"mode": "hsmodem", "kind": "stats", "speed": self.speed, "mer": round(float(s["mer_db"]), 1),
                       "ok": int(s["frames_ok"]), "failed": int(s["frames_lost"]), "sync": bool(s["in_sync"]),
                       "freq": round(float(s["freq_hz"]), 1), "last": self.last_frame_t})
