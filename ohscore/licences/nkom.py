"""The Norwegian amateur licence (Nkom): who may transmit where, at what power.

Source: [N1] Forskrift om radioamatørvirksomhet, FOR-2026-03-23-465, in
force 23 March 2026 and not amended since: § 5 (begrenset lisens) and § 5a
(full lisens), as transcribed in docs/ham/countries/no.md section 3. It
replaced the 2009 regulation outright, so anything about Norway older than
April 2026 is about the old law. The research has not had the line-by-line
check the UK's had (docs/ham/licence-check.md).

Every figure is "utgangseffekt fra sender", defined in § 3 i as PEP
measured where the antenna joins the transmitter's final stage; the
exceptions are 1 W EIRP on 2200 m and 630 m (on top of the PEP figure),
10 W mean on 1850-2000 kHz, and 20 mW EIRP on 1258-1296 MHz from 2028. The
maximum bandwidth column is law in Norway, not band-plan advice, and is
EMISSIONS here.

Decisions:
- 23 cm has two tables in § 5a: 1240-1300 MHz at 300 W to 31 December
  2027, then four sub-bands from 1 January 2028. Both are dated rows. Their
  bandwidths differ too (20 MHz now; 18 MHz and 150 kHz from 2028), and
  EMISSIONS have no dates, so the stricter of each applies now: 18 MHz on
  1240-1258 MHz and 150 kHz on 1258-1300 MHz, which also takes the
  research's stricter reading of the 2028 rule for signals wider than
  150 kHz (no.md s.3.1). Wideband (ATV) on 1258-1300 MHz is therefore
  refused before 2028 although the law allows it.
- The 1000 W EME/meteor-scatter allowance (4 m, 2 m, 70 cm, 23 cm) and the
  2028 satellite uplink's elevation-dependent EIRP on 1260-1262 MHz both
  raise power on conditions OpenHamShack cannot see (antenna, logging,
  elevation): not encoded, the ordinary limit applies.
- The regulation does not apply to 2-32 GHz within 20 km of Ny-Ålesund
  (§ 2). As a station condition it would have to default to refusing 13 cm
  to 3 cm for every mainland station, so it is a NOTE instead, and the
  country mapping covers the mainland (LA) only: a Svalbard station gets no
  regime by default.
- 430-432 and 438-440 MHz, and 10.00-10.25 GHz, are not amateur in Norway;
  they are refused with a sentence saying so.
"""
from __future__ import annotations

ID = "nkom-2026"
TITLE = "Norwegian amateur licence (Forskrift om radioamatørvirksomhet 2026)"
SHORT = "Norway (Nkom)"
AUTHORITY = "Nasjonal kommunikasjonsmyndighet (Nkom)"
COUNTRY = ("NO",)
PLAN = ""
SOURCE = {
    "title": "Forskrift om radioamatørvirksomhet, FOR-2026-03-23-465, § 5 and § 5a",
    "url": "https://lovdata.no/dokument/SF/forskrift/2026-03-23-465",
    "version": "Fastsatt 23.03.2026, i kraft 23.03.2026; no amendment on Lovdata at 2026-10-08 "
               "(the sha256 is of the HTML page fetched that day, not of the legal text)",
    "date": "2026-03-23",
    "checked": "2026-10-08",
    "sha256": "c65067ecf826985afb374bf49aa30e56a422075ad656661b72fa687908189791",
}
CLASSES = ("no_begrenset", "no_full")
CLASS_NAME = {"no_begrenset": "Restricted (begrenset)", "no_full": "Full"}

_P, _I, _M = "PEP", "EIRP", "mean"


def _r(lo_khz, hi_khz, b, f, note, src, extras=None):
    """A row in kHz; b and f are begrenset's and full's limits (None: the
    class has no row in its table). A bare number is W PEP."""
    lim = {}
    for cls, v in (("no_begrenset", b), ("no_full", f)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


_B, _F, _BF = "N1 § 5", "N1 § 5a", "N1 § 5, § 5a"
_TO_2027 = {"valid_to": "2027-12-31"}
_FROM_2028 = {"valid_from": "2028-01-01"}

ALLOCATIONS = [
    _r(135.7, 137.8, None, ((200.0, _P), (1.0, _I)), "secondary; 200 W PEP and 1 W EIRP", _F),
    _r(472, 479, None, ((100.0, _P), (1.0, _I)), "secondary; 100 W PEP and 1 W EIRP", _F),
    _r(1810, 1850, None, 1000, "primary", _F),
    _r(1850, 2000, None, (10.0, _M), "secondary; 10 W mean whatever the modulation", _F),
    _r(3500, 3800, 10, 1000, "primary", _BF),
    _r(5260, 5410, None, 100, "secondary; a national block, wider than WRC-15's", _F),
    _r(7000, 7200, 10, 1000, "primary", _BF),
    _r(10100, 10150, None, 1000, "secondary", _F),
    _r(14000, 14350, 10, 1000, "primary", _BF),
    _r(18068, 18168, 10, 1000, "primary", _BF),
    _r(21000, 21450, 10, 1000, "primary", _BF),
    _r(24740, 24890, None, 1000, "secondary; national extension below 12 m", _F),
    _r(24890, 24990, None, 1000, "primary", _F),
    _r(28000, 29700, 10, 1000, "primary", _BF),
    _r(50000, 52000, 10, 1000, "primary", _BF),
    _r(69900, 70500, None, 100, "secondary (1000 W EME/MS on conditions, not encoded)", _F),
    _r(144000, 146000, 10, 300, "primary (1000 W EME/MS on conditions, not encoded)", _BF),
    _r(432000, 438000, 10, 300, "primary (1000 W EME/MS on conditions, not encoded)", _BF),
    _r(1240000, 1300000, None, 300, "secondary, to 31 Dec 2027 (1000 W EME/MS on conditions, not encoded)", _F,
       _TO_2027),
    _r(1240000, 1258000, None, 300, "secondary, from 1 Jan 2028", _F, _FROM_2028),
    _r(1258000, 1296000, None, (0.02, _I), "secondary, from 1 Jan 2028; 0.02 W EIRP", _F, _FROM_2028),
    _r(1296000, 1298000, None, 50, "secondary, from 1 Jan 2028", _F, _FROM_2028),
    _r(1298000, 1300000, None, 158, "secondary, from 1 Jan 2028 (EME 500 W on conditions, not encoded)", _F,
       _FROM_2028),
    _r(2300000, 2450000, 5, 100, "secondary", _BF),
    _r(3400000, 3410000, None, 100, "secondary", _F),
    _r(5650000, 5850000, None, 100, "secondary", _F),
    _r(10250000, 10500000, 1, 100, "secondary", _BF),
]

# The "Tillatt maksimal båndbredde" column of § 5 and § 5a (no.md s.3). A
# class not in a row has no allocation there. Every mode class is allowed:
# the law limits width, not mode.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})


def _em(lo_khz, hi_khz, bw_hz, classes, src, note=""):
    return (lo_khz * 1e3, hi_khz * 1e3, {c: _ALL for c in classes}, float(bw_hz), note, src)


_BOTH, _FULL = ("no_begrenset", "no_full"), ("no_full",)
EMISSIONS = [
    _em(135.7, 137.8, 1000, _FULL, _F),
    _em(472, 479, 1000, _FULL, _F),
    _em(1810, 2000, 6000, _FULL, _F),
    _em(3500, 3800, 6000, _BOTH, _BF),
    _em(5260, 5410, 6000, _FULL, _F),
    _em(7000, 7200, 6000, _BOTH, _BF),
    _em(10100, 10150, 1000, _FULL, _F),
    _em(14000, 14350, 6000, _BOTH, _BF),
    _em(18068, 18168, 6000, _BOTH, _BF),
    _em(21000, 21450, 6000, _BOTH, _BF),
    _em(24740, 24990, 6000, _FULL, _F),
    _em(28000, 29700, 18000, _BOTH, _BF),
    _em(50000, 52000, 18000, _BOTH, _BF),
    _em(69900, 70500, 18000, _FULL, _F),
    _em(144000, 146000, 18000, _BOTH, _BF),
    _em(432000, 433600, 30000, _BOTH, _BF),
    _em(433600, 434000, 200000, _BOTH, _BF, "200 kHz is allowed in 433.6-434.0 MHz"),
    _em(434000, 438000, 30000, _BOTH, _BF),
    # The stricter of the two 23 cm tables' widths (see the docstring).
    _em(1240000, 1258000, 18e6, _FULL, _F, "18 MHz from 2028; 20 MHz to 2027 (stricter applied)"),
    _em(1258000, 1300000, 150e3, _FULL, _F, "150 kHz from 2028; 20 MHz to 2027 (stricter applied)"),
    _em(2300000, 2450000, 20e6, _BOTH, _BF),
    _em(3400000, 3410000, 7e6, _FULL, _F),
    _em(5650000, 5850000, 20e6, _FULL, _F),
    _em(10250000, 10500000, 50e6, _BOTH, _BF),
]

_GAP = "no.md s.3.2"
REFUSED = [
    (430e6, 432e6, "430-432 MHz is not an amateur band in Norway", _GAP),
    (438e6, 440e6, "438-440 MHz is not an amateur band in Norway", _GAP),
    (10_000e6, 10_250e6, "10.00-10.25 GHz is not an amateur band in Norway", _GAP),
]

# no.md s.4: the regulation names the amateur-satellite service only for
# 1260-1270 MHz (from 2028); QO-100's uplink lies inside 2300-2450 MHz,
# which both classes hold without further permission, at their 13 cm power.
SATELLITE = [
    (1260e6, 1270e6, "up", "N1 § 5a (1258-1296 MHz row, from 2028)"),
    (2300e6, 2450e6, "both", "N1 § 5, § 5a; no.md s.4"),
]

# no.md s.5: Full is HAREC class A (§ 4) and the CEPT licence (T/R 61-01
# Annex 2: Norway LA, A). Begrenset is valid only in Norway; Norway has not
# implemented ECC/REC/(05)06. A visiting CEPT licensee follows § 5a (NRRL's
# visitor page [secondary], consistent with Annex 2's "A").
CEPT = {"T/R 61-01": ("no_full",), "T/R 61-02": ("no_full",)}
CEPT_SRC = ("Forskrift om radioamatørvirksomhet § 4; CEPT T/R 61-01 Annex 2 Table 1 (16 Feb 2024) p.6; "
            "ECC/REC/(05)06 Annex 2 p.5")
CEPT_VISITOR = {"T/R 61-01": "no_full"}

NOTES = [
    ("identification", "Give the full call sign at the start and end of a transmission, and at short intervals "
                       "during it.", "N1 § 7"),
    ("interference", "If transmitting causes interference, output power must be reduced to at most 100 W.",
     "N1 § 7"),
    ("ny-alesund", "The regulation does not apply to 2-32 GHz within 20 km of Ny-Ålesund (Svalbard): no amateur "
                   "transmission there.", "N1 § 2"),
    ("eme", "1000 W may be used for EME and meteor scatter on 4 m, 2 m, 70 cm and 23 cm (to 2027) with a "
            "directional antenna and a log of time, azimuth and elevation; OpenHamShack holds the ordinary limit.",
     "N1 § 5a"),
    ("training", "A restricted licensee may transmit under Full conditions while a Full licensee is present "
                 "and supervising.", "N1 § 6"),
    ("airborne", "No transmission from unmanned aircraft, except organised emergency communication and "
                 "experimental telemetry at 100 mW EIRP at most.", "N1 § 7"),
    ("encryption", "Encryption is prohibited, except for organised emergency communication and training "
                   "for it.", "N1 § 8"),
]
