"""The Canadian amateur licence (ISED, RBR-4 Issue 3): who may transmit
where, at what power.

Source: RBR-4 Issue 3 (July 2022), "Standards for the Operation of Radio
Stations in the Amateur Radio Service", made binding by s.45 of the
Radiocommunication Regulations (SOR/96-484) [R4], with the Canadian Table
of Frequency Allocations 2022 [T22] for status and the footnotes RBR-4
quotes, as transcribed in docs/ham/countries/ca.md (sections 2-8). No newer
issue of RBR-4 was found on 2026-10-08.

Canada has no station licence: a person holding an Amateur Radio Operator
Certificate is exempt from licensing (Regs s.15.3). Privileges reduce to
two independent things, HF access and the power tier, so three classes:

- `ca_basic`: Basic only - every band above 30 MHz, nothing below
  (not even 10 m);
- `ca_basic_hf`: Basic with Honours, or Basic with Morse, or Basic issued
  before 1 April 2002 - every band, Basic power;
- `ca_advanced`: Basic and Advanced - every band, Advanced power.

Power is a transmitter limit, the same on every band (R4 s.10): Basic 560 W
PEP for "any type of single sideband emission", 190 W carrier for any other
emission; Advanced 2250 W PEP and 750 W carrier. Encoded as a Limit per mode
class. Whether a data mode or digital voice sent through an SSB exciter
(J2D, FreeDV) is "single sideband" is, ca.md says (s.3 and s.11 item 4),
an interpretation ISED has not confirmed, and the reading that gives it the
higher PEP figure would raise the power, so data, digital voice and image
are held to the carrier figure; only SSB voice gets the PEP one. The only
radiated limits are 2200 m and 630 m (1 W EIRP each, on top of the
transmitter limit) and 60 m (100 W ERP).

Decisions where the research is unsure (each refuses, never guesses):

- 630 m is 1 W EIRP: RAC's 5 W is not in any ISED text (ca.md s.11 item 1).
- 60 m: the four channels and the 5351.5-5366.5 kHz band, one emission at
  100 W ERP (s.11 item 2), and the transmitter limit as well.
- 220-222 MHz only "in exceptional circumstances ... to assist in disaster
  relief efforts" (C11): refused.
- 5850-5925 MHz: what SMSE-012-22 did to the amateur entry is UNCONFIRMED
  (s.3): the row is marked unconfirmed, so refused.
- Nothing above 250 GHz (RAC's "above 400 GHz" is not in RBR-4).

QO-100 is below the horizon from all of Canada; 2400-2450 MHz is
amateur-satellite (RR 5.282) and every class holds it.
"""
from __future__ import annotations

from . import Limit

ID = "ised-2022"
TITLE = "ISED RBR-4, Standards for the Operation of Radio Stations in the Amateur Radio Service (Issue 3, 2022)"
SHORT = "Canada (ISED)"
AUTHORITY = "ISED"
COUNTRY = ("CA",)
PLAN = ""
# [R4] in docs/ham/countries/ca.md.
SOURCE = {
    "title": "RBR-4, Standards for the Operation of Radio Stations in the Amateur Radio Service",
    "url": "https://ised-isde.canada.ca/site/spectrum-management-telecommunications/sites/default/files/"
           "attachments/2022/RBR-4-i3-2022-07EN.pdf",
    "version": "Issue 3, July 2022 (no day printed; PDF created 2022-08-03); still current per ISED's "
               "publications page of 2025-07-15",
    "date": "2022-07-01",
    "checked": "2026-10-08",
    "sha256": "e805024a0ea5de502169457c101a2f15227837a04b2ee8d4c0e6cd8fd9c5acdd",
}
CLASSES = ("ca_basic", "ca_basic_hf", "ca_advanced")
CLASS_NAME = {"ca_basic": "Basic", "ca_basic_hf": "Basic with Honours or Morse", "ca_advanced": "Advanced"}

_SSB = frozenset({"ssb"})
_OTHER = frozenset({"cw", "am", "fm", "digi", "dv", "image"})
# R4 s.10.2 and s.10.3, p.4: RF output into a matched load.
BASIC = (Limit(560.0, "PEP", _SSB), Limit(190.0, "carrier", _OTHER))
ADVANCED = (Limit(2250.0, "PEP", _SSB), Limit(750.0, "carrier", _OTHER))


def _all(extra=()):
    """Every class (bands above 30 MHz: Basic suffices)."""
    return {"ca_basic": BASIC + extra, "ca_basic_hf": BASIC + extra, "ca_advanced": ADVANCED + extra}


def _hf(extra=()):
    """Below 30 MHz: "B and 5, B/H, B and A" - not Basic alone."""
    return {"ca_basic_hf": BASIC + extra, "ca_advanced": ADVANCED + extra}


def _k(lo_khz, hi_khz, lim, note, src, extras=None):
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


def _m(lo_mhz, hi_mhz, lim, note, src, extras=None):
    return _k(lo_mhz * 1e3, hi_mhz * 1e3, lim, note, src, extras)


_S1 = "RBR-4 Sch. I item {}, p.6"
_S1b = "RBR-4 Sch. I item {}, p.7"
_EIRP1 = (Limit(1.0, "EIRP"),)

# RBR-4 Schedule I (stations in Canada), items 1-40; status from T22.
ALLOCATIONS = [
    _k(135.7, 137.8, _hf(_EIRP1), "2200 m, secondary; 1 W EIRP as well as the transmitter limit (5.67A)",
       "RBR-4 Sch. I item 1, pp.6-7"),
    _k(472, 479, _hf(_EIRP1), "630 m, secondary; 1 W EIRP (5.80A; RAC's 5 W is unconfirmed)",
       "RBR-4 Sch. I item 2, pp.6-7"),
    _k(1800, 2000, _hf(), "160 m, primary", _S1.format(3)),
    _k(3500, 4000, _hf(), "80 m, primary", _S1.format(4)),
    # 60 m (items 5-9) is CHANNELLED below.
    _k(7000, 7300, _hf(), "40 m, primary", _S1.format(10)),
    _k(10100, 10150, _hf(), "30 m (C6: may be required to cease); 1 kHz bandwidth", "RBR-4 Sch. I item 11, p.6, p.8"),
    _k(14000, 14350, _hf(), "20 m, primary", _S1.format(12)),
    _k(18068, 18168, _hf(), "17 m, primary", _S1.format(13)),
    _k(21000, 21450, _hf(), "15 m, primary", _S1.format(14)),
    _k(24890, 24990, _hf(), "12 m, primary", _S1.format(15)),
    _k(28000, 29700, _hf(), "10 m, primary (below 30 MHz: not Basic alone)", _S1.format(16)),
    _m(50, 54, _all(), "6 m, primary", _S1.format(17)),
    _m(144, 148, _all(), "2 m, primary", _S1.format(18)),
    _m(219, 220, _all(), "secondary (C11)", "RBR-4 Sch. I item 19, p.6, p.8"),
    _m(222, 225, _all(), "1.25 m, primary", _S1.format(21)),
    _m(430, 450, _all(), "70 cm, secondary; 12 MHz bandwidth", _S1.format(22)),
    _m(902, 928, _all(), "33 cm, secondary; 12 MHz bandwidth", _S1.format(23)),
    _m(1240, 1300, _all(), "23 cm, secondary", _S1.format(24)),
    _m(2300, 2400, _all(), "13 cm, secondary", _S1.format(25)),
    _m(2400, 2450, _all(), "13 cm, secondary; ISM; amateur-satellite (5.282)", _S1.format(25)),
    _m(3300, 3500, _all(), "9 cm, secondary (3450-3500 MHz is a flexible-use mobile band)", _S1.format(26)),
    _m(5650, 5850, _all(), "5 cm, secondary", _S1.format(27)),
    _m(5850, 5925, _all(), "5 cm, secondary; the effect of SMSE-012-22 on the amateur entry is unconfirmed",
       _S1.format(27) + "; ca.md s.3", {"unconfirmed": True}),
    _m(10000, 10500, _all(), "3 cm, secondary", _S1.format(28)),
    _m(24000, 24050, _all(), "primary", _S1b.format(29)),
    _m(24050, 24250, _all(), "secondary", _S1b.format(30)),
    _m(47000, 47200, _all(), "primary", _S1b.format(31)),
    _m(76000, 81500, _all(), "secondary except 77.5-78 GHz", "RBR-4 Sch. I items 32-35, p.7"),
    _m(122250, 123000, _all(), "secondary", _S1b.format(36)),
    _m(134000, 141000, _all(), "primary to 136 GHz, secondary above", "RBR-4 Sch. I items 37-38, p.7"),
    _m(241000, 250000, _all(), "secondary to 248 GHz, primary above", "RBR-4 Sch. I items 39-40, p.7"),
]

# 60 m [ca.md s.3; R4 items 5-9 and footnote C21, p.8]: four 2.8 kHz
# channels and the 5351.5-5366.5 kHz band, 100 W ERP (PEP), never wider than
# 2.8 kHz. Channel edges are centre +/- 1.4 kHz [derived in ca.md s.3]. The
# transmitter limit applies too; a channel's limits cannot depend on the
# mode, so it is the carrier figure (the stricter) for every mode.
_SIXTY_SRC = "RBR-4 Sch. I items 5-9, p.6, footnote C21 p.8"
_SIXTY_LIM = {"ca_basic_hf": ((100.0, "ERP"), (190.0, "carrier")),
              "ca_advanced": ((100.0, "ERP"), (750.0, "carrier"))}


def _channel(centre_khz):
    lo, hi = (centre_khz - 1.4) * 1e3, (centre_khz + 1.4) * 1e3
    return {"lo": lo, "hi": hi, "label": f"60 m channel {centre_khz:g} kHz",
            "where": f"the 2.8 kHz centred on {centre_khz:g} kHz", "segments": [(lo, hi)],
            "limits": _SIXTY_LIM, "max_bw": 2800.0, "src": _SIXTY_SRC}


CHANNELLED = [
    _channel(5332.0), _channel(5348.0),
    {"lo": 5351.5e3, "hi": 5366.5e3, "label": "60 m (5351.5-5366.5 kHz)", "where": "5351.5-5366.5 kHz",
     "segments": [(5351.5e3, 5366.5e3)], "limits": _SIXTY_LIM, "max_bw": 2800.0, "src": _SIXTY_SRC},
    _channel(5373.0), _channel(5405.0),
]

_SIXTY_GAP = ("In Canada, 60 m may be used only on the channels centred on 5332, 5348, 5373 and 5405 kHz and "
              "in 5351.5-5366.5 kHz (RBR-4 Schedule I, footnote C21).")
REFUSED = [
    (5333.4e3, 5346.6e3, _SIXTY_GAP, "ca.md s.3, gaps"),
    (5349.4e3, 5351.5e3, _SIXTY_GAP, "ca.md s.3, gaps"),
    (5366.5e3, 5371.6e3, _SIXTY_GAP, "ca.md s.3, gaps"),
    (5374.4e3, 5403.6e3, _SIXTY_GAP, "ca.md s.3, gaps"),
    (220e6, 222e6, "220-222 MHz is open to amateurs only in exceptional circumstances, to assist in disaster "
                   "relief (footnote C11), so OpenHamShack does not transmit there.", "RBR-4 Sch. I item 20; ca.md s.3"),
]

# Maximum bandwidth, R4 Sch. I column II (measured 26 dB down, R4 s.4):
# every mode, every class. 23 cm and up: "Not specified".
_EVERY = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})


def _bw(lo_hz, hi_hz, bw_hz, item):
    return (lo_hz, hi_hz, {c: _EVERY for c in CLASSES}, bw_hz, f"RBR-4 maximum bandwidth {bw_hz:g} Hz",
            f"RBR-4 s.4 p.2, Sch. I item {item}")


EMISSIONS = [
    _bw(135.7e3, 137.8e3, 100.0, 1), _bw(472e3, 479e3, 1000.0, 2), _bw(1800e3, 2000e3, 6000.0, 3),
    _bw(3500e3, 4000e3, 6000.0, 4), _bw(7000e3, 7300e3, 6000.0, 10), _bw(10100e3, 10150e3, 1000.0, 11),
    _bw(14000e3, 14350e3, 6000.0, 12), _bw(18068e3, 18168e3, 6000.0, 13), _bw(21000e3, 21450e3, 6000.0, 14),
    _bw(24890e3, 24990e3, 6000.0, 15), _bw(28000e3, 29700e3, 20000.0, 16), _bw(50e6, 54e6, 30000.0, 17),
    _bw(144e6, 148e6, 30000.0, 18), _bw(219e6, 220e6, 100000.0, 19), _bw(222e6, 225e6, 100000.0, 21),
    _bw(430e6, 450e6, 12e6, 22), _bw(902e6, 928e6, 12e6, 23),
]

# The amateur-satellite service in T22 (ca.md s.6), no direction stated
# except 1260-1270 and 5650-5670 MHz, Earth-to-space only (5.282). The
# 5830-5850 MHz downlink in RAC's plan is not in T22: left out.
_T22 = "Canadian Table of Frequency Allocations 2022 (ca.md s.6)"
SATELLITE = [(a * 1e6, b * 1e6, d, _T22 if d == "both" else _T22 + ", RR 5.282") for a, b, d in (
    (7.0, 7.1, "both"), (14.0, 14.25, "both"), (18.068, 18.168, "both"), (21.0, 21.45, "both"),
    (24.89, 24.99, "both"), (28.0, 29.7, "both"), (144, 146, "both"), (435, 438, "both"), (1260, 1270, "up"),
    (2400, 2450, "both"), (3400, 3410, "both"), (5650, 5670, "up"), (10450, 10500, "both"),
    (24000, 24050, "both"), (47000, 47200, "both"), (76000, 81500, "both"), (134000, 141000, "both"),
    (241000, 250000, "both"))]

# CEPT T/R 61-01 (ca.md s.8): a Canadian qualifies with Basic and Advanced
# and the call sign on the certificate; Basic with Honours or Morse alone
# does not. A visitor under T/R 61-01 has Basic and Advanced privileges, never
# beyond the home licence. Canada is not in ECC/REC (05)06.
CEPT = {"T/R 61-01": ("ca_advanced",)}
CEPT_SRC = ("RIC-3 Issue 5 s.8.2.1; CEPT T/R 61-01 (18 Oct 2024) Annex 4 Table 2; RBR-4 s.3.2; "
            "ECC/REC (05)06 (16 Jun 2023) Annex 4")
CEPT_VISITOR = {"T/R 61-01": "ca_advanced"}

NOTES = [
    ("visitors", "A visitor operates with Basic and Advanced privileges, but never beyond those of their own "
                 "licence.", "RBR-4 s.3.2"),
    ("remote", "Holders of Basic may not remote-control a fixed station (RIC-3 policy, which has no status in law; "
               "a relaxation is pending).", "RIC-3 s.4.5.1-4.5.2; ca.md s.6"),
    ("home-built", "Only Advanced holders may install a transmitter or amplifier that is not commercially "
                   "manufactured; how ISED treats an SDR board with a home-built amplifier is not stated.",
     "Regs s.44(a); ca.md s.11 item 5"),
    ("repeater", "A same-band repeater or a club station needs the Advanced qualification.", "Regs s.44(b)"),
    ("amplifier", "An amplifier must not be capable of exceeding the power limit by more than 3 dB.",
     "RBR-4 s.10.1"),
    ("carrier", "Below 30 MHz an unmodulated carrier may be sent only for brief tests.", "RBR-4 s.11"),
    ("identification", "Identify at the beginning and end of each exchange and at least every 30 minutes, in "
                       "English or French.", "RBR-4 s.9"),
    ("60 m", "60 m allows only 2K80J3E, 2K80J2D, 60H0J2B and 150HA1A emissions.", "footnote C21"),
]
