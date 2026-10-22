"""The Irish amateur licence (ComReg): who may transmit where, at what power.

Source: ComReg 09/45R6, "Amateur Station Licence Guidelines" (29/05/2023)
[C1], Annex 1 Tables 2 (HF, pp.20-23) and 3 (VHF and up, pp.23-26) and the
additional bands of A1.5 (p.27), as transcribed in
docs/ham/countries/ie.md section 3. S.I. No. 192 of 2009 reg. 7(1)(b) puts
the bands and powers in Part 2 of each licence; 09/45R6 is where ComReg
publishes them, and ComReg's own page (modified 2026-05-08) still links R6
as current. Nobody has yet done the line-by-line check the UK had
(docs/ham/licence-check.md): do it against the PDF before relying on this.

Both classes have exactly the same bands and powers - "The frequency bands
specified in Tables 2 and 3 below are available for both CEPT Class 1 &
CEPT Class 2 Licence types" [C1 A1.2 p.19]; Morse is the only difference.
Both are kept so a class 2 call (suffix ending in B) can hint its class.

Power is PEP "measured at the output of the transmitter or R.F. Power
Amplifier" [C1 A2.10 p.30], except the rows the table gives in e.i.r.p.
(2200 m, 630 m, the WRC-15 60 m band).

What is left out, and why (ie.md sections 3.1 and 8):
- 60 m spot frequencies (5.280 ... 5.405 MHz, 200 W PEP): the licence does
  not say whether a spot frequency is the carrier or the channel centre, nor
  how wide a channel is [UNCONFIRMED], so outside the WRC-15 band 60 m is
  refused rather than given a guessed channel.
- 1300-1304 MHz, by individual application for repeaters, is printed as
  "0W (0 dBW)", which contradicts itself: refused.
- 4 m mobile: the row says "Fixed Operation Only" and also gives a mobile
  power [UNCONFIRMED]: the row is encoded at its fixed 50 W PEP, and the
  mobile rules are NOTES.
- The contest power uplift on ComReg's web page has no power reference
  [UNCONFIRMED] and no dates: not encoded, shown as a NOTE.
- Mobile (/M) 50 W, maritime mobile (/MM) 10 W and harbour-island 50 W
  limits are NOTES, not CONDITIONS: they depend on how the station is being
  operated, and a condition defaulted to its restrictive answer would hold
  every fixed Irish station to 10 W and off 6 m and 70 cm. That is a
  decision for whoever owns the interface (the UK's airborne rule is a NOTE
  for the same reason).
"""
from __future__ import annotations

ID = "comreg-2023"
TITLE = "ComReg amateur station licence (09/45R6, 2023)"
SHORT = "Ireland (ComReg)"
AUTHORITY = "ComReg"
COUNTRY = ("IE",)
PLAN = ""
# [C1] in docs/ham/countries/ie.md.
SOURCE = {
    "title": "ComReg 09/45R6, Amateur Station Licence Guidelines, Annex 1 Tables 2 and 3",
    "url": "https://www.comreg.ie/media/2023/05/ComReg-0945R6.pdf",
    "version": "09/45R6, dated 29/05/2023 (still linked as current by ComReg's page modified 2026-05-08)",
    "date": "2023-05-29",
    "checked": "2026-10-08",
    "sha256": "9c6252ab5677f155726fcd71649593b4a125b245268db5e9bd28242ea280e3cb",
}
CLASSES = ("cept1", "cept2")
CLASS_NAME = {"cept1": "CEPT Class 1", "cept2": "CEPT Class 2"}

_P, _I = "PEP", "EIRP"


# One limit for both classes, since C1 A1.2 gives them the same table.
def _r(lo_khz, hi_khz, watts, unit=_P, note="", src="C1 T2", **extras):
    lim = (float(watts), unit)
    row = (lo_khz * 1e3, hi_khz * 1e3, {"cept1": lim, "cept2": lim}, note, src)
    return row + (extras,) if extras else row


# Every power is the dBW figure the table prints with it (26 dBW = 400 W,
# 22 dBW = 158 W, 17 dBW = 50 W).
ALLOCATIONS = [
    _r(135.7, 137.8, 1, _I, "secondary", "C1 T2 p.20"),
    _r(472, 479, 5, _I, "secondary; no harmful interference to aeronautical radionavigation or maritime",
       "C1 T2 p.20"),
    _r(1810, 1850, 400, note="primary", src="C1 T2 p.21"),
    _r(1850, 2000, 10, note="primary", src="C1 T2 p.21"),
    _r(3500, 3800, 400, note="primary; maritime mobile permitted", src="C1 T2 p.21"),
    # 60 m: the WRC-15 band only; the spot channels are REFUSED below.
    _r(5351.5, 5366.5, 15, _I, "secondary (RR 5.133B)", "C1 T2 pp.21-22"),
    _r(7000, 7200, 400, note="primary; maritime mobile permitted", src="C1 T2 p.22"),
    _r(10100, 10130, 400, note="secondary; Morse only (EMISSIONS)", src="C1 T2 p.22"),
    _r(10130, 10150, 400, note="secondary; narrowband digimodes up to 500 Hz (EMISSIONS)", src="C1 T2 p.22"),
    _r(14000, 14350, 400, note="primary; maritime mobile permitted", src="C1 T2 p.22"),
    _r(18068, 18168, 400, note="primary", src="C1 T2 p.23"),
    _r(21000, 21450, 400, note="primary", src="C1 T2 p.23"),
    _r(24890, 24990, 400, note="primary", src="C1 T2 p.23"),
    _r(28000, 29700, 400, note="primary", src="C1 T2 p.23"),
    _r(30000, 49000, 50, note="secondary (the whole 30-49 MHz range)", src="C1 T3 p.23"),
    _r(50000, 52000, 100, note="secondary", src="C1 T3 p.24"),
    _r(54000, 69900, 50, note="secondary", src="C1 T3 p.24"),
    _r(69900, 70500, 50, note="secondary; fixed operation only (mobile: see NOTES)", src="C1 T3 p.24"),
    _r(144000, 146000, 400, note="primary; maritime mobile permitted", src="C1 T3 p.24"),
    _r(430000, 432000, 50, note="primary", src="C1 T3 p.24"),
    _r(432000, 440000, 400, note="primary", src="C1 T3 p.24"),
    _r(1240000, 1300000, 158, note="secondary", src="C1 T3 p.24"),
    _r(2300000, 2400000, 158, note="secondary", src="C1 T3 p.24"),
    # An additional band by individual application, satellite only, for at
    # most twelve months [C1 A1.5 p.27, 3.8]: the permit is CONDITIONS below.
    _r(2400000, 2450000, 25, note="secondary; by individual application; satellite operation only",
       src="C1 A1.5 p.27", satellite_only=True),
    _r(5570000, 5650000, 158, note="secondary", src="C1 T3 p.24"),
    _r(5650000, 5850000, 158, note="secondary", src="C1 T3 p.24"),
    _r(10000000, 10270000, 158, note="secondary", src="C1 T3 p.25"),
    _r(10300000, 10500000, 158, note="secondary; 10450-10500 MHz used for the amateur-satellite service",
       src="C1 T3 p.25"),
    _r(24000000, 24050000, 50, note="primary", src="C1 T3 p.25"),
    _r(47000000, 47200000, 50, note="primary", src="C1 T3 p.25"),
    _r(76000000, 77500000, 50, note="secondary", src="C1 T3 p.25"),
    _r(77500000, 78000000, 50, note="primary", src="C1 T3 p.25"),
    _r(78000000, 81000000, 50, note="secondary", src="C1 T3 p.25"),
    _r(134000000, 136000000, 50, note="primary", src="C1 T3 p.25"),
    _r(136000000, 141000000, 50, note="secondary", src="C1 T3 p.25"),
    _r(241000000, 248000000, 50, note="secondary", src="C1 T3 p.25"),
    _r(248000000, 250000000, 50, note="primary", src="C1 T3 p.26"),
]

# 30 m is law, not band plan [C1 T2 p.22]: "Morse Only" below 10130 kHz,
# narrowband digimodes of at most 500 Hz above it. The upper row names
# digimodes only, so Morse there is not assumed; SSB "only in safety-of-life
# emergencies" is not something OpenHamShack transmits, so it is not opened.
_BOTH = ("cept1", "cept2")
EMISSIONS = [
    (10100e3, 10130e3, {c: frozenset({"cw"}) for c in _BOTH}, None, "Morse only", "C1 T2 p.22"),
    (10130e3, 10150e3, {c: frozenset({"digi"}) for c in _BOTH}, 500.0, "narrowband digimodes up to 500 Hz",
     "C1 T2 p.22"),
]

REFUSED = [
    (5250e3, 5351.5e3, "Below 5351.5 kHz, Irish 60 m use is only on spot frequencies, and the licence does not say "
                       "whether a spot frequency is the carrier or the centre of the channel, nor how wide a channel "
                       "is: OpenHamShack refuses them until that is confirmed", "C1 T2 p.21; ie.md s.3.1, s.8"),
    (5366.5e3, 5450e3, "Above 5366.5 kHz, Irish 60 m use is only on spot frequencies, and the licence does not say "
                       "whether a spot frequency is the carrier or the centre of the channel, nor how wide a channel "
                       "is: OpenHamShack refuses them until that is confirmed", "C1 T2 p.21; ie.md s.3.1, s.8"),
    (1300e6, 1304e6, "1300-1304 MHz is for repeaters by individual application, and the licence's power for it "
                     "(\"0W (0 dBW)\") contradicts itself: OpenHamShack does not transmit there", "C1 A1.5 p.27"),
    (10_270e6, 10_300e6, "The Irish licence excludes 10.270-10.300 GHz", "C1 T3 p.25"),
]

CONDITIONS = [{"key": "holdsComRegSatellitePermit", "lo": 2400e6, "hi": 2450e6,
               "label": "I hold a ComReg authorisation for 2400-2450 MHz (satellite)",
               "default": False, "when": False,
               "refuse": ("2400-2450 MHz needs an individual authorisation from ComReg, for satellite operation "
                          "only; tick it in Settings › Licence & plan if you hold one"),
               "src": "C1 A1.5 p.27, 3.8"}]

# Only two satellite ranges are in the licence: the 13 cm additional band
# ("Restricted to Satellite Operation Only") and 10450-10500 MHz ("used for
# Amateur Satellite Service"); neither gives a direction.
SATELLITE = [(2400e6, 2450e6, "both", "C1 A1.5 p.27"),
             (10_450e6, 10_500e6, "both", "C1 T3 p.25")]

# ComReg recognises T/R 61-01 only: "does not recognise novice or
# intermediate licences" [C1 3.2; C2]; Ireland is listed in T/R 61-01
# Annex 2 as "EI, EJ - 1 and 2" [CT1 p.6] and absent from ECC/REC/(05)06.
CEPT = {"T/R 61-01": ("cept1", "cept2")}
CEPT_SRC = ("ComReg 09/45R6 s.3.1-3.4; ComReg 'Radio Amateurs' page (modified 2026-05-08); "
            "CEPT T/R 61-01 Annex 2 (16 Feb 2024) p.6")
# Which class a T/R 61-01 visitor holds is not stated; both have the same
# bands, so the operator's choice changes nothing.
CEPT_VISITOR: dict = {}

NOTES = [
    ("mobile", "Mobile (/M) stations may use at most 50 W (17 dBW) PEP, and not within any estuary, dock or harbour "
               "or near an airport. Shown, not enforced.", "C1 Note 7 p.27, 5.5"),
    ("mobile", "4 m mobile operation: the licence says both \"Fixed Operation Only\" and 25 W PEP for mobile use, "
               "so OpenHamShack applies the fixed 50 W PEP and does not judge mobile use.", "C1 T3 p.24, Note 7 p.27"),
    ("maritime", "Maritime mobile (/MM, inland waterways included) is permitted only on 80, 40, 20, 17, 15, 12 and "
                 "10 m and 2 m, at most 10 W (10 dBW). Shown, not enforced.", "C1 Note 8 p.27, 5.7"),
    ("location", "Stations on islands within harbour areas (such as Spike Island) are limited to 50 W (17 dBW) PEP. "
                 "Shown, not enforced.", "C1 Note 2 p.26"),
    ("contest", "ComReg's web page allows 1500 W on some HF bands and 1000 W on some VHF/UHF bands during listed "
                "contests; it gives no power reference and no dates, so OpenHamShack does not apply it.",
     "ComReg 'Radio Amateurs' page (modified 2026-05-08)"),
]
