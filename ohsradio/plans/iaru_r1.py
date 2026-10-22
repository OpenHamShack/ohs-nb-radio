"""The IARU Region 1 band plan, 160 m to 6 cm, as data: the generic plan
for a Region 1 station whose country has no national plan written here
(ohsradio/plans/__init__.py choose()), and the plan used when the region
itself is unknown.

Like every IARU plan it is a voluntary code of practice that defers to
national rules: the VHF Handbook says "no right to reserved frequencies
can be derived" and advises looking "to the bandplanning of the country
of the operator" [I2 p.34]. The licence is the law; this is the fallback
when nothing nearer is known, so the guard warns outside it (or refuses,
if the operator chooses "enforce") and always refuses its beacon and
satellite-exclusive segments.

Sources, transcribed in docs/ham/bandplan-iaru-regions.md section 3,
where every row carries its page:

  I1  IARU Region 1 HF Band Plan, effective from 16 Oct 2020 (SOURCE).
      No later HF plan is published; whether Zlatibor 2023 changed it is
      unverified (that document, section 7).
  I2  IARU-R1 VHF Handbook, version 10.03, February 2026 (SOURCES): 6 m
      and up.

Decisions taken while encoding:

- Bands only some R1 countries have are left out, so a national plan
  enables them rather than this one implying them: 160 m above 1850 kHz
  (ITU footnote 5.96), 4 m (no ITU allocation; CEPT ECA9 only), 6 m above
  52 MHz (R1's allocation is 50-52), and 9 cm (5.431: Germany only).
- R1 "All modes" on HF is "CW, Phone and ... Centres of Activity, plus
  AM" [I1 p.3]: every class but FM (HF_ALL), with FM added from 29 MHz
  where the plan's bandwidth allows it.
- The plan's 2700 Hz telephony limit stands although the notes let AM
  use the telephony sub-bands "providing consideration is given to
  adjacent channel users": the guard warns, it does not refuse, which is
  the weight that note asks for.
- Guard channels and the 144.000-144.0025 MHz "no transmission" strip
  are always refused. base.KINDS has only beacon and satellite as
  always-refused kinds; each of these protects a satellite segment it
  adjoins, so they are kind "satellite" (never "beacon": the simulator
  draws beacons in beacon segments).
- Satellite segments are refused only where the plan reserves them
  (145.806-146, 435-438, 1260-1270, 2400-2450, 5650-5670, 5830-5850 MHz).
  The shared ones stay transmittable: 21125-21450 kHz ("non-exclusive"),
  29300-29510 kHz ("Satellite Links", not marked exclusive) and
  144.0025-144.025 MHz.
- Every beacon sub-band is refused, including the ones the plan does not
  call exclusive (1240.500-1240.750 MHz): no ordinary QSO traffic is
  planned there (that document, section 6, point 4).
- Repeater output sub-ranges the plan prints inside a wider row are cut
  out of it as kind "output" at the plan's own channel figures; outputs
  in a block the plan hands to national planning (430.025-430.375 MHz,
  France/Netherlands/Belgium only) are not, since marking them would warn
  every other R1 country off its own usage.
- ATV and DATV segments carry the image class: the app's image modes are
  SSTV and fax, so SSB or FM there warns, which is the plan's intent.
- Where the plan gives no bandwidth ("national", "-"), max_bw is None.
- Neither I1 nor I2 lists FT8 or other digital dial frequencies, so
  CENTRES has none: the band bar's WSJT-X dials (ohsradio/bands.py) supply
  them.

All frequencies Hz.
"""
from __future__ import annotations

from .. import bands as _bands
from .base import (ALL, CLASS_WORD, CW, FM, HF_ALL, MODE_CLASS, NARROW, NONE, WEAK, Seg,  # noqa: F401
                   make_lookup)
from .base import k as _k
from .base import m as _m

ID = "iaru-r1"
TITLE = "IARU Region 1 band plan"
SHORT = "IARU Region 1"
REGION = 1
COUNTRY = ()
SOURCE = {"title": "IARU Region 1 HF Band Plan (hf_r1_bandplan.pdf)",
          "url": "https://www.iaru-r1.org/wp-content/uploads/2021/06/hf_r1_bandplan.pdf",
          "version": "Effective from 16 Oct 2020 (Novi Sad virtual General Conference)",
          "date": "2020-10-16", "checked": "2026-10-08"}
SOURCES = [SOURCE,
           {"title": "IARU-R1 VHF Handbook (VHF_Handbook_V10_03_final.pdf)",
            "url": "https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf",
            "version": "Version 10.03, February 2026",
            # The PDF's modification date; the cover gives only the month.
            "date": "2026-02-18", "checked": "2026-10-08"}]

# "not SSB" [I1 p.4]: and so not AM either, the other wide telephony mode.
NO_SSB = HF_ALL - {"ssb", "am"}
CW_SSB = frozenset({"cw", "ssb"})
DIGI = frozenset({"digi"})
IMAGE = frozenset({"image"})

# HF, kHz [I1 p.1-2]. Rows the plan prints separately only to tag them
# (contest preferred, ACDS, DX priority) stay separate so the label says so.
HF = (
    _k((1810, 1838, "CW", CW, 200, ""), (1838, 1840, "narrow band modes", NARROW, 500, ""),
       (1840, 1843, "all modes, digimodes", HF_ALL, 2700, ""), (1843, 1850, "all modes", HF_ALL, 2700, "")) +
    # 3600-3620 (digimodes, ACDS) and 3600-3650 (SSB contest preferred)
    # overlap as printed; both are all modes at 2700 Hz, so the split is
    # only where the labels change.
    _k((3500, 3510, "CW, intercontinental priority", CW, 200, ""), (3510, 3560, "CW, contest preferred", CW, 200, ""),
       (3560, 3570, "CW", CW, 200, ""), (3570, 3580, "narrow band, digimodes", NARROW, 200, ""),
       (3580, 3590, "narrow band, digimodes", NARROW, 500, ""),
       (3590, 3600, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (3600, 3620, "all modes, digimodes, ACDS", HF_ALL, 2700, ""),
       (3620, 3650, "all modes, SSB contest preferred", HF_ALL, 2700, ""), (3650, 3700, "all modes", HF_ALL, 2700, ""),
       (3700, 3775, "all modes, SSB contest preferred", HF_ALL, 2700, ""),
       (3775, 3800, "all modes, intercontinental priority", HF_ALL, 2700, "")) +
    # 60 m: the WRC-15 band only, the plan's "proposed usage" [I1 p.3]. The
    # top 500 Hz is printed "20 (!)" Hz: weak-signal narrow modes.
    _k((5351.5, 5354, "CW, narrow band modes", NARROW, 200, ""), (5354, 5366, "all modes, USB", HF_ALL, 2700, ""),
       (5366, 5366.5, "weak signal narrow band modes", DIGI, 20, "")) +
    _k((7000, 7040, "CW", CW, 200, ""), (7040, 7047, "narrow band, digimodes", NARROW, 500, ""),
       (7047, 7050, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (7050, 7053, "all modes, digimodes, ACDS", HF_ALL, 2700, ""),
       (7053, 7060, "all modes, digimodes", HF_ALL, 2700, ""),
       (7060, 7100, "all modes, SSB contest preferred", HF_ALL, 2700, ""), (7100, 7130, "all modes", HF_ALL, 2700, ""),
       (7130, 7175, "all modes, SSB contest preferred", HF_ALL, 2700, ""),
       (7175, 7200, "all modes, intercontinental priority", HF_ALL, 2700, "")) +
    _k((10100, 10130, "CW", CW, 200, ""), (10130, 10150, "narrow band, digimodes", NARROW, 500, "")) +
    _k((14000, 14060, "CW, contest preferred", CW, 200, ""), (14060, 14070, "CW", CW, 200, ""),
       (14070, 14089, "narrow band, digimodes", NARROW, 500, ""),
       (14089, 14099, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (14099, 14101, "IBP beacons", None, None, "beacon"),
       (14101, 14112, "all modes, digimodes, ACDS", HF_ALL, 2700, ""), (14112, 14125, "all modes", HF_ALL, 2700, ""),
       (14125, 14300, "all modes, SSB contest preferred", HF_ALL, 2700, ""),
       (14300, 14350, "all modes", HF_ALL, 2700, "")) +
    _k((18068, 18095, "CW", CW, 200, ""), (18095, 18105, "narrow band, digimodes", NARROW, 500, ""),
       (18105, 18109, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (18109, 18111, "IBP beacons", None, None, "beacon"),
       (18111, 18120, "all modes, digimodes, ACDS", HF_ALL, 2700, ""), (18120, 18168, "all modes", HF_ALL, 2700, "")) +
    # 21125-21450 is also a satellite uplink "on a non-exclusive basis"
    # [I1 p.4]: shared, so nothing here changes for it.
    _k((21000, 21070, "CW", CW, 200, ""), (21070, 21090, "narrow band, digimodes", NARROW, 500, ""),
       (21090, 21110, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (21110, 21120, "all modes but SSB, digimodes, ACDS", NO_SSB, 2700, ""),
       (21120, 21149, "narrow band modes", NARROW, 500, ""), (21149, 21151, "IBP beacons", None, None, "beacon"),
       (21151, 21450, "all modes", HF_ALL, 2700, "")) +
    _k((24890, 24915, "CW", CW, 200, ""), (24915, 24925, "narrow band, digimodes", NARROW, 500, ""),
       (24925, 24929, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (24929, 24931, "IBP beacons", None, None, "beacon"),
       (24931, 24940, "all modes, digimodes, ACDS", HF_ALL, 2700, ""), (24940, 24990, "all modes", HF_ALL, 2700, "")) +
    # 10 m: all three beacon rows are "exclusively" [I1 p.2]. 29590-29610
    # (calling and parrot) has derived edges: the plan prints only spot
    # frequencies there. RH1-RH8 outputs are 29620-29690 [I1 p.4].
    _k((28000, 28070, "CW", CW, 200, ""), (28070, 28120, "narrow band, digimodes", NARROW, 500, ""),
       (28120, 28150, "narrow band, digimodes, ACDS", NARROW, 500, ""),
       (28150, 28190, "narrow band modes", NARROW, 500, ""),
       (28190, 28199, "regional time-shared beacons", None, None, "beacon"),
       (28199, 28201, "IBP beacons", None, None, "beacon"),
       (28201, 28225, "continuous-duty beacons", None, None, "beacon"),
       (28225, 28300, "all modes, beacons (shared)", HF_ALL, 2700, ""),
       (28300, 28320, "all modes, digimodes, ACDS", HF_ALL, 2700, ""), (28320, 29000, "all modes", HF_ALL, 2700, ""),
       (29000, 29100, "all modes", ALL, None, ""), (29100, 29200, "FM simplex", ALL, None, ""),
       (29200, 29300, "all modes, digimodes, ACDS", ALL, None, ""),
       (29300, 29510, "satellite links (shared)", ALL, None, ""),
       (29510, 29520, "guard channel", None, None, "satellite"),
       (29520, 29590, "FM repeater inputs", ALL, 6000, ""), (29590, 29610, "FM calling and simplex", ALL, 6000, ""),
       (29620, 29700, "repeater outputs", NONE, None, "output"))
)

# 6 m and up, MHz [I2].
VHF = (
    # 6 m [I2 p.35-36]. Note (e)'s wideband maxima are the segments' bandwidths;
    # its "50.9-50.2" is printed so, and read as 50.9-51.2, the row it sits in.
    # Outputs: 50.710-50.890 (-500 kHz pairs, Novi Sad 2020) and the older
    # +600 kHz pairs' 51.810-51.990, cut out of the 51.4-52.0 row.
    _m((50.000, 50.030, "Synchronised Beacon Project", None, None, "beacon"),
       (50.030, 50.100, "telegraphy", CW, 500, ""),
       (50.100, 50.130, "intercontinental", CW_SSB, 2700, ""), (50.130, 50.200, "international", CW_SSB, 2700, ""),
       (50.200, 50.300, "general usage", CW_SSB, 2700, ""),
       (50.300, 50.400, "MGM and narrowband telegraphy", NARROW, 2700, ""),
       (50.400, 50.500, "beacons", None, None, "beacon"),
       (50.500, 50.700, "all modes, digital communications", ALL, 50_000, ""),
       (50.700, 50.900, "repeater outputs", NONE, None, "output"),
       (50.900, 51.200, "wideband digital experiments", ALL, 200_000, ""),
       (51.200, 51.400, "repeater inputs", FM, 12_000, ""),
       (51.400, 51.810, "FM/DV simplex, all modes", ALL, 500_000, ""),
       (51.810, 51.990, "repeater outputs", NONE, None, "output"),
       (51.990, 52.000, "all modes", ALL, 500_000, "")) +
    # 2 m [I2 p.38-40]. Footnote r: "No transmission shall be made below
    # 144,0025 MHz"; the rest of the downlink segment is shared.
    _m((144.000, 144.0025, "no transmission below 144.0025", None, None, "satellite"),
       (144.0025, 144.025, "satellite downlinks (shared)", ALL, 2700, ""),
       (144.025, 144.100, "telegraphy", CW, 500, ""), (144.100, 144.150, "CW and MGM", NARROW, 500, ""),
       (144.150, 144.400, "CW, SSB and MGM", WEAK, 2700, ""), (144.400, 144.490, "beacons", None, None, "beacon"),
       (144.491, 144.493, "personal MGM beacons", DIGI, 500, ""),
       (144.500, 144.794, "all modes", ALL, 20_000, ""),
       # APRS (144.800, a CENTRES entry) is FM AFSK, so FM belongs here too.
       (144.794, 144.9625, "MGM and digital communications", frozenset({"digi", "dv", "fm"}), 12_000, ""),
       (144.975, 145.194, "repeater inputs", FM, 12_000, ""),
       (145.194, 145.206, "space communication", FM, 12_000, ""), (145.206, 145.5625, "FM/DV simplex", FM, 12_000, ""),
       (145.575, 145.7935, "repeater outputs", NONE, None, "output"),
       (145.794, 145.806, "space communication", FM, 12_000, ""),
       (145.806, 146.000, "satellites", None, None, "satellite")) +
    # 70 cm [I2 p.41-44]. 430-432 is "sub-regional (national) bandplanning".
    # 435-438 is refused whole although DATV may use 436-438: the satellite
    # service "shall have priority", and DATV is not a mode this app sends.
    _m((430.000, 431.975, "national planning", ALL, None, ""),
       (432.000, 432.400, "narrow band", ALL, 2700, ""), (432.400, 432.490, "beacons", None, None, "beacon"),
       (432.491, 432.493, "experimental MGM", DIGI, 500, ""),
       (432.500, 432.975, "all modes, APRS, repeater inputs", ALL, None, ""),
       (433.000, 433.375, "repeater inputs", FM, None, ""), (433.400, 433.5875, "FM/DV simplex", FM, None, ""),
       (433.600, 434.000, "all modes, digital communications", ALL, None, ""),
       (434.000, 434.5875, "all modes, digital communications", ALL, None, ""),
       (434.600, 434.9875, "repeater outputs", NONE, None, "output"),
       (435.000, 438.000, "satellites", None, None, "satellite"),
       (438.000, 438.650, "all modes, digital", ALL, None, ""),
       (438.650, 439.5875, "repeater outputs (7.6 MHz)", NONE, None, "output"),
       (439.5875, 440.000, "all modes, digital links", ALL, None, "")) +
    # 23 cm [I2 p.45-47]. Outputs RS1-RS28 (1242.025-1242.700) and R20-R68
    # (1258.150-1259.350) are cut out of the rows they are printed in.
    _m((1240.000, 1240.500, "narrow band (reserved for future)", ALL, 2700, ""),
       (1240.500, 1240.750, "beacons (reserved for future)", None, None, "beacon"),
       (1240.750, 1241.000, "FM/DV (reserved for future)", FM, 20_000, ""),
       (1241.000, 1242.025, "all modes, digital communications", ALL, 20_000, ""),
       (1242.025, 1242.700, "repeater outputs (RS)", NONE, None, "output"),
       (1242.700, 1243.250, "all modes, digital", ALL, 20_000, ""),
       (1243.250, 1258.150, "ATV and DATV", IMAGE, None, ""),
       (1258.150, 1259.350, "repeater outputs (R20-R68)", NONE, None, "output"),
       (1259.350, 1260.000, "ATV and DATV", IMAGE, None, ""),
       (1260.000, 1270.000, "satellite uplinks", None, None, "satellite"),
       (1270.000, 1272.000, "repeater inputs (RS), digital", ALL, 20_000, ""),
       (1272.000, 1290.994, "ATV and DATV", IMAGE, None, ""),
       (1290.994, 1291.481, "repeater inputs (RM)", FM, 20_000, ""),
       (1291.494, 1296.000, "all modes", ALL, None, ""), (1296.000, 1296.150, "telegraphy, MGM, EME", NARROW, 500, ""),
       (1296.150, 1296.800, "narrow band", WEAK, 2700, ""), (1296.800, 1296.994, "beacons", None, None, "beacon"),
       (1296.994, 1297.481, "repeater outputs (RM)", NONE, None, "output"),
       (1297.494, 1297.981, "FM/DV simplex", FM, 20_000, ""), (1298.000, 1299.000, "all modes", ALL, 20_000, ""),
       (1299.000, 1299.750, "high-speed data", ALL, 150_000, ""), (1299.750, 1300.000, "FM/DV", ALL, 20_000, "")) +
    # 13 cm [I2 p.48].
    _m((2300.000, 2320.000, "national planning", ALL, 20_000, ""), (2320.000, 2320.800, "narrow band", ALL, None, ""),
       (2320.800, 2321.000, "beacons", None, None, "beacon"), (2321.000, 2322.000, "FM/DV", FM, 20_000, ""),
       (2322.000, 2400.000, "all modes, ATV, digital", ALL, None, ""),
       (2400.000, 2450.000, "satellites", None, None, "satellite")) +
    # 9 cm is left out: no R1 allocation but Germany's (5.431).
    # 6 cm [I2 p.50].
    _m((5650.000, 5670.000, "satellite uplinks", None, None, "satellite"),
       (5670.000, 5700.000, "MGM", DIGI, None, ""), (5700.000, 5760.000, "all modes", ALL, None, ""),
       (5760.000, 5760.800, "narrow band", ALL, 2700, ""), (5760.800, 5760.990, "beacons", None, None, "beacon"),
       (5761.000, 5830.000, "all modes", ALL, None, ""),
       (5830.000, 5850.000, "satellite downlinks", None, None, "satellite"))
)

SEGMENTS: list[Seg] = sorted(HF + VHF, key=lambda s: s.lo)

# Centres of activity the plan states [I1 p.1-2; I2]: (Hz, label, mode).
# "Image" centres are SSTV, "Digital Voice" FreeDV (the app's DV mode).
# The 13 cm centre at 2400.500 MHz and the 6 cm narrowband centre at 5668.2
# MHz are left out: each is inside a satellite segment, which the guard
# refuses.
CENTRES = [
    (1_836_000, "QRP CW", "cw"),
    (3_555_000, "QRS", "cw"), (3_560_000, "QRP CW", "cw"), (3_630_000, "digital voice", "freedv"),
    (3_690_000, "SSB QRP", "lsb"), (3_735_000, "image", "sstv"), (3_760_000, "R1 emergency", "lsb"),
    (7_030_000, "QRP CW", "cw"), (7_070_000, "digital voice", "freedv"), (7_090_000, "SSB QRP", "lsb"),
    (7_110_000, "R1 emergency", "lsb"), (7_165_000, "image", "sstv"),
    (10_116_000, "QRP CW", "cw"),
    (14_055_000, "QRS", "cw"), (14_060_000, "QRP CW", "cw"), (14_130_000, "digital voice", "freedv"),
    (14_195_000, "DXpeditions", "usb"), (14_230_000, "image", "sstv"), (14_285_000, "SSB QRP", "usb"),
    (14_300_000, "global emergency", "usb"),
    (18_086_000, "QRP CW", "cw"), (18_130_000, "SSB QRP", "usb"), (18_150_000, "digital voice", "freedv"),
    (18_160_000, "emergency", "usb"),
    (21_055_000, "QRS", "cw"), (21_060_000, "QRP CW", "cw"), (21_180_000, "digital voice", "freedv"),
    (21_285_000, "SSB QRP", "usb"), (21_340_000, "image", "sstv"), (21_360_000, "global emergency", "usb"),
    (24_906_000, "QRP CW", "cw"), (24_950_000, "SSB QRP", "usb"), (24_960_000, "digital voice", "freedv"),
    (28_055_000, "QRS", "cw"), (28_060_000, "QRP CW", "cw"), (28_330_000, "digital voice", "freedv"),
    (28_360_000, "SSB QRP", "usb"), (28_680_000, "image", "sstv"), (29_600_000, "FM calling", "fm"),
    (50_050_000, "international CW centre", "cw"), (50_090_000, "intercontinental CW centre", "cw"),
    (50_110_000, "intercontinental centre", "usb"), (50_150_000, "international centre", "usb"),
    (50_285_000, "crossband", "usb"), (50_305_000, "PSK", "psk31"), (50_630_000, "DV calling", "fm"),
    (51_510_000, "FM calling", "fm"),
    (144_050_000, "CW centre", "cw"), (144_300_000, "SSB centre", "usb"), (144_500_000, "image", "sstv"),
    (144_800_000, "APRS", "fm"), (145_375_000, "DV calling", "fm"), (145_500_000, "FM calling", "fm"),
    (432_050_000, "CW centre", "cw"), (432_200_000, "SSB centre", "usb"), (432_500_000, "APRS", "fm"),
    (433_450_000, "DV calling", "fm"), (433_500_000, "FM calling", "fm"),
    (1_296_200_000, "narrowband centre", "usb"), (1_297_500_000, "FM centre", "fm"),
    (1_297_725_000, "DV calling", "fm"),
    (2_320_200_000, "SSB centre", "usb"),
    (5_760_200_000, "narrowband centre", "usb"),
]

# The five NCDXF/IARU beacon frequencies (the IBP slots' centres) [I1 p.1-2].
IBP = [14_100_000.0, 18_110_000.0, 21_150_000.0, 24_930_000.0, 28_200_000.0]


segment_at, overlapping = make_lookup(SEGMENTS)

# Repeater pairs (ohsradio/plans/repeaters.py), from the rows of
# docs/ham/bandplan-iaru-regions.md section 3 that print the pairing. Where
# the plan gives no channel spacing the step is 0: any frequency in the
# output range is a channel. Channel names only where the handbook uses
# them (RV, RM, RS); the 70 cm 7.6 MHz pairs are left unnamed.
RS = _bands.RepeaterScheme
REPEATERS = [
    RS("RH", 29_620_000, 29_690_000, -100_000, 10_000, 1),            # RH1-RH8 [I1 p.4]
    RS("", 50_710_000, 50_890_000, +500_000, 0, 0, "6 m, the -500 kHz option (Novi Sad 2020)"),
    RS("", 51_810_000, 51_990_000, -600_000, 0, 0, "6 m, the older 600 kHz option"),
    RS("RV", 145_600_000, 145_787_500, -600_000, 12_500, 48),        # "Repeater Output exclusive" [I2]
    RS("", 438_650_000, 439_587_500, -7_600_000, 12_500, 0, "70 cm, 7.6 MHz pairs"),
    RS("RS", 1_242_025_000, 1_242_700_000, +28_000_000, 25_000, 1),   # RS1-RS28, inputs 1270.025-
    RS("RM", 1_297_000_000, 1_297_475_000, -6_000_000, 25_000, 0),    # RM0-RM19
]
RPT_OFFSET = {"10m": 100_000, "6m": 500_000, "2m": 600_000, "70cm": 7_600_000, "23cm": 6_000_000}
