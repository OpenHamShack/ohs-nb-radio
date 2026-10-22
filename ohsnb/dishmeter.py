"""Dish alignment: the middle beacon's SNR and the transponder's rise over
the noise, for peaking a dish - and an opt-in phone page with the same.

The engine half (no Qt). Radio.dish_open() / dish_close() / dish_reset()
drive it; the window's half is ohsnb/ui/dishmeter.py. Grown from the
prototype used on Brian's dish on 07/10/2026 (a script that opened the
LibreSDR itself and served a page on port 8099). Decisions:

- **Measured from the engine's own receive stream**, the wideband block
  the wide scope gets (Engine._rx_wide), never by opening the radio: the
  radio is already open, and a second opener would fight it. So it also
  works on an IQ recording, which is how it is tested.
- **The beacon's SNR is beacon lock's own measure** (BeaconTracker's
  _bpsk_snr: the power within +-900 Hz of the beacon, over the noise in
  2.5 kHz), so the big number and the badge's "Beacon SNR" agree. The
  noise is the transponder's own beside the beacon (median over +-12 kHz):
  as a dish comes onto the satellite the beacon rises out of it.
  Where the beacon is: within +-1 kHz of where rxCorr puts it while beacon
  lock is locked, else the strongest 1.8 kHz hump within +-15 kHz of
  there (the prototype's window) - a dish being moved has often lost the
  lock, and the needle must still move. The dialog says which.
- **The transponder's rise** is the median level across the transponder
  (its noise, robust to the stations on it) over the median beside it,
  outside the passband: the satellite's own noise coming up out of the
  receiver's. It needs room beside the band; at 600 kS/s there is little,
  and when there is too little it is not shown rather than guessed.
- **Fixed gain while open** (Radio): an AGC raises the gain as the signal
  falls and lowers it as it rises - the very change being looked for.
- **Smoothed, every quarter second**: power spectra averaged with the one
  before (half each), so a hand on the dish sees it move within half a
  second, without the digits flickering by a dB at every update.
- **The tone** rises with the SNR (TONE_HZ at 0 dB, TONE_PER_DB more per
  dB), the way a satellite finder's does; it replaces the receive audio
  while on, through the app's own audio and volume.
- **The phone page** is off unless asked for, served on a port the
  operator chooses (8099 by default, the prototype's), on every IPv4
  interface so a phone on the same network reaches it - but it answers
  only addresses that are not on the Internet (private, link-local,
  loopback, the 100.64/10 a tailnet or a hotspot uses): "bound to the
  LAN" in the sense that matters, whatever a router forwards. One self-contained page, no external assets (a field
  laptop may have no route out); its tone is the phone's own WebAudio.
  It changes nothing in the radio but the "best" figure.
"""
from __future__ import annotations

import ipaddress
import json
import math
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import bandplan

UPDATE_S = 0.25
BIN_HZ = 150.0                  # about: the FFT is the power of two nearest fs / this
LOCKED_SNAP_HZ = 1_000.0        # how far from where rxCorr puts it the beacon is looked for, locked
SEARCH_HZ = 15_000.0            # ... and not locked
NOISE_HZ = 12_000.0             # the beacon's noise: median over this either side
BEACON_HALF_HZ = 900.0          # BeaconTracker._bpsk_snr's +-900 Hz
USABLE = 0.42                   # of fs from DC: inside the SDR's flat passband
EDGE_HZ = 5_000.0               # kept clear inside and outside the transponder's edges
MIN_FLOOR_BINS = 8
TONE_HZ = 200.0
TONE_PER_DB = 50.0
TONE_MAX_HZ = 1_700.0
TONE_LEVEL = 0.3
AUDIO_RATE = 12_000.0
DEFAULT_PORT = 8099


class DishMeter:
    """Fed the wideband receive stream, block by block (`feed`); every
    UPDATE_S returns {snr, rise, found, offset} - snr and rise in dB or None
    when they cannot be measured, `found` "locked" (where beacon lock has
    it) or "nearby" (the strongest hump near where it should be), offset
    the beacon's distance from where rxCorr puts it, Hz."""

    def __init__(self, fs: float):
        self.fs = float(fs)
        self.nfft = 1 << int(round(math.log2(self.fs / BIN_HZ)))
        self.bin_hz = self.fs / self.nfft
        self.win = np.hanning(self.nfft).astype(np.float32)
        self.freqs = np.fft.fftshift(np.fft.fftfreq(self.nfft, 1 / self.fs))
        self.left = np.zeros(0, np.complex64)
        self.acc = np.zeros(self.nfft)
        self.frames = 0
        self.need = max(1, int(round(UPDATE_S * self.fs / self.nfft)))
        self.avg: np.ndarray | None = None

    def feed(self, x: np.ndarray, beacon_off: float, band: tuple[float, float], locked: bool) -> dict | None:
        """`beacon_off`: where the middle beacon should be, Hz from DC;
        `band`: the transponder's edges, Hz from DC; `locked`: beacon lock
        has the beacon there."""
        z = np.concatenate([self.left, x]) if len(self.left) else x
        k = len(z) // self.nfft
        if k:
            fr = z[:k * self.nfft].reshape(k, self.nfft) * self.win
            self.acc += (np.abs(np.fft.fft(fr, axis=1)) ** 2).sum(axis=0)
            self.frames += k
        self.left = np.array(z[k * self.nfft:], np.complex64)
        if self.frames < self.need:
            return None
        P = np.fft.fftshift(self.acc / self.frames)
        self.acc = np.zeros(self.nfft)
        self.frames = 0
        self.avg = P if self.avg is None else 0.5 * self.avg + 0.5 * P
        return self.measure(self.avg, beacon_off, band, locked)

    def _bins(self, lo: float, hi: float) -> np.ndarray:
        f = self.freqs
        lim = USABLE * self.fs
        return np.flatnonzero((f >= max(lo, -lim)) & (f <= min(hi, lim)))

    def measure(self, P: np.ndarray, beacon_off: float, band: tuple[float, float], locked: bool) -> dict:
        snap = LOCKED_SNAP_HZ if locked else SEARCH_HZ
        out = {"snr": None, "rise": None, "found": "locked" if locked else "nearby", "offset": None}
        half = max(1, int(round(BEACON_HALF_HZ / self.bin_hz)))
        cand = self._bins(beacon_off - snap, beacon_off + snap)
        # DC is 3.5 kHz from the beacon (Radio's RX_CENTRE_DL): an SDR's DC
        # offset there would otherwise be the "strongest hump" nearby. Its
        # own bin and the next either side, filled in from the bins beside
        # them: with rxCorr kHz out the beacon itself can sit on DC, and
        # filling them with the noise put a hole in it that moved where it
        # seemed to be by up to 700 Hz.
        dc = np.flatnonzero(np.abs(self.freqs) <= 1.5 * self.bin_hz)
        if len(dc):
            P = P.copy()
            P[dc] = 0.5 * (P[dc[0] - 2:dc[0]].mean() + P[dc[-1] + 1:dc[-1] + 3].mean())
        if len(cand) > 2 * half:
            # The power within +-900 Hz of each candidate centre, by a running sum.
            box = np.convolve(P, np.ones(2 * half + 1), mode="same")
            c = int(cand[np.argmax(box[cand])])
            fc = float(self.freqs[c])
            near = self._bins(fc - NOISE_HZ, fc + NOISE_HZ)
            near = near[np.abs(near - c) > 2 * half]
            if len(near) >= 16:
                noise = float(np.median(P[near])) + 1e-30
                excess = float(box[c]) - noise * (2 * half + 1)
                # As BeaconTracker._bpsk_snr: the excess over the noise in 2.5 kHz.
                out["snr"] = round(10 * math.log10(max(excess, noise * 1e-3) / (noise * 2500.0 / self.bin_hz)), 1)
                out["offset"] = round(float(self.freqs[c] - beacon_off), 0)
        lo, hi = sorted(band)
        inside = self._bins(lo + EDGE_HZ, hi - EDGE_HZ)
        lim = USABLE * self.fs
        f = self.freqs
        beside = np.flatnonzero(((f < lo - EDGE_HZ) | (f > hi + EDGE_HZ)) & (np.abs(f) <= lim))
        if len(inside) >= MIN_FLOOR_BINS and len(beside) >= MIN_FLOOR_BINS:
            out["rise"] = round(10 * math.log10((float(np.median(P[inside])) + 1e-30)
                                               / (float(np.median(P[beside])) + 1e-30)), 2)
        return out


class Best:
    """The best SNR since the tool opened or `reset()`."""

    def __init__(self):
        self.value: float | None = None
        self.lock = threading.Lock()

    def see(self, snr: float | None) -> float | None:
        with self.lock:
            if snr is not None and (self.value is None or snr > self.value):
                self.value = snr
            return self.value

    def reset(self) -> None:
        with self.lock:
            self.value = None


def tone_hz(snr: float | None) -> float:
    """The tone's pitch for an SNR: TONE_HZ at 0 dB (or nothing measured),
    TONE_PER_DB more per dB, at most TONE_MAX_HZ."""
    s = 0.0 if snr is None else max(0.0, float(snr))
    return min(TONE_MAX_HZ, TONE_HZ + TONE_PER_DB * s)


class Tone:
    """A sine whose pitch glides to `target` across each block, phase-
    continuous, so a changing SNR is heard as a slide, never a click."""

    def __init__(self, rate: float = AUDIO_RATE):
        self.rate = rate
        self.f = TONE_HZ
        self.target = TONE_HZ
        self.phase = 0.0

    def __call__(self, n: int) -> np.ndarray:
        f = np.linspace(self.f, self.target, n, endpoint=False) if n else np.zeros(0)
        ph = self.phase + 2 * np.pi * np.cumsum(f) / self.rate
        self.f = self.target
        if n:
            self.phase = float(ph[-1] % (2 * np.pi))
        return (TONE_LEVEL * np.sin(ph)).astype(np.float32)


# -- the phone page --------------------------------------------------------------
def lan_addresses() -> list[str]:
    """This machine's IPv4 addresses a phone on the same network could
    use: the one the default route leaves by (a UDP "connect" sends
    nothing) and whatever the host name resolves to; not loopback."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))         # TEST-NET-1: never answered, only routed
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    out = []
    for a in found:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if not ip.is_loopback and not ip.is_unspecified and a not in out:
            out.append(a)
    return out


def allowed_client(addr: str) -> bool:
    """Only an address that cannot be on the Internet may read the page."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    # Not "global": private ranges, link-local, loopback - and the
    # 100.64/10 shared range a tailnet or a mobile hotspot hands out.
    return not ip.is_global and not ip.is_multicast


class PhoneServer:
    """The phone page on `port`. `snapshot()` returns the numbers as a dict;
    `reset()` resets the best figure. start() raises OSError (port in use,
    not allowed) with the system's reason; stop() is immediate."""

    def __init__(self, port: int, snapshot, reset):
        self.port = int(port)
        self.snapshot, self.reset = snapshot, reset
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # quiet: a phone polls four times a second
                pass

            def _send(self, code: int, body: bytes, ctype: str):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _allowed(self) -> bool:
                if allowed_client(self.client_address[0]):
                    return True
                self._send(403, b"This page is for the local network only.\n", "text/plain; charset=utf-8")
                return False

            def do_GET(self):
                if not self._allowed():
                    return
                path = self.path.split("?", 1)[0]
                if path == "/s":
                    self._send(200, json.dumps(outer.snapshot()).encode(), "application/json")
                elif path == "/":
                    self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                else:
                    self._send(404, b"Not here.\n", "text/plain; charset=utf-8")

            def do_POST(self):
                if not self._allowed():
                    return
                if self.path.split("?", 1)[0] == "/reset":
                    outer.reset()
                    self._send(200, b"ok\n", "text/plain; charset=utf-8")
                else:
                    self._send(404, b"Not here.\n", "text/plain; charset=utf-8")

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = Server(("0.0.0.0", self.port), Handler)
        self.port = self.httpd.server_address[1]       # 0 asked for: the one given (tests)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ohsnb-dishpage",
                                       kwargs={"poll_interval": 0.2}, daemon=True)
        self.thread.start()

    def urls(self) -> list[str]:
        return [f"http://{a}:{self.port}/" for a in lan_addresses()]

    def stop(self) -> None:
        h, self.httpd = self.httpd, None
        if h is not None:
            h.shutdown()
            h.server_close()


# One self-contained page: no fonts, scripts or images from anywhere else.
# The tone needs a tap first (browsers allow sound only after one).
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dish alignment - OpenHamShack QO-100 NB</title>
<style>
:root{--bg:#0b0d12;--fg:#e8ecf3;--mute:#9aa3b2;--track:#222833;--accent:#2d6cdf}
@media (prefers-color-scheme: light){:root{--bg:#f6f7f9;--fg:#11151c;--mute:#5b6473;--track:#dde1e7}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,sans-serif;text-align:center;
padding:16px;-webkit-user-select:none;user-select:none}
.s{font-size:clamp(14px,5vw,28px);color:var(--mute)}
#snr{font-size:clamp(64px,30vw,240px);font-weight:700;line-height:1;margin:8px 0;font-variant-numeric:tabular-nums}
.bar{height:36px;background:var(--track);border-radius:8px;overflow:hidden;margin:12px 0}
#bar{height:100%;width:0;background:linear-gradient(90deg,#c33,#cc3,#3c6)}
.row{font-size:clamp(18px,7vw,40px);margin:10px 0;font-variant-numeric:tabular-nums}
button{font-size:clamp(16px,5.5vw,30px);padding:14px 26px;border-radius:12px;border:0;background:var(--accent);
color:#fff;margin:8px}
#stale{color:#e55}
</style></head><body>
<div class="s">Middle beacon, dB over the noise</div>
<div id="snr">--</div>
<div class="bar"><div id="bar"></div></div>
<div class="row">best <b id="best">--</b> &nbsp; transponder <b id="rise">--</b></div>
<div class="s" id="where"></div>
<div><button id="tone">Tone on</button><button id="reset">Reset best</button></div>
<div class="s">Pitch rises with the beacon. Normal: 15-20 dB.</div>
<div class="s" id="stale"></div>
<script>
"use strict";
let ctx=null,osc=null,gain=null,on=false,last=0;
const $=id=>document.getElementById(id);
const fmt=(v,d)=>v===null||v===undefined?"--":v.toFixed(d);
$("tone").onclick=()=>{
  if(!ctx){const A=window.AudioContext||window.webkitAudioContext;ctx=new A();osc=ctx.createOscillator();
    gain=ctx.createGain();gain.gain.value=0;osc.connect(gain);gain.connect(ctx.destination);osc.start();}
  ctx.resume();on=!on;gain.gain.setTargetAtTime(on?0.2:0,ctx.currentTime,0.02);
  $("tone").textContent=on?"Tone off":"Tone on";};
$("reset").onclick=()=>fetch("reset",{method:"POST"});
async function tick(){
  try{
    const s=await (await fetch("s",{cache:"no-store"})).json();
    last=Date.now();
    $("snr").textContent=fmt(s.snr,1);
    $("best").textContent=fmt(s.best,1);
    $("rise").textContent=s.rise===null?"--":(s.rise>=0?"+":"")+s.rise.toFixed(1)+" dB";
    $("where").textContent=s.where||"";
    $("bar").style.width=Math.max(0,Math.min(100,(s.snr||0)*4))+"%";
    if(osc)osc.frequency.setTargetAtTime(s.tone,ctx.currentTime,0.05);
    $("stale").textContent=s.open?"":"Dish alignment is closed in OpenHamShack QO-100 NB.";
  }catch(e){}
  if(last&&Date.now()-last>3000)$("stale").textContent="No answer from OpenHamShack QO-100 NB.";
  setTimeout(tick,250);
}
tick();
</script></body></html>
"""
