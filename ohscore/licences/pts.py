"""The Swedish amateur rules (PTS): who may transmit where, at what power.

Sweden issues no amateur licence: transmitting is exempt from licensing
for the holder of a certificate. Source: [P1] PTSFS 2025:1, Post- och
telestyrelsens föreskrifter om undantag från tillståndsplikt för
användning av vissa radiosändare, in force 17 March 2025, whose 3 kap.
gives each amateur band its own paragraph (27 § to 259 §), as transcribed
in docs/ham/countries/se.md section 3. No later amendment was found, but
PTS's search was blocked to the research [UNCONFIRMED]: re-check before
relying on it. The research has not had the line-by-line check the UK's
had (docs/ham/licence-check.md).

Nearly every figure is "Högsta effekt tillförd antennsystemet: N W
p.e.p." - PEP supplied to the antenna system. The exceptions are 1 W ERP
on 2200 m, 1 W EIRP on 630 m, 15 W EIRP on 60 m and the entry
certificate's 25 W ERP on 2 m. P1 sets no bandwidths, no primary or
secondary status and no satellite rules.

Decisions:
- More power, 70 MHz, or more than 100 mW on 2400-2450 MHz for satellite
  work need an individual PTS permit whose terms are not public: not
  encoded. The exemption's figures are the limits here, and QO-100 NB's
  QO-100 uplink is 100 mW PEP.
- The entry certificate may be used only with CE-marked transmitters, and
  not for automatic stations or remote control (49 §). OpenHamShack cannot tell
  whether a transmitter is CE-marked, and a condition cannot single out
  one class, so it is a NOTE.
- 2300-2400 MHz (auctioned), 3.4 GHz, 70 MHz, 430-432 and 438-440 MHz are
  not amateur in Sweden: refused with a sentence saying so.
- Bands are written to 10.5 GHz; the research's 24-250 GHz rows are left
  out (the apps' hardware stops at 5.85 GHz).
"""
from __future__ import annotations

ID = "pts-2025"
TITLE = "Swedish amateur exemption (PTSFS 2025:1)"
SHORT = "Sweden (PTS)"
AUTHORITY = "Post- och telestyrelsen (PTS)"
COUNTRY = ("SE",)
PLAN = ""
SOURCE = {
    "title": "PTSFS 2025:1, Post- och telestyrelsens föreskrifter om undantag från tillståndsplikt för "
             "användning av vissa radiosändare, 3 kap. (Amatörradiotrafik)",
    "url": "https://pts.se/contentassets/b05c8a7d01a64783aafc6a19e1b78590/"
           "ptsfs-2025-1-foreskrifter-om-undantag-fran-tillstandsplikt-for-anvandning-av-vissa-radiosandare.pdf",
    "version": "Beslutade 20 februari 2025, utkom 4 mars 2025, in force 17 March 2025",
    "date": "2025-02-20",
    "checked": "2026-10-08",
    "sha256": "bd9ece78d49dcd45691cbdef8414e5c8fee089cd0f923ee483fcdc73dc4d571d",
}
CLASSES = ("insteg", "certifikat")
CLASS_NAME = {"insteg": "Entry certificate (instegscertifikat)", "certifikat": "Amateur radio certificate"}

_P, _E, _I = "PEP", "ERP", "EIRP"


def _r(lo_khz, hi_khz, i, c, src, note=""):
    """A row in kHz; i and c are insteg's and certifikat's limits (None:
    no paragraph for the class). A bare number is W PEP to the antenna
    system."""
    lim = {}
    for cls, v in (("insteg", i), ("certifikat", c)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    return (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)


ALLOCATIONS = [
    _r(135.7, 137.8, None, (1.0, _E), "P1 27 § p.14"),
    _r(472, 479, None, (1.0, _I), "P1 35 § p.15"),
    # 160 m in four steps (38-41 §).
    _r(1810, 1850, None, 200, "P1 38 § p.16"),
    _r(1850, 1900, None, 10, "P1 39 § p.16"),
    _r(1900, 1950, None, 100, "P1 40 § p.16"),
    _r(1950, 2000, None, 10, "P1 41 § p.16"),
    _r(3500, 3800, None, 200, "P1 43 § p.16"),
    _r(5351.5, 5366.5, None, (15.0, _I), "P1 46 § p.16"),
    _r(7000, 7200, 25, 200, "P1 48 § p.16, 49 § p.17"),
    _r(10100, 10150, None, 150, "P1 52 § p.17"),
    _r(14000, 14350, 25, 200, "P1 59 §, 60 § p.18"),
    _r(18068, 18168, None, 200, "P1 61 § p.18"),
    _r(21000, 21450, 25, 200, "P1 62 §, 63 § p.18"),
    _r(24890, 24990, None, 200, "P1 64 § p.18"),
    _r(28000, 29700, 25, 200, "P1 85 §, 86 § p.21"),
    _r(50000, 52000, 25, 200, "P1 98 §, 99 § p.23"),
    # 104 §: the entry certificate's 2 m figure is radiated (ERP).
    _r(144000, 146000, (25.0, _E), 200, "P1 103 §, 104 § p.23", "entry certificate: 25 W ERP"),
    _r(432000, 438000, None, 200, "P1 123 § p.26"),
    _r(1240000, 1300000, None, 200, "P1 154 § p.34"),
    _r(2400000, 2450000, None, 0.1, "P1 185 § p.47", "100 mW PEP; more needs a PTS permit"),
    _r(5650000, 5850000, None, 200, "P1 203 § p.51"),
    _r(10000000, 10500000, None, 200, "P1 213 § p.53"),
]

_GAP = "se.md s.3.1, s.3.2"
REFUSED = [
    (69.9e6, 70.5e6, "70 MHz is not an amateur band in Sweden: it needs a temporary permit from PTS", _GAP),
    (430e6, 432e6, "430-432 MHz is not an amateur band in Sweden", _GAP),
    (438e6, 440e6, "438-440 MHz is not an amateur band in Sweden", _GAP),
    (2300e6, 2400e6, "2300-2400 MHz is not an amateur band in Sweden: PTS auctioned it", _GAP),
    (3400e6, 3410e6, "3.4 GHz is not an amateur band in Sweden", _GAP),
]

# se.md s.4: QO-100's uplink is inside 185 §'s 2400-2450 MHz, which only
# the full certificate holds, at 100 mW PEP. P1 has no other satellite
# rules, so no other row is listed.
SATELLITE = [(2400e6, 2450e6, "both", "P1 185 § p.47; se.md s.4")]

# se.md s.5: every full certificate is a CEPT licence (T/R 61-01 Annex 2:
# Sweden SM, SA, "All") and needs HAREC knowledge (27 §); Sweden has not
# implemented ECC/REC/(05)06, and the entry certificate is national only.
# A visiting CEPT licensee has the full certificate's terms (SSA's visitor
# page [secondary], consistent with Annex 2).
CEPT = {"T/R 61-01": ("certifikat",), "T/R 61-02": ("certifikat",)}
CEPT_SRC = ("PTSFS 2025:1 27 §; CEPT T/R 61-01 Annex 2 (16 Feb 2024) p.7 notes 15-16; "
            "ECC/REC/(05)06 Annex 2 p.5")
CEPT_VISITOR = {"T/R 61-01": "certifikat"}

NOTES = [
    ("identification", "Send the call sign at the start and end of each contact, and repeat it at short "
                       "intervals while it continues.", "P1 27 § p.14"),
    ("ce-marking", "An entry certificate may be used only with CE-marked transmitters: not a home-built or "
                   "modified one, nor a software-defined radio not marked as an amateur transmitter.",
     "P1 49 § p.17"),
    ("unattended", "An entry certificate gives no right to automatic stations or remote control.", "P1 49 § p.17"),
    ("automatic", "Beacons, repeaters and position transmitters must identify regularly with the responsible "
                  "person's call sign.", "P1 27 § p.14"),
    ("permit", "Higher power (up to 1 kW), 70 MHz and more than 100 mW on 2400-2450 MHz need an individual PTS "
               "permit; OpenHamShack holds the exemption's limits.", "se.md s.1, s.3.1"),
]
