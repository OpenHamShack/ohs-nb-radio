"""The IARU Region 2 band plan, 160 m to 6 cm, as data: the generic plan
for a station in the Americas whose country has no national plan written
here (ohsradio/plans/__init__.py choose()).

It is a "voluntary band plan ... national and/or local band plans may not
follow the IARU Region 2 band plan exactly", and operators "are cautioned
to consult all applicable national plans and regulatory documents before
transmitting" [N1 p.1]. The licence is the law; the guard warns outside
this plan (or refuses, under "enforce") and always refuses its beacon and
satellite-exclusive segments.

Source: IARU Region 2 Band Plan, "September 2020" (N1), transcribed in
docs/ham/bandplan-iaru-regions.md section 4 with each row's page. The R2
committee may amend it between assemblies; none was found (that document,
section 7), and the 2025 General Assembly reported no change.

Decisions taken while encoding:

- The plan's own extents are used where R2's allocation is wider than
  the UK edges in ohsradio/bands.py: 80 m to 4000 kHz, 40 m to 7300, 6 m to
  54 MHz, 2 m to 148, 9 cm 3300-3500 and 6 cm to 5925. 420-430 and
  440-450 MHz are left out: only footnote countries (5.270, 5.284) have
  them, and their national plans enable them.
- R2 "All modes" is every class; the plan's bandwidth does the limiting.
  Rows marked (*) allow DSB AM "up to 6 kHz" [N1 p.1]; the guard has one
  bandwidth per segment, so those rows carry 6000 Hz, else AM would be
  warned exactly where the plan invites it.
- "Local option" blocks (144.5-144.6, 145.1-145.2, 433.1-435, 438-440,
  2310-2390 MHz) have no segment: the plan leaves them to national and
  local plans, so only the licence speaks there.
- Beacon sub-bands are refused although most are not marked exclusive (the
  IBP slots and 28199-28201 are): no ordinary traffic is planned in them.
  The one exception is 50.000-50.100 MHz, which is also R2's whole 6 m CW
  segment and so stays transmittable for CW. The whole 28190-28225 kHz
  segment is refused, as the plan prints it, with the exclusive IBP slot
  inside it. 144.400-144.500 is refused although it holds the ISS FM
  voice uplink at 144.490 (note 2): satellite work is refused here anyway.
- The guard bands at 29510-29520 kHz and 145.790-145.800 MHz ("no
  transmission allowed") are always refused. base.KINDS has only beacon
  and satellite as always-refused kinds; both guards protect the
  satellite segment beside them, so they are kind "satellite".
- Satellite segments are refused where the plan says "(exclusive)" or
  lists them in the satellite-only table (29300-29510 kHz, 145.8-146 and
  435-438 MHz). The others are shared and transmittable: 21125-21450 kHz,
  144.000-144.025, 1260-1270 ("priority"), 2400-2450, 3400-3410 and the
  6 cm satellite segments.
- The 9 cm radio-astronomy bands (3332-3339 and 3345.8-3352.5 MHz) are
  "protected" with no operation. No kind in base.KINDS refuses them
  without misnaming them, so they are "not for transmitting" (modes
  empty): the guard warns, and refuses under "enforce".
- 147.0-147.4 MHz are inputs and 147.6-148.0 outputs as N1 prints them,
  the reverse of common US practice [unverified]; an output only warns,
  so a national (ARRL) plan can correct it without anyone being blocked.
- ATV segments carry the image class (the app's image modes are SSTV and
  fax); SSB or FM there warns.
- N1 lists no FT8 or other digital dial frequencies: the band bar's
  WSJT-X dials (ohsradio/bands.py) supply them.

All frequencies Hz.
"""
from __future__ import annotations

from .. import bands as _bands
from .base import (ALL, CLASS_WORD, CW, FM, HF_ALL, MODE_CLASS, NARROW, NONE, WEAK, Seg,  # noqa: F401
                   make_lookup)
from .base import k as _k
from .base import m as _m

ID = "iaru-r2"
TITLE = "IARU Region 2 band plan"
SHORT = "IARU Region 2"
REGION = 2
COUNTRY = ()
SOURCE = {"title": "IARU Region 2 Band Plan (IARU-Region-2-Band-plan.pdf)",
          "url": "https://www.iaru-r2.org/wp-content/uploads/2020/02/IARU-Region-2-Band-plan.pdf",
          "version": "September 2020 (incorporates the Lima 2019 General Assembly changes)",
          # The title page gives only the month; the R2 page announced it on 4 Oct 2020.
          "date": "2020-09-01", "checked": "2026-10-08"}
SOURCES = [SOURCE]

AM_BW = 6000          # rows marked (*): DSB AM up to 6 kHz
CW_SSB = frozenset({"cw", "ssb"})
DIGI = frozenset({"digi"})
IMAGE = frozenset({"image"})
NBFM = frozenset({"cw", "ssb", "digi", "fm"})

# HF, kHz [N1 p.5-10].
HF = (
    # 1840-1843 also admits digital modes up to 200 Hz; the segment's
    # 2700 Hz is the SSB figure.
    _k((1800, 1810, "digital modes", DIGI, 500, ""), (1810, 1830, "CW", CW, 200, ""),
       (1830, 1839, "CW, DX window", CW, 200, ""), (1839, 1840, "DX window, ACDS", NARROW, 200, ""),
       (1840, 1843, "SSB DX window", WEAK, 2700, ""), (1843, 1850, "SSB DX window", CW_SSB, 2700, ""),
       (1850, 2000, "all modes", ALL, AM_BW, "")) +
    # 3600-3625 (ACDS, *) and 3600-3650 (SSB contest preferred) overlap as
    # printed: the (*) row keeps its 6 kHz, the rest is the 2700 Hz row.
    _k((3500, 3510, "CW, DX window", CW, 200, ""), (3510, 3560, "CW, contest preferred", CW, 200, ""),
       (3560, 3570, "CW", CW, 200, ""), (3570, 3580, "CW, digital modes", NARROW, 200, ""),
       (3580, 3590, "CW, digital modes", NARROW, 500, ""), (3590, 3600, "CW, digital modes, ACDS", NARROW, 500, ""),
       (3600, 3625, "all modes, ACDS", ALL, AM_BW, ""),
       (3625, 3650, "all modes, SSB contest preferred", ALL, 2700, ""), (3650, 3700, "all modes", ALL, 2700, ""),
       (3700, 3775, "all modes, SSB contest preferred", ALL, 2700, ""),
       (3775, 3800, "all modes, DX window", ALL, 2700, ""), (3800, 3875, "all modes", ALL, 2700, ""),
       (3875, 3900, "all modes", ALL, AM_BW, ""), (3900, 4000, "all modes", ALL, 2700, "")) +
    _k((5351.5, 5354, "CW, digital modes", NARROW, 500, ""), (5354, 5366, "all modes, USB", ALL, 2700, ""),
       (5366, 5366.5, "CW, digital modes, ACDS", NARROW, 20, "")) +
    _k((7000, 7025, "CW, DX window", CW, 200, ""), (7025, 7040, "CW", CW, 200, ""),
       (7040, 7047, "CW, digital modes", NARROW, 500, ""), (7047, 7050, "CW, digital modes, ACDS", NARROW, 500, ""),
       (7050, 7053, "all modes, ACDS", ALL, 2700, ""), (7053, 7060, "all modes", ALL, 2700, ""),
       (7060, 7100, "all modes, SSB contest preferred", ALL, 2700, ""), (7100, 7130, "all modes", ALL, AM_BW, ""),
       (7130, 7200, "all modes, SSB contest preferred", ALL, AM_BW, ""), (7200, 7300, "all modes", ALL, AM_BW, "")) +
    # 10140-10150 is printed 2700 Hz for CW and digital modes only; encoded
    # as printed.
    _k((10100, 10130, "CW", CW, 200, ""), (10130, 10140, "CW, digital modes, ACDS", NARROW, 500, ""),
       (10140, 10150, "CW, digital modes", NARROW, 2700, "")) +
    _k((14000, 14025, "CW, DX window", CW, 200, ""), (14025, 14060, "CW, contest preferred", CW, 200, ""),
       (14060, 14070, "CW", CW, 200, ""), (14070, 14089, "CW, digital modes", NARROW, 500, ""),
       (14089, 14099, "CW, digital modes, ACDS", NARROW, 500, ""),
       (14099, 14101, "IBP beacons", None, None, "beacon"), (14101, 14112, "all modes, ACDS", ALL, 2700, ""),
       (14112, 14190, "all modes, SSB contest preferred", ALL, 2700, ""),
       (14190, 14200, "all modes, SSB DX window", ALL, 2700, ""),
       (14200, 14285, "all modes, SSB contest preferred", ALL, 2700, ""),
       (14285, 14300, "all modes", ALL, AM_BW, ""), (14300, 14350, "all modes", ALL, 2700, "")) +
    _k((18068, 18095, "CW", CW, 200, ""), (18095, 18105, "CW, digital modes", NARROW, 500, ""),
       (18105, 18109, "CW, digital modes, ACDS", NARROW, 500, ""),
       (18109, 18111, "IBP beacons", None, None, "beacon"),
       (18111, 18120, "all modes, ACDS", ALL, 2700, ""), (18120, 18168, "all modes", ALL, 2700, "")) +
    # 21120-21149 is printed "all modes" at 500 Hz; encoded as printed (the
    # bandwidth keeps it narrow). 21125-21450 is a shared satellite uplink
    # (footnote 2), so nothing here changes for it.
    _k((21000, 21070, "CW", CW, 200, ""), (21070, 21090, "CW, digital modes", NARROW, 500, ""),
       (21090, 21110, "CW, digital modes, ACDS", NARROW, 500, ""),
       (21110, 21120, "CW, digital modes, ACDS", NARROW, 2700, ""),
       (21120, 21149, "all modes, narrow", ALL, 500, ""), (21149, 21151, "IBP beacons", None, None, "beacon"),
       (21151, 21380, "all modes", ALL, 2700, ""), (21380, 21450, "all modes", ALL, AM_BW, "")) +
    _k((24890, 24915, "CW", CW, 200, ""), (24915, 24925, "CW, digital modes", NARROW, 500, ""),
       (24925, 24929, "CW, digital modes, ACDS", NARROW, 500, ""),
       (24929, 24931, "IBP beacons", None, None, "beacon"),
       (24931, 24940, "all modes, ACDS", ALL, 2700, ""), (24940, 24990, "all modes", ALL, 2700, "")) +
    # The outputs' "29620 to 26690 kHz" is printed so and read as 29690.
    _k((28000, 28070, "CW", CW, 200, ""), (28070, 28120, "CW, digital modes", NARROW, 500, ""),
       (28120, 28150, "CW, digital modes, ACDS", NARROW, 500, ""),
       (28150, 28190, "CW, digital modes", NARROW, 500, ""),
       (28190, 28225, "beacons (IBP 28199-28201)", None, None, "beacon"),
       (28225, 28300, "all modes, beacons (shared)", ALL, 2700, ""),
       (28300, 28320, "all modes, ACDS", ALL, 2700, ""), (28320, 29000, "all modes", ALL, 2700, ""),
       (29000, 29200, "all modes, AM preferred", ALL, 6000, ""), (29200, 29300, "all modes, ACDS", ALL, 6000, ""),
       (29300, 29510, "satellites", None, None, "satellite"),
       (29510, 29520, "guard band", None, None, "satellite"),
       (29520, 29590, "repeater inputs", FM, 6000, ""), (29590, 29620, "FM calling and simplex", FM, 6000, ""),
       (29620, 29700, "repeater outputs", NONE, None, "output"))
)

# 6 m and up, MHz [N1 p.11-18].
VHF = (
    # The printed "+500 Hz" / "-500 Hz" repeater offsets are read as kHz.
    # N1 names no 6 m FM calling frequency.
    _m((50.000, 50.100, "CW, beacons (shared)", CW, 500, ""), (50.100, 50.125, "DX window", CW_SSB, 2700, ""),
       (50.125, 50.400, "CW, SSB, digital modes", WEAK, 2700, ""),
       (50.400, 50.500, "beacons, digital beacons", None, None, "beacon"),
       (50.500, 50.600, "all modes, ACDS", ALL, AM_BW, ""), (50.600, 50.800, "all modes, ACDS", ALL, 12_000, ""),
       (50.800, 51.000, "radio remote control", ALL, 12_000, ""), (51.000, 51.110, "DX window", CW_SSB, 2700, ""),
       (51.110, 51.480, "repeater inputs", FM, 12_000, ""), (51.500, 51.600, "FM simplex", FM, 12_000, ""),
       (51.620, 51.980, "repeater outputs", NONE, None, "output"),
       (52.000, 52.100, "internet voice gateways", FM, 12_000, ""), (52.100, 54.000, "all modes", ALL, 12_000, "")) +
    # 2 m: 144.000-144.025 "Satellites" and 144.000-144.110 "EME and weak
    # signal" CW overlap as printed. The satellite row is not exclusive, so
    # terrestrially the CW row is what applies. 144.900-145.000 is printed
    # "weak signal" in an FM/DV row; encoded as the row's classes.
    _m((144.000, 144.110, "CW, EME and weak signal", CW, 500, ""),
       (144.110, 144.150, "CW, digital, EME and weak signal", NARROW, 2700, ""),
       (144.150, 144.180, "weak signal", WEAK, 2700, ""), (144.180, 144.275, "weak signal", CW_SSB, 2700, ""),
       (144.275, 144.300, "beacons", None, None, "beacon"), (144.300, 144.360, "CW, SSB calling", CW_SSB, 2700, ""),
       (144.360, 144.400, "ACDS, APRS", DIGI | {"fm"}, 12_000, ""),       # APRS is FM AFSK
       (144.400, 144.500, "beacons, digital beacons", None, None, "beacon"),
       (144.600, 144.900, "repeater inputs", FM, 12_000, ""), (144.900, 145.000, "FM/DV", FM, 12_000, ""),
       (145.000, 145.100, "all modes, ACDS, gateways", ALL, 12_000, ""),
       (145.200, 145.500, "repeater outputs", NONE, None, "output"), (145.500, 145.790, "all modes", ALL, 12_000, ""),
       (145.790, 145.800, "guard band", None, None, "satellite"),
       (145.800, 146.000, "satellites", None, None, "satellite"),
       (146.000, 146.390, "repeater inputs", FM, 12_000, ""), (146.390, 146.600, "FM simplex", FM, 12_000, ""),
       (146.600, 146.990, "repeater outputs", NONE, None, "output"),
       (146.990, 147.400, "repeater inputs", FM, 12_000, ""), (147.400, 147.590, "FM/DV", FM, 12_000, ""),
       (147.590, 148.000, "repeater outputs", NONE, None, "output")) +
    # 70 cm: from 430, the footnote countries' 420-430 left to their plans.
    # 430-432 is the ATV simplex row (426-432), and the local option where
    # 430-450 is not held (note 1).
    _m((430.000, 432.000, "ATV simplex", IMAGE, None, ""), (432.000, 432.025, "CW, EME", CW, 500, ""),
       (432.025, 432.100, "EME and weak signal", NARROW, 500, ""),
       (432.100, 432.300, "weak signal, CW/SSB calling", CW_SSB, 2700, ""),
       (432.300, 432.400, "beacons", None, None, "beacon"),
       (432.400, 432.420, "beacons, digital beacons", None, None, "beacon"),
       (432.420, 433.000, "weak signal", WEAK, 2700, ""), (433.000, 433.050, "ACDS", DIGI, 12_000, ""),
       (433.050, 433.100, "internet voice gateways", ALL, 12_000, ""),
       (435.000, 438.000, "satellites", None, None, "satellite")) +
    # 23 cm. 1290-1294 is a regional option for repeater outputs inside the
    # broadband row; an option, so not cut out as outputs.
    _m((1240.000, 1246.000, "ATV channel 1", IMAGE, None, ""),
       (1246.000, 1248.000, "point-to-point links", FM, 20_000, ""),
       (1248.000, 1252.000, "digital", DIGI, 20_000, ""), (1252.000, 1258.000, "ATV channel 2", IMAGE, None, ""),
       (1258.000, 1260.000, "point-to-point links", FM, 20_000, ""),
       (1260.000, 1270.000, "satellite uplinks (priority), experimental", ALL, None, ""),
       (1270.000, 1276.000, "repeater inputs", FM, 20_000, ""), (1276.000, 1282.000, "ATV channel 3", IMAGE, None, ""),
       (1282.000, 1288.000, "repeater outputs", NONE, None, "output"),
       (1288.000, 1294.000, "broadband experimental", ALL, None, ""),
       (1294.000, 1295.000, "FM simplex", FM, 20_000, ""), (1295.000, 1295.800, "narrowband image, experimental",
                                                            ALL, None, ""),
       (1295.800, 1296.080, "EME and weak signal", WEAK, 2700, ""),
       (1296.080, 1296.200, "weak signal, CW/SSB calling", CW_SSB, 2700, ""),
       (1296.200, 1296.400, "beacons, digital beacons", None, None, "beacon"),
       (1296.400, 1297.000, "general narrowband", ALL, 2700, ""),
       (1297.000, 1300.000, "digital", DIGI, 150_000, "")) +
    # 13 cm. 2390-2400 holds the pairs of 2300-2310 (+90 MHz), each pair at
    # its partner's bandwidth as the plan prints them; 2393.75-2394.75 is
    # experimental with none. 2400-2450 "Satellites" is not exclusive:
    # broadband is allowed in 2410-2450 at up to 22 MHz.
    _m((2300.000, 2303.000, "analogue and digital, duplex", ALL, 1_000_000, ""),
       (2303.000, 2303.750, "analogue and digital", ALL, 50_000, ""),
       (2303.750, 2304.000, "weak signal", WEAK, 3000, ""), (2304.000, 2304.100, "EME and weak signal", WEAK, 3000, ""),
       (2304.100, 2304.300, "weak signal, calling", WEAK, 3000, ""),
       (2304.300, 2304.400, "beacons, digital beacons", None, None, "beacon"),
       (2304.400, 2304.750, "weak signal, NBFM", NBFM, 6000, ""),
       (2304.750, 2305.000, "analogue and digital", ALL, 50_000, ""),
       (2305.000, 2310.000, "analogue and digital", ALL, 1_000_000, ""),
       (2390.000, 2393.000, "analogue and digital, duplex", ALL, 1_000_000, ""),
       (2393.000, 2393.750, "analogue and digital", ALL, 50_000, ""),
       (2393.750, 2394.750, "experimental", ALL, None, ""),
       (2394.750, 2395.000, "analogue and digital", ALL, 50_000, ""),
       (2395.000, 2400.000, "analogue and digital", ALL, 1_000_000, ""),
       (2400.000, 2410.000, "satellites (shared)", ALL, None, ""),
       (2410.000, 2450.000, "satellites (shared), broadband", ALL, 22_000_000, "")) +
    # 9 cm, as the document lists it in prose: 3300-3400 duplex pairs at
    # several bandwidths (no single figure, so none), broadband from 3360.
    # The satellite rows (3400-3410) are shared, with "no restrictions for
    # modes and bandwidth for satellites" (footnote 1).
    _m((3300.000, 3332.000, "duplex pairs, experimental", ALL, None, ""),
       (3332.000, 3339.000, "radio astronomy, no operation", None, None, "protected"),
       (3339.000, 3345.800, "duplex pairs, experimental", ALL, None, ""),
       (3345.800, 3352.500, "radio astronomy, no operation", None, None, "protected"),
       (3352.500, 3360.000, "duplex pairs, experimental", ALL, None, ""),
       (3360.000, 3400.000, "broadband", ALL, 22_000_000, ""),
       (3400.000, 3400.300, "EME, weak signal, satellite", WEAK, 3000, ""),
       (3400.300, 3401.000, "weak signal, satellite", WEAK, 3000, ""),
       (3401.000, 3410.000, "satellites (shared)", ALL, None, ""), (3410.000, 3455.000, "duplex pairs", ALL, None, ""),
       (3455.000, 3455.500, "crossband linear translator", ALL, 100_000, ""),
       (3455.500, 3456.300, "weak signal, calling", NBFM, 6000, ""),
       (3456.300, 3457.000, "beacons, digital beacons", None, None, "beacon"),
       (3457.000, 3460.000, "duplex", ALL, None, ""), (3460.000, 3500.000, "broadband", ALL, 22_000_000, "")) +
    # 6 cm: the satellite rows overlap the all-modes rows as printed and are
    # not exclusive, so they are all-modes rows labelled for the satellites.
    _m((5650.000, 5670.000, "all modes, satellite uplinks", ALL, None, ""),
       (5670.000, 5760.000, "all modes", ALL, None, ""),
       (5760.000, 5760.300, "EME and weak signal", ALL, 2700, ""),
       (5760.300, 5761.000, "beacons, digital beacons", None, None, "beacon"),
       (5761.000, 5765.000, "weak signal", ALL, None, ""), (5765.000, 5830.000, "all modes", ALL, None, ""),
       (5830.000, 5850.000, "all modes, satellite downlinks", ALL, None, ""),
       (5850.000, 5925.000, "all modes", ALL, None, ""))
)

SEGMENTS: list[Seg] = sorted(HF + VHF, key=lambda s: s.lo)

# Centres of activity the plan states [N1]: (Hz, label, mode). "Image" is
# SSTV, "DV" FreeDV. 7060 is printed in the 7053-7060 row: its top edge.
CENTRES = [
    (1_812_000, "QRP CW", "cw"), (1_910_000, "SSB QRP", "lsb"),
    (3_555_000, "QRS", "cw"), (3_560_000, "QRP CW", "cw"), (3_690_000, "SSB QRP", "lsb"),
    (3_735_000, "image", "sstv"), (3_750_000, "emergency", "lsb"), (3_845_000, "image", "sstv"),
    (3_885_000, "AM", "am"), (3_985_000, "emergency", "lsb"),
    (7_030_000, "QRP CW", "cw"), (7_060_000, "R2 emergency", "lsb"), (7_070_000, "digital voice", "freedv"),
    (7_090_000, "SSB QRP", "lsb"), (7_165_000, "image", "sstv"), (7_240_000, "R2 emergency", "lsb"),
    (7_275_000, "R2 emergency", "lsb"), (7_285_000, "SSB QRP", "lsb"), (7_290_000, "AM", "am"),
    (10_116_000, "QRP CW", "cw"),
    (14_055_000, "QRS", "cw"), (14_060_000, "QRP CW", "cw"), (14_230_000, "image", "sstv"),
    (14_285_000, "SSB QRP, AM calling", "usb"), (14_300_000, "global emergency", "usb"),
    (18_086_000, "QRP CW", "cw"), (18_130_000, "QRP", "usb"), (18_160_000, "global emergency", "usb"),
    (21_060_000, "QRP CW", "cw"), (21_285_000, "SSB QRP", "usb"), (21_340_000, "image", "sstv"),
    (21_360_000, "global emergency", "usb"),
    (24_906_000, "QRP CW", "cw"), (24_950_000, "SSB QRP", "usb"),
    (28_055_000, "QRS", "cw"), (28_060_000, "QRP CW", "cw"), (28_330_000, "digital voice", "freedv"),
    (28_360_000, "SSB QRP", "usb"), (28_680_000, "image", "sstv"), (29_600_000, "FM calling", "fm"),
    (50_110_000, "DX calling", "usb"), (50_305_000, "PSK", "psk31"),
    (144_200_000, "calling", "usb"), (144_300_000, "calling", "usb"), (144_390_000, "APRS", "fm"),
    (146_520_000, "FM calling", "fm"),
    (432_100_000, "CW/SSB calling", "usb"),
    (1_294_500_000, "FM simplex calling", "fm"), (1_296_100_000, "CW/SSB calling", "usb"),
    (2_304_100_000, "calling", "usb"),
    (3_400_100_000, "EME calling", "usb"), (3_456_100_000, "calling", "usb"),
    (5_760_100_000, "calling", "usb"),
]

# The five NCDXF/IARU beacon frequencies [N1 p.8-10].
IBP = [14_100_000.0, 18_110_000.0, 21_150_000.0, 24_930_000.0, 28_200_000.0]


segment_at, overlapping = make_lookup(SEGMENTS)

# Repeater pairs (ohsradio/plans/repeaters.py), as N1 prints them
# (docs/ham/bandplan-iaru-regions.md section 4). N1 gives no channel
# spacing on 2 m, so the step is 0 (any frequency in the output range);
# its 147 MHz pairs are as printed (inputs 147.000-147.390 with outputs
# 600 kHz up), though US practice there is often the other way: the
# operator's own - and + remain for that. N1 names no 70 cm repeater
# sub-band, so 70 cm has none: auto is simplex there.
RS = _bands.RepeaterScheme
REPEATERS = [
    RS("", 29_620_000, 29_690_000, -100_000, 10_000, 0, "10 m"),
    RS("", 51_620_000, 51_980_000, -500_000, 10_000, 0, "6 m"),
    RS("", 145_200_000, 145_500_000, -600_000, 0, 0, "2 m"),
    RS("", 146_610_000, 146_970_000, -600_000, 0, 0, "2 m"),
    RS("", 147_600_000, 147_990_000, -600_000, 0, 0, "2 m"),
]
RPT_OFFSET = {"10m": 100_000, "6m": 500_000, "2m": 600_000}
