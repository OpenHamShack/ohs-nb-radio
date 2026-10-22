"""Repeater pairs by plan and by country: which way, and how far, "auto"
shifts the transmit dial from a repeater's output (ohsradio/radio.py shift).

Why a table of its own. The direction of a repeater shift is national,
never inherited from the IARU channel name (docs/ham/countries/README.md
point 12): on 70 cm Germany's inputs are 7.6 MHz below the outputs and
Ireland's above; France, Italy, the Netherlands and Belgium have outputs
at 430.025-430.375 MHz with inputs 1.6 MHz *above*; the UK's RB pairs run
the reverse of IARU R1's. One per-band constant (bands.py rpt_offset, as
before 08/10/2026) is right in one country at most.

A plan module may carry its own REPEATERS (the RSGB's and IARU R1's do).
A country whose national band plan is not written as segments can still
have its pairs here, in BY_COUNTRY, cited to its national plan: the
segments then come from the region's IARU plan and the pairs from here.

Each entry: {"schemes": [bands.RepeaterScheme], "offsets": {band name:
Hz}, "src": "..."}. `offsets` is the split a band arrival sets for the
operator's manual - and + (bands.Band.rpt_offset is the UK's).

Where nothing is known, auto is simplex (0): a guess at a direction would
put the transmitter on another repeater's output.
"""
from __future__ import annotations

from .. import bands

RS = bands.RepeaterScheme

# Countries whose pairs are known but whose national plan is not written
# as segments: each from section 7 of docs/ham/countries/<iso>.md, only
# where the research states the direction (its [derived] pairings are left
# out). Input = output + shift. Encoded 08/10/2026.
BY_COUNTRY: dict[str, dict] = {
    "IE": {"src": "ie.md s.7: IRTS repeater list (R2), IRTS band plan V3.0 (R1)",
           "schemes": [RS("RV", 145_600_000, 145_787_500, -600_000, 12_500, 48),
                       RS("RU", 430_825_000, 430_975_000, +7_600_000, 12_500, 66, "Irish: input 7.6 MHz above"),
                       RS("RU", 433_000_000, 433_350_000, +1_600_000, 12_500, 240)],
           "offsets": {"2m": 600_000, "70cm": 7_600_000}},
    "DE": {"src": "de.md s.7: DARC B2 (08/2017), B70 (08/2017, 05/2025), B23 (11/2011), BHF, B6 (04/2026)",
           "schemes": [RS("", 29_620_000, 29_690_000, -100_000, 10_000, 0),
                       RS("", 51_810_000, 51_990_000, -600_000, 20_000, 0),
                       RS("RV", 145_575_000, 145_787_500, -600_000, 12_500, 46),
                       RS("", 438_200_000, 438_537_500, -7_600_000, 12_500, 0, "DV/packet"),
                       RS("", 438_550_000, 439_437_500, -7_600_000, 12_500, 0, "NBFM"),
                       RS("", 439_450_000, 439_587_500, -7_600_000, 12_500, 0, "DV"),
                       RS("", 439_812_500, 439_975_000, -9_400_000, 12_500, 0),
                       RS("RS", 1_242_025_000, 1_242_700_000, +28_000_000, 25_000, 1),
                       RS("RS", 1_298_025_000, 1_298_975_000, -28_000_000, 25_000, 1)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "70cm": 7_600_000, "23cm": 28_000_000}},
    "NL": {"src": "nl.md s.7: RDI Gedragslijn (June 2021)",
           "schemes": [RS("RV", 145_600_000, 145_787_500, -600_000, 12_500, 48),
                       RS("", 430_012_500, 430_375_000, +1_600_000, 12_500, 0),
                       RS("", 438_000_000, 438_500_000, -7_600_000, 12_500, 0),
                       RS("", 1_297_962_500, 1_299_000_000, -28_000_000, 0, 0)],
           "offsets": {"2m": 600_000, "70cm": 1_600_000}},
    "BE": {"src": "be.md s.7: UBA repeater list (U3, 2023)",
           "schemes": [RS("RF", 51_870_000, 51_990_000, -600_000, 10_000, 87),
                       RS("RV", 145_575_000, 145_787_500, -600_000, 12_500, 46),
                       RS("RU", 430_075_000, 430_375_000, +1_600_000, 12_500, 6),
                       RS("RU", 438_200_000, 439_525_000, -7_600_000, 12_500, 656),
                       RS("RS", 1_298_225_000, 1_298_700_000, -28_000_000, 25_000, 9)],
           "offsets": {"6m": 600_000, "2m": 600_000, "70cm": 1_600_000}},
    "FR": {"src": "fr.md s.7: REF band plans (HF 2016/2021, VHF+ 2017)",
           "schemes": [RS("RH", 29_620_000, 29_690_000, -100_000, 10_000, 1),
                       RS("", 51_810_000, 51_990_000, -600_000, 20_000, 0),
                       RS("RV", 145_575_000, 145_787_500, -600_000, 12_500, 46),
                       RS("", 430_025_000, 430_375_000, +1_600_000, 12_500, 0),
                       RS("", 439_800_000, 439_975_000, -9_400_000, 0, 0),
                       RS("RS", 1_242_025_000, 1_242_700_000, +28_000_000, 25_000, 1),
                       RS("RM", 1_297_000_000, 1_297_475_000, -6_000_000, 25_000, 0)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "70cm": 1_600_000}},
    "ES": {"src": "es.md s.7: URE band plan",
           "schemes": [RS("", 29_620_000, 29_690_000, -100_000, 0, 0),
                       RS("", 51_810_000, 51_990_000, -600_000, 20_000, 0),
                       RS("", 145_575_000, 145_787_500, -600_000, 12_500, 0),
                       RS("", 434_600_000, 434_975_000, -1_600_000, 0, 0),
                       RS("", 1_296_994_000, 1_297_481_000, -6_000_000, 0, 0),
                       RS("", 1_298_000_000, 1_298_500_000, -28_000_000, 0, 0)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "70cm": 1_600_000, "23cm": 6_000_000}},
    # Italy's two 70 cm systems run in opposite directions, so no 70 cm
    # offset is set on arrival: auto knows each pair, - and + are typed.
    "IT": {"src": "it.md s.7: ARI band plan (VHF+ Rev 0.6, 2018)",
           "schemes": [RS("", 29_620_000, 29_690_000, -100_000, 0, 0),
                       RS("", 51_810_000, 51_990_000, -600_000, 20_000, 0),
                       RS("", 145_575_000, 145_787_500, -600_000, 12_500, 0),
                       RS("RU", 430_025_000, 430_375_000, +1_600_000, 12_500, 2),
                       RS("RU", 432_825_000, 433_200_000, -1_600_000, 12_500, 226),
                       RS("RS", 1_242_025_000, 1_243_250_000, +28_000_000, 25_000, 1),
                       RS("", 1_296_994_000, 1_297_481_000, -6_000_000, 0, 0)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "23cm": 28_000_000}},
    "NO": {"src": "no.md s.7: NRRL band plans (2018/2019)",
           "schemes": [RS("RF", 51_810_000, 51_990_000, -600_000, 0, 0),
                       RS("", 145_575_000, 145_787_500, -600_000, 12_500, 0),
                       RS("", 434_600_000, 434_975_000, -2_000_000, 12_500, 0),
                       RS("RS", 1_242_025_000, 1_243_250_000, +28_000_000, 25_000, 1),
                       RS("R", 1_258_150_000, 1_259_350_000, +35_000_000, 25_000, 20),
                       RS("RM", 1_297_000_000, 1_297_475_000, -6_000_000, 25_000, 0)],
           "offsets": {"6m": 600_000, "2m": 600_000, "70cm": 2_000_000, "23cm": 6_000_000}},
    "SE": {"src": "se.md s.7: SSA HF v3.3, VUHF v3.2 (30 Sep 2025)",
           "schemes": [RS("RH", 29_620_000, 29_690_000, -100_000, 10_000, 1),
                       RS("RF", 51_810_000, 51_990_000, -600_000, 10_000, 81),
                       RS("RV", 145_575_000, 145_787_500, -600_000, 12_500, 46),
                       RS("", 434_500_000, 434_575_000, -2_000_000, 0, 0, "NRAU digital"),
                       RS("RU", 434_600_000, 434_975_000, -2_000_000, 12_500, 368,
                          "older repeaters use -1.6 MHz: set by hand"),
                       RS("RM", 1_297_000_000, 1_297_475_000, -6_000_000, 25_000, 0)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "70cm": 2_000_000, "23cm": 6_000_000}},
    "DK": {"src": "dk.md s.7: BEK 499/2026 Bilag 4 1.4 notes 6-12; EDR band plan",
           "schemes": [RS("RF", 51_810_000, 51_990_000, -600_000, 10_000, 81),
                       RS("", 70_487_500, 70_512_500, -600_000, 0, 0),
                       RS("RV", 145_575_000, 145_787_500, -600_000, 12_500, 46),
                       RS("RU", 434_600_000, 434_987_500, -2_000_000, 12_500, 368),
                       RS("", 437_912_500, 437_962_500, -4_600_000, 25_000, 0, "digital"),
                       RS("RS", 1_242_025_000, 1_242_700_000, +28_000_000, 25_000, 1),
                       RS("RM", 1_297_000_000, 1_297_475_000, -6_000_000, 25_000, 0,
                          "-6 MHz ends 1 Jan 2029; -40 MHz also authorised")],
           "offsets": {"6m": 600_000, "4m": 600_000, "2m": 600_000, "70cm": 2_000_000, "23cm": 6_000_000}},
    "FI": {"src": "fi.md s.7: written into Radioamatöörimääräys 6 K/2019M (F1)",
           "schemes": [RS("", 29_620_000, 29_690_000, -100_000, 10_000, 0),
                       RS("RF", 51_810_000, 51_990_000, -600_000, 20_000, 81),
                       RS("", 145_575_000, 145_787_500, -600_000, 12_500, 0),
                       RS("", 434_500_000, 434_587_500, -2_000_000, 12_500, 0),
                       RS("", 434_600_000, 434_987_500, -2_000_000, 12_500, 0),
                       RS("", 438_062_500, 438_162_500, -5_000_000, 12_500, 0)],
           "offsets": {"10m": 100_000, "6m": 600_000, "2m": 600_000, "70cm": 2_000_000}},
    "US": {"src": "us.md s.9: ARRL band plan (pairs from its ranges)",
           "schemes": [RS("", 51_620_000, 51_980_000, -500_000, 20_000, 0),
                       RS("", 52_500_000, 52_980_000, -500_000, 0, 0),
                       RS("", 53_500_000, 53_980_000, -500_000, 0, 0),
                       RS("", 145_200_000, 145_500_000, -600_000, 0, 0),
                       RS("", 146_610_000, 146_970_000, -600_000, 0, 0),
                       RS("", 147_000_000, 147_390_000, +600_000, 0, 0),
                       RS("", 927_000_000, 927_075_000, -25_000_000, 0, 0),
                       RS("", 927_125_000, 928_000_000, -25_000_000, 0, 0),
                       RS("", 1_282_000_000, 1_288_000_000, -12_000_000, 25_000, 0)],
           "offsets": {"6m": 500_000, "2m": 600_000, "23cm": 12_000_000}},
    "CA": {"src": "ca.md, band plan section: RAC band plans",
           "schemes": [RS("", 53_000_000, 54_000_000, -1_000_000, 0, 0),
                       RS("", 145_100_000, 145_500_000, -600_000, 0, 0),
                       RS("", 146_610_000, 146_970_000, -600_000, 0, 0),
                       RS("", 147_000_000, 147_390_000, +600_000, 0, 0),
                       RS("", 223_910_000, 224_970_000, -1_600_000, 0, 0),
                       RS("", 442_000_000, 445_000_000, +5_000_000, 0, 0),
                       RS("", 919_000_000, 922_000_000, -12_000_000, 0, 0),
                       RS("", 1_282_000_000, 1_288_000_000, -12_000_000, 0, 0)],
           "offsets": {"6m": 1_000_000, "2m": 600_000, "70cm": 5_000_000, "23cm": 12_000_000}},
    "AU": {"src": "au.md, band plan section: WIA band plan 2026",
           "schemes": [RS("", 29_610_000, 29_690_000, -100_000, 0, 0),
                       RS("", 53_550_000, 54_000_000, -1_000_000, 25_000, 0),
                       RS("", 144_887_500, 145_062_500, +600_000, 0, 0, "Block C"),
                       RS("", 146_612_500, 147_000_000, -600_000, 0, 0, "Block A"),
                       RS("", 147_012_500, 147_387_500, +600_000, 0, 0, "Block B"),
                       RS("", 438_000_000, 438_937_500, -7_000_000, 0, 0, "Block A"),
                       RS("", 439_612_500, 440_000_000, -7_000_000, 0, 0, "Block B; -5 MHz alternative"),
                       RS("", 2_425_000_000, 2_426_000_000, -20_000_000, 0, 0),
                       RS("", 3_356_000_000, 3_357_000_000, +40_000_000, 0, 0),
                       RS("", 5_730_000_000, 5_735_000_000, +40_000_000, 100_000, 0)],
           "offsets": {"10m": 100_000, "6m": 1_000_000, "2m": 600_000, "70cm": 7_000_000}},
    "NZ": {"src": "nz.md, band plan section: NZART band plan chart (June 2026)",
           "schemes": [RS("", 29_620_000, 29_680_000, -100_000, 0, 0),
                       RS("", 145_325_000, 145_775_000, -600_000, 25_000, 0),
                       RS("", 146_625_000, 147_000_000, -600_000, 25_000, 0),
                       RS("", 147_025_000, 147_375_000, +600_000, 25_000, 0),
                       RS("", 438_000_000, 440_000_000, -5_000_000, 0, 0, "7 MHz, or a positive offset, by arrangement"),
                       RS("", 1_290_000_000, 1_294_000_000, -20_000_000, 0, 0),
                       RS("", 2_425_000_000, 2_427_000_000, -20_000_000, 0, 0)],
           "offsets": {"10m": 100_000, "2m": 600_000, "70cm": 5_000_000, "23cm": 20_000_000}},
}


def for_station(plan, iso: str = "", chosen: bool = False) -> tuple[list, dict]:
    """(schemes, offsets) in force: the plan's own when the operator chose
    the plan or it is the station country's national plan; else the
    country's pairs from BY_COUNTRY; else the plan's (an IARU plan's); else
    none."""
    national = iso and iso in getattr(plan, "COUNTRY", ())
    if not chosen and not national and iso in BY_COUNTRY:
        entry = BY_COUNTRY[iso]
        return list(entry["schemes"]), dict(entry.get("offsets", {}))
    return list(getattr(plan, "REPEATERS", [])), dict(getattr(plan, "RPT_OFFSET", {}))


def validate(schemes: list, where: str) -> list[str]:
    """Problems with a list of schemes: edges, a step that divides the
    range, outputs that do not overlap."""
    p = []
    for r in schemes:
        if not r.out_lo <= r.out_hi:
            p.append(f"{where} {r.name or r.out_lo}: output range is upside down")
        if r.step < 0 or (r.step and abs(round((r.out_hi - r.out_lo) / r.step) * r.step - (r.out_hi - r.out_lo)) > 1):
            p.append(f"{where} {r.name or r.out_lo}: the step does not divide the output range")
        if not r.shift:
            p.append(f"{where} {r.name or r.out_lo}: a repeater scheme with no shift is simplex")
    spans = sorted((r.out_lo, r.out_hi) for r in schemes)
    for a, b in zip(spans, spans[1:]):
        if b[0] <= a[1]:
            p.append(f"{where}: output ranges {a} and {b} overlap")
    return p
