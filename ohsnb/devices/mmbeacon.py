"""The simulator's multimedia beacon: a real HSmodem signal with realistic
content, so NB's beacon view can be built, shown and tested end to end with
no dish.

It is made the way AMSAT-DL's beacon makes it (docs/hsmodem-research.md):
files sent one after another and the streams beside them, the five queues
served round robin a frame at a time (distrubution.cpp) - here bulletins
(.blt, zipped, type 3), a picture (.jpg, type 2), DX-cluster spots and
CW-skimmer lines (type 8, streams 0 and 2) and NB/WB spectra (streams 1
and 3) - framed by ohsdigi's port of HSmodem and modulated at 2400 Bd,
RRC 0.2, 12 kHz. The template is one period of a periodic signal (the
frames twice through the filter, the second pass kept), so the
simulator's loop has no seam.

Everything it says is the simulator's own: the bulletins say so, the spots
are the simulated band's stations, the spectra are drawn from the band
plan. Where ohsdigi is not built the old random-symbol stand-in
(simsignals.apsk_beacon) is used, so the band still looks right.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.modes import hsmodem

from .. import bandplan

TESTCARD = Path(__file__).with_name("mmb-testcard.jpg")

BULLETINS = {
    "amsat_1.blt": (
        "OPENHAMSHACK NB SIMULATOR - SAMPLE BULLETIN 1\n"
        "This text is sent by OpenHamShack QO-100 NB's own simulator to show the multimedia\n"
        "beacon view working. It is not an AMSAT-DL bulletin.\n\n"
        "QO-100 narrowband transponder: 10489.500 - 10490.000 MHz down,\n"
        "2400.000 - 2400.500 MHz up. Lower beacon 10489.500 (CW), middle\n"
        "beacon 10489.750 (400 bit/s BPSK), multimedia beacon 10489.995\n"
        "(8APSK, 7200 bit/s), upper beacon 10490.000.\n"
        "Keep your downlink below the beacon level.\n"),
    "amsat_2.blt": (
        "OPENHAMSHACK NB SIMULATOR - SAMPLE BULLETIN 2\n"
        "Simulated content, not from AMSAT-DL.\n\n"
        "Band plan reminder: CW 10489.505-540, narrow digimodes 540-580,\n"
        "digimodes up to 2.7 kHz 580-650, SSB 650-745 and 755-850,\n"
        "emergency 10489.860, mixed modes and contests 865-990.\n"),
}


def _utc(t: float) -> str:
    return time.strftime("%H%MZ", time.gmtime(t))


def dx_spots(rng: np.random.Generator, t: float) -> list[bytes]:
    """Spots of the simulated band's own kind of traffic, plus HF ones (the
    beacon relays a whole cluster, not only QO-100)."""
    calls = ["G4XYZ", "DL1ABC", "EA4QRP", "F5KLM", "OH8ZZ", "PA3QOS", "ON4BB", "SV1QO", "OE3ABC", "HB9QQ",
             "GM4SAT", "CT1QO", "LA9NB", "EI7ABC"]
    spots = [
        (10_489_525.0, "CW"), (10_489_540.0, "FT8"), (10_489_568.5, "PSK31"), (10_489_596.0, "RTTY"),
        (10_489_700.0, "SSB"), (10_489_800.0, "SSB"), (10_489_640.0, "FreeDV"), (10_489_910.0, "contest"),
        (14_074.0, "FT8"), (7_012.5, "CW"), (21_295.0, "SSB"), (50_313.0, "FT8"),
    ]
    out = []
    for i, (qrg, what) in enumerate(spots):
        rep, dx = rng.choice(calls, 2, replace=False)
        out.append(hsmodem.dx_payload(f"{rep}-#" if i % 3 == 0 else str(rep), qrg, str(dx),
                                      f"{what} via QO-100 sim" if qrg > 10e6 else f"{what} sim spot",
                                      _utc(t - 60 * (len(spots) - i)), "JO31"))
    return out


def cw_lines(rng: np.random.Generator, t: float) -> list[bytes]:
    calls = ["DL1ABC", "G4XYZ", "F5KLM", "OH8ZZ"]
    return [hsmodem.cw_payload(f"{10489520.0 + 3 * i:.1f} {c} {int(rng.integers(8, 30))} dB "
                               f"{int(rng.integers(16, 28))} WPM CQ {_utc(t)}") for i, c in enumerate(calls)]


def nb_spectrum(rng: np.random.Generator) -> np.ndarray:
    """275 values, 2 kHz apart from 10489.475 MHz, scaled so the lower
    beacon is 63 (extdata.cpp makeSpecData)."""
    n, start, step = hsmodem.NB_SPEC["n"], hsmodem.NB_SPEC["start"], hsmodem.NB_SPEC["step"]
    f = start + step * np.arange(n)
    v = 8 + rng.integers(0, 3, n).astype(float)
    inside = (f >= bandplan.DL_LO) & (f <= bandplan.DL_HI)
    v[inside] += 6
    for key, lvl in (("lower", 63), ("middle", 60), ("mm", 55), ("upper", 58)):
        v[int(round((bandplan.BEACONS[key]["dl"] - start) / step))] = lvl
    for _ in range(int(rng.integers(12, 25))):
        k = int(rng.integers(20, 255))
        v[k] = max(v[k], float(rng.integers(20, 45)))
    return np.clip(v, 0, 63)


def wb_spectrum(rng: np.random.Generator) -> np.ndarray:
    """266 values, 30 kHz apart from 10491.500 MHz (makeWBSpecData): the WB
    transponder's beacon at the left, a few DATV carriers."""
    n = hsmodem.WB_SPEC["n"]
    v = 6 + rng.integers(0, 3, n).astype(float)
    v[:17] = 63                                       # the WB beacon, 0.5 MHz wide
    for c, w in ((60, 8), (120, 4), (180, 12), (230, 3)):
        v[c - w:c + w] = np.maximum(v[c - w:c + w], 30 + rng.integers(0, 10))
    return np.clip(v, 0, 63)


def schedule(rng: np.random.Generator, t: float | None = None) -> list[tuple[int, int, bytes]]:
    """One loop of the beacon: (type, status, payload) in sending order."""
    t = time.time() if t is None else t
    files: list[tuple[int, int, bytes]] = []
    for name, text in BULLETINS.items():
        files += hsmodem.file_payloads(name, text.encode("ascii"))
    if TESTCARD.exists():
        files += hsmodem.file_payloads("testcard.jpg", TESTCARD.read_bytes())
    ext = [(hsmodem.T_EXT, hsmodem.S_SINGLE, p) for pair in zip(dx_spots(rng, t), cw_lines(rng, t) * 3)
           for p in pair]
    queues = {"ext": ext, "files": files}
    out: list[tuple[int, int, bytes]] = []
    k = 0
    # distrubution.cpp: GUI, external (DX/CW), NB spectrum, WB spectrum,
    # files, one frame each in turn. The spectra are always ready on the
    # beacon (a new one every 250 ms), so they take every turn they get.
    while queues["files"] or queues["ext"]:
        turn = k % 4
        k += 1
        if turn == 0 and queues["ext"]:
            out.append(queues["ext"].pop(0))
        elif turn == 1:
            out.append((hsmodem.T_EXT, hsmodem.S_SINGLE, hsmodem.spectrum_payload(hsmodem.X_NBSPEC, nb_spectrum(rng))))
        elif turn == 2:
            out.append((hsmodem.T_EXT, hsmodem.S_SINGLE, hsmodem.spectrum_payload(hsmodem.X_WBSPEC, wb_spectrum(rng))))
        elif turn == 3 and queues["files"]:
            out.append(queues["files"].pop(0))
    return out


def template(rng: np.random.Generator) -> np.ndarray:
    """The beacon's 12 kHz complex baseband loop, RMS 1.

    The stand-in is drawn from `rng` either way and then, with ohsdigi,
    discarded: the simulator's generator then gives every station after
    the beacon exactly what it gave before the real beacon existed, so a
    seeded band (and every test that seeds one) is unchanged. The real
    beacon's own randomness comes from a generator of its own."""
    standin = sg.apsk_beacon(rng, 10.0)
    if not hsmodem.AVAILABLE:
        return standin
    own = np.random.default_rng(int(np.abs(standin[:4].view(np.uint32)).sum()))
    frames = hsmodem.beacon_frames(schedule(own))
    x = np.frombuffer(hsmodem.OHSDIGI.hs_baseband(frames + frames, 5), np.complex64)
    y = x[len(x) // 2:].copy()
    return (y / np.sqrt(np.mean(np.abs(y) ** 2))).astype(np.complex64)
