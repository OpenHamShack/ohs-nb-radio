"""The Finnish amateur licence (Traficom): who may transmit where, at what power.

Sources: Radiotaajuusmääräys 4 AG/2026 M and its allocation table
(Taajuusjakotaulukko), in force 31 March 2026 [F1] - every amateur band,
its power and its repeater pairs - and Radioamatöörimääräys 6 K/2019 M [F2]
- power definitions, bandwidths, call signs. As transcribed in
docs/ham/countries/fi.md section 3; "table p.N" is the table's own folio.
F1 is reissued about yearly: re-check each spring. Nobody has yet done the
line-by-line check the UK had (docs/ham/licence-check.md).

Power. F1 gives one figure on HF that "means PEP if the carrier is
suppressed by at least 6 dB; otherwise carrier power", and above 30 MHz a
carrier figure with a higher PEP figure "if the carrier is suppressed by at
least 6 dB". Both are transmitter power into the feeder [F2 § 3]. That is a
limit that depends on the mode, so each row carries Limits by mode class:
SSB gets the PEP figure; everything else the carrier figure. Whether a
digital mode or digital voice sent through an SSB exciter counts as
"carrier suppressed" is not stated [UNCONFIRMED], so digi and dv take the
carrier figure, the stricter reading. (The guard judges a carrier limit on
PEP, so CW, FM and AM are held at least as tightly as the law holds them.)

What is left out or held back, and why (fi.md sections 3.1, 5 and 8):
- 1240-1300 MHz needs a separate, case-by-case licence whose terms are not
  published: refused, with a sentence pointing to the operator's own
  licence.
- 70.000-70.050 MHz is for beacons only, and 438.0625-438.1625 MHz for
  repeater transmitters only: refused.
- The 6 m field-strength limit at the Russian border cannot be computed
  here: a NOTE. The 4 m excluded municipalities, the 4 m border zones and
  the part of Tohmajärvi where 6 m may not be used are CONDITIONS, each
  defaulting to the answer that refuses or limits.
- The general class's 600 W carrier for CW and digital modes of at most
  3 kHz on 144.000-144.150 and 432.000-432.150 MHz is encoded by mode; the
  3 kHz is not checked per mode (the 18 kHz legal cap still applies).
- Old classes L and T: their rights in today's table are [UNCONFIRMED], so
  they are not offered.
"""
from __future__ import annotations

# Limit is defined in the package before any regime is imported there (the
# package must import its regimes below the class).
from . import Limit

ID = "traficom-2026"
TITLE = "Traficom amateur licence (Radiotaajuusmääräys 4 AG/2026 M, 6 K/2019 M)"
SHORT = "Finland (Traficom)"
AUTHORITY = "Traficom"
COUNTRY = ("FI",)
PLAN = ""
# [F1] in docs/ham/countries/fi.md; [F2] 6 K/2019 M sha256 7c635555...e2bfd5.
SOURCE = {
    "title": "Traficom, Radiotaajuusmääräys 4 AG/2026M, Taajuusjakotaulukko; with Radioamatöörimääräys 6 K/2019 M",
    "url": "https://www.finlex.fi/api/media/authority-regulation/1070975/mainPdf/main.pdf"
           "?typeDiscriminator=traficom-communications",
    "version": "4 AG/2026M, given 26.3.2026, in force 31.3.2026 (repeals 4 AF/2025M)",
    "date": "2026-03-31",
    "checked": "2026-10-08",
    "sha256": "d272fe71d37a8b953d5ec349185826fc4439e6ac481ef5f50beff26a8b96258b",
}
CLASSES = ("perus", "yleis")
CLASS_NAME = {"perus": "Basic (perusluokka)", "yleis": "General (yleisluokka)"}

_SSB = frozenset({"ssb"})
_REST = frozenset({"cw", "am", "fm", "digi", "dv", "image"})


def _pc(carrier, pep=None):
    """F1's "carrier power, or PEP if the carrier is suppressed by at least
    6 dB" as mode-dependent limits (pep None: the same figure for both)."""
    return ((float(pep if pep is not None else carrier), "PEP", _SSB), (float(carrier), "carrier", _REST))


def _r(lo_khz, hi_khz, perus, yleis, note="", src="", **extras):
    row = (lo_khz * 1e3, hi_khz * 1e3, {"perus": perus, "yleis": yleis}, note, "F1 table " + src)
    return row + (extras,) if extras else row


_EIRP1 = (1.0, "EIRP")
_HF = _pc(120), _pc(1500)
_UP = _pc(30, 120), _pc(150, 600)          # 2 m, 70 cm, 13 cm and up
# 144.000-144.150 and 432.000-432.150 MHz: the general class may use 600 W
# carrier with A1A and digital emissions of at most 3 kHz [F1 pp.70, 94].
_WEAK = (_pc(30, 120), ((600.0, "PEP", _SSB), (600.0, "carrier", frozenset({"cw", "digi", "dv"})),
                        (150.0, "carrier", frozenset({"am", "fm", "image"}))))

ALLOCATIONS = [
    _r(135.7, 137.8, _EIRP1, _EIRP1, "secondary", "p.4"),
    _r(472, 479, _EIRP1, _EIRP1, "secondary", "p.6"),
    _r(1810, 1850, *_HF, "primary", "p.8"),
    _r(1850, 2000, _pc(15, 60), _pc(15, 60), "secondary", "p.8"),
    _r(3500, 3800, *_HF, "primary", "p.14"),
    _r(5351.5, 5366.5, (15.0, "EIRP"), (15.0, "EIRP"), "primary (F4)", "p.20"),
    _r(7000, 7200, *_HF, "exclusive primary", "p.25"),
    _r(10100, 10150, *_HF, "secondary", "p.30"),
    _r(14000, 14350, *_HF, "exclusive primary", "pp.36-37"),
    _r(18068, 18168, *_HF, "exclusive primary", "p.42"),
    _r(21000, 21450, *_HF, "exclusive primary", "p.46"),
    _r(24890, 24990, *_HF, "exclusive primary", "p.50"),
    _r(28000, 29700, *_HF, "exclusive primary", "p.55"),
    _r(50000, 50500, _pc(30, 120), _pc(150, 200), "primary; Russian border field-strength limit (NOTES)", "p.60"),
    _r(50500, 52000, _pc(30, 120), _pc(150, 200), "secondary; Russian border field-strength limit (NOTES)", "p.60"),
    # "Lähettimen teho" with no PEP or carrier qualifier on 4 m: PEP.
    _r(70050, 70250, (30.0, "PEP"), (100.0, "PEP"), "secondary; transmitter power, no reference stated: PEP",
       "p.62"),
    _r(70250, 70300, (25.0, "PEP"), (25.0, "PEP"), "secondary; transmitter power, no reference stated: PEP",
       "p.62"),
    _r(144000, 144150, *_WEAK, "exclusive primary", "p.70"),
    _r(144150, 146000, *_UP, "exclusive primary", "pp.70-72"),
    _r(432000, 432150, *_WEAK, "primary", "p.94"),
    _r(432150, 435000, *_UP, "primary", "p.94"),
    # Only an amateur-satellite row in F1 [derived from F1 rows, fi.md s.3].
    _r(435000, 436000, *_UP, "amateur-satellite only", "p.96", satellite_only=True),
    _r(436000, 438000, *_UP, "primary; amateur and amateur-satellite", "pp.96-97"),
    _r(2300000, 2400000, *_UP, "secondary", "p.131"),
    _r(2400000, 2450000, *_UP, "secondary; amateur and amateur-satellite", "p.131"),
    _r(3400000, 3408000, *_UP, "secondary; ends at 3408 MHz", "p.136"),
    _r(5650000, 5850000, *_UP, "secondary", "pp.141-143"),
    _r(10000000, 10280000, *_UP, "secondary", "p.151"),
    _r(10368000, 10370000, *_UP, "secondary; narrowband only", "p.151"),
    _r(10450000, 10500000, *_UP, "secondary; amateur and amateur-satellite", "p.152"),
    _r(24000000, 24050000, *_UP, "primary", "p.168"),
    _r(24050000, 24250000, *_UP, "secondary", "p.169"),
    _r(47000000, 47200000, *_UP, "exclusive primary", "p.179"),
    _r(76000000, 77500000, *_UP, "secondary", "p.189"),
    _r(77500000, 78000000, *_UP, "primary", "pp.189-190"),
    _r(78000000, 81500000, *_UP, "secondary", "pp.191-193"),
    _r(122250000, 123000000, *_UP, "secondary", "p.200"),
    _r(134000000, 136000000, *_UP, "primary", "p.201"),
    _r(136000000, 141000000, *_UP, "secondary", "p.202"),
    _r(241000000, 248000000, *_UP, "secondary", "p.209"),
    _r(248000000, 250000000, *_UP, "primary", "p.210"),
]

# F2 § 16: below 30 MHz at most 8 kHz, 50-146 MHz at most 18 kHz, but
# 472-479 kHz, 10100-10150 kHz and 70.000-70.050 MHz at most 1 kHz (the
# last is REFUSED here anyway). No figure for 135.7 kHz or above 146 MHz.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})
_BOTH = ("perus", "yleis")


def _bw(lo_khz, hi_khz, hz):
    return (lo_khz * 1e3, hi_khz * 1e3, {c: _ALL for c in _BOTH}, float(hz), f"at most {hz / 1e3:g} kHz",
            "F2 § 16")


EMISSIONS = [_bw(472, 479, 1000), _bw(10100, 10150, 1000)] + [_bw(lo, hi, 8000) for lo, hi in (
    (1810, 2000), (3500, 3800), (5351.5, 5366.5), (7000, 7200), (14000, 14350), (18068, 18168),
    (21000, 21450), (24890, 24990), (28000, 29700))] + [_bw(lo, hi, 18000) for lo, hi in (
    (50000, 52000), (70050, 70300), (144000, 146000))]

REFUSED = [
    (5250e3, 5351.5e3, "Finnish 60 m use is only 5351.5-5366.5 kHz", "F1 table p.20; fi.md s.3.1"),
    (5366.5e3, 5450e3, "Finnish 60 m use is only 5351.5-5366.5 kHz", "F1 table p.20; fi.md s.3.1"),
    (70e6, 70.05e6, "70.000-70.050 MHz is for amateur beacons only in Finland", "F1 table p.61"),
    (70.3e6, 70.5e6, "The Finnish 4 m allocation ends at 70.300 MHz", "F1 table p.62; fi.md s.3.2"),
    (430e6, 432e6, "430-432 MHz is not an amateur band in Finland", "F1; fi.md s.3.2"),
    (438.0625e6, 438.1625e6, "438.0625-438.1625 MHz is for repeater transmitters only in Finland",
     "F1 table pp.96-97; fi.md s.3"),
    (1240e6, 1300e6, "1240-1300 MHz needs a separate, case-by-case licence from Traficom whose terms are not "
                     "published; if you hold one, enter its terms as your own licence in Settings › Licence & plan",
     "F1 table pp.118-119; F4; F5"),
]

# Location rules on 4 m and 6 m [F1 pp.60-62; F4], each defaulting to the
# answer that refuses or limits.
_MUNICIPALITIES = ("Lieksa, Ilomantsi, Joensuu, Kontiolahti, Polvijärvi, Juuka, Nurmes, Valtimo, Kuhmo, "
                   "Hyrynsalmi, Suomussalmi, Ristijärvi or Sotkamo")
CONDITIONS = [
    {"key": "inFinnish4mExcludedArea", "lo": 70.05e6, "hi": 70.3e6, "default": True,
     "label": f"Station is in {_MUNICIPALITIES}",
     "refuse": (f"4 m may not be used in {_MUNICIPALITIES}; Settings › Licence & plan says this station is there, "
                f"or has not been told otherwise"),
     "src": "F1 table pp.61-62 (a)"},
    {"key": "nearFinnishBorder4m", "lo": 70.05e6, "hi": 70.3e6, "default": True,
     "label": "Station is within 50 km of the Russian or Norwegian border",
     # "suurin sallittu lähetysteho", transmitter power with no reference:
     # PEP, as on the 4 m rows.
     "limit": Limit(25.0, "PEP"), "src": "F1 table pp.61-62 (b), (c)"},
    {"key": "inTohmajarvi6mArea", "lo": 50e6, "hi": 52e6, "default": True,
     "label": "Station is in the part of Tohmajärvi where 6 m transmitters may not be used",
     "refuse": ("6 m transmitters may not be used in part of Tohmajärvi; Settings › Licence & plan says this "
                "station is there, or has not been told otherwise"),
     "src": "F4 (compilation of F1 table p.60)"},
]

# Satellite rows of F1 (fi.md s.4): 5650-5670 MHz uplink, 5830-5850 MHz
# "satelliitista maahan" (downlink); the rest name no direction. 1260-1270
# MHz falls under the separate 23 cm licence.
_SAT = "F1 table (fi.md s.4)"
SATELLITE = [(a * 1e3, b * 1e3, d, _SAT) for a, b, d in (
    (7000, 7100, "both"), (14000, 14250, "both"), (18068, 18168, "both"), (21000, 21450, "both"),
    (24890, 24990, "both"), (28000, 29700, "both"), (144000, 146000, "both"), (435000, 438000, "both"),
    (2400000, 2450000, "both"), (5650000, 5670000, "up"), (5830000, 5850000, "down"),
    (10450000, 10500000, "both"), (24000000, 24050000, "both"), (47000000, 47200000, "both"),
    (76000000, 81500000, "both"), (136000000, 141000000, "both"), (241000000, 250000000, "both"))]

# T/R 61-01 Annex 2 lists "Finland | OH | L, P, T, Y" [C1 p.5], but whether
# the basic class (P) is accepted abroad is [UNCONFIRMED]: only the general
# class, which Traficom calls HAREC, is mapped. ECC/REC/(05)06 footnote 1
# [C2 p.5]: Finland has no Novice-equivalent class, but CEPT Novice visitors
# may "under no circumstances exceed the Finnish elementary novice class
# guidelines" - the basic class.
CEPT = {"T/R 61-01": ("yleis",), "T/R 61-02": ("yleis",)}
CEPT_SRC = ("CEPT T/R 61-01 Annex 2 p.5; ECC/REC/(05)06 Annex 2 p.5 footnote 1; Traficom 'Qualifications and "
            "frequencies in amateur radio operations' (fetched 2026-10-08)")
CEPT_VISITOR = {"ECC/REC (05)06": "perus"}

NOTES = [
    ("location", "6 m: the field strength at the Russian border, at 10 m height, must not exceed +6 dBµV/m for "
                 "more than 10 % of the time; Traficom publishes a guide to computing it. Not judged here.",
     "F1 table p.60"),
    ("location", "4 m within 50 km of the Russian border: the antenna's main lobe must not point between 0 and 180 "
                 "degrees. Not judged here.", "F1 table pp.61-62 (b)"),
    ("power", "The general class may be licensed individually for higher power for experiments; OpenHamShack applies "
              "the table's figures.", "F1 § 3.12"),
    ("unattended", "Unattended stations need a special licence, supervised by a general or technical class holder.",
     "F2 § 5"),
]

