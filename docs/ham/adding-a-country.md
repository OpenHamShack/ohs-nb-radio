# Adding a country

How to teach OpenHamShack Radio and OpenHamShack QO-100 NB another country's amateur licence,
and optionally its band plan and repeater pairs. Written 08/10/2026, when
the apps stopped assuming the UK.

The contract itself is code, and wins where this page disagrees with it:

- the licence regime: the docstring of `ohscore/licences/__init__.py`, and
  its `validate()`;
- the band plan: the docstring of `ohsradio/plans/base.py`, and its
  `validate()`;
- repeater pairs: `ohsradio/plans/repeaters.py`.

`ohscore/licences/ofcom.py` (the UK) is the worked example of a regime;
`ohsradio/plans/iaru_r1.py` of a plan.

## What happens before a country is added

The station's country comes from the callsign (`ohscore/countries.py`:
EA8/GM4BRI is in the Canary Islands) or the Station setting. A country
whose licence is not written gets the IARU plan of its region, and
**transmit stays locked**, with a sentence saying how to unlock it: the
operator chooses a written licence, or enters their own segments and
power limits (Settings › Licence & plan › Your own licence, the
`customLicence` setting). Receive always works.

Nothing about a country is ever guessed. That is the rule the rest of this
page serves.

## 1. Research first, with sources

Each country has a research file, `docs/ham/countries/<iso>.md`, in the
template the existing fifteen use: sources (with the SHA-256 of every
downloaded document), regulator and instruments, classes, a power table
per sub-allocation with the source's own wording, satellite/QO-100, CEPT,
callsigns, national band plan, and a confidence and gaps section.
`docs/ham/countries/README.md` indexes them and lists what differs
between countries.

**Anything the research marks [UNCONFIRMED] is encoded as refused, never
as a guess** - not even as the "probable" reading. The operator who knows
better can enter their own licence; a wrong guess would let a transmitter
key where it may not.

Before a country's table is relied on, somebody should do the line-by-line
check the UK had (`docs/ham/licence-check.md`): every row against the PDF
it cites, by page.

## 2. The licence regime: `ohscore/licences/<id>.py`

One module per regulator and edition. The ID names both (`bnetza-2024`);
a new edition is a new ID, so a config naming the old one is noticed.
Frequencies are Hz, powers watts. Write rows in kHz or MHz through a small
helper, as `ofcom.py` does, if it reads better.

Required: `ID`, `TITLE`, `SHORT` (the Settings choice), `AUTHORITY`,
`COUNTRY` (ISO codes), `SOURCE` (title, url, version, ISO date, ISO date
last checked, sha256), `CLASSES` (lowest first), `CLASS_NAME`,
`ALLOCATIONS`.

**An allocation row** is `(lo, hi, {class: limit}, note, source[, extras])`.
A class missing from a row may not transmit there. Rows never overlap,
unless they can never apply together (different ITU regions, dates that do
not meet). `source` is the page or clause, so a reader can find it.

**A limit** is `(watts, unit)`, unit one of PEP, mean, carrier, ERP, EIRP.
What the research found that needs more:

| The law says | Encode |
|---|---|
| A figure per mode (CA Basic 560 W PEP SSB, 190 W carrier otherwise; AU pX/pY) | a tuple of `Limit(watts, unit, modes)`, every mode class covered; the strictest applies when the mode is unknown |
| Two caps at once (FI: carrier and PEP above 30 MHz; UK 60 m: 100 W PEP and 200 W EIRP) | a tuple of `Limit`s with no `modes`: all apply |
| "Output power" with no reference | PEP at the transmitter, said in the row's note |
| A figure with no stated unit or reference, marked UNCONFIRMED | the row with `{"unconfirmed": True}`: refused |
| ERP / EIRP | that unit; the guard computes it from the operator's antenna gain |
| Half power where amateurs are secondary (ES) | the halved figure, the derivation in the note |

**Extras**, a dict as the sixth element:

- `valid_from` / `valid_to` (ISO dates): ES's QO-100 resolution to
  2026-12-26, NZ 3400-3410 MHz to 2027-06-30, the 23 cm ECC (25)01 dates.
  An expired row is refused.
- `regions` (ITU regions the row applies in): US Region 3 territories.
- `unconfirmed: True`: refused with a sentence saying so.
- `satellite_only: True`: amateur-satellite service only (NL 2400-2450
  MHz, IT 145.8-146 MHz). HAM refuses it; NB's uplink check allows it. It
  needs a `SATELLITE` row too.

**Optional tables** (absent means the licence says nothing of the kind):

- `CHANNELLED` - an allocation usable only in listed channels (60 m).
- `EMISSIONS` - per-class mode classes and maximum bandwidth on a range
  (DE 2.7 kHz on most HF, IE 30 m CW below 10.130 MHz, FR class 3's
  emission list).
- `REFUSED` - ranges refused for every class, each with its whole
  sentence (gaps inside a nominal band; anything the research says to
  refuse).
- `CONDITIONS` - a yes/no about the station, answered in Settings and
  stored in `stationConditions`: where the answer is `when`, the range is
  refused (`refuse`) or held to a lower `Limit` (`limit`). **The default
  is the restrictive answer.** This is how to encode:
  - a band needing **separate permission** (IE 2400-2450 MHz, ES most of
    13 cm and 5.7 GHz, FI 23 cm, SE QO-100 above 100 mW): key
    `holdsXxxPermit`, default False, when False, refuse "...needs a
    separate permit from <regulator>; tick it in Settings if you hold
    one";
  - a **location** rule (FI's border zones, AU's quiet zone, the US
    White Sands box): default to the answer that refuses or limits.
- `SATELLITE` - where the amateur-satellite service is permitted, and in
  which direction. **OpenHamShack QO-100 NB transmits to QO-100 only where this has
  an "up" or "both" row over 2400.050-2400.300 MHz and the class holds the
  allocation there**; a class with no 13 cm (DE N, NL N, BE B and C, FR
  class 3, SE insteg, DK D) therefore locks NB's transmit.
- `CEPT`, `CEPT_SRC`, `CEPT_VISITOR` - which classes are CEPT licences,
  and what a visiting CEPT licence becomes here.
- `NOTES` - beacon, repeater, unattended, airborne rules: shown, not
  enforced.
- `EDGES` - "lower-open" for AU's (lower, upper] bands; the guard reads
  either the same, since a signal must lie wholly inside.
- `PLAN` - the national band plan's id, "" for none.

Every sentence a regime supplies is whole, with names put in by
`format()`, never assembled from fragments: they will be translated.

**Register it** in `REGIMES` in `ohscore/licences/__init__.py`.

## 3. The country: `ohscore/countries.py`

Add a `Country` to `WRITTEN`: ISO code, name, regulator, the DXCC
entities its rules cover (primary prefixes as cty.dat gives them - the UK
is eight), its regime ids (the first is the default), its national plan
id or "", and its ITU region. Cite where the regulator says which
territories the licence covers; leave out an entity whose rules were not
researched (the Faroes and Greenland are not Denmark's for this purpose).

## 4. Band plan and repeater pairs (optional)

A country with no national plan gets its region's IARU plan, which is a
sound default: the plan is a code of practice and the guard only warns
outside it, unless the operator chooses "enforce".

- **A national plan** is a module in `ohsradio/plans/` with the shape in
  `plans/base.py`, registered in `PLANS`, and named in the Country's
  `plan`. It is a complete table, not a patch on the IARU one.
- **Repeater pairs** without a whole plan go in `BY_COUNTRY` in
  `ohsradio/plans/repeaters.py`, cited to the national plan. The direction
  is national (DE 70 cm inputs below the outputs, IE above, FR/IT/NL/BE
  1.6 MHz up), so never derive it from an IARU channel name. Where the
  research gives no direction, add nothing: auto stays simplex.

## 5. Tests: `tests/test_licence_<iso>.py`

The file starts with `import scratch_home`. Tests execute behaviour; they
never read source text.

- `licences.validate(module) == []` (the shared test does this for every
  registered regime too).
- For each class, a few signals through `ohsradio.guard.licence_check(cls,
  lo, hi, pep, gain, lic=module, mode=..., region=..., today=...)`: inside
  a row at its limit passes; above it warns; outside it, or in a gap, is
  refused - each with a comment quoting the research file's row.
- Each unconfirmed, satellite-only, dated, permit and location row:
  refused (or limited) as the research says, and allowed once the
  condition is answered where it can be.
- NB: `licences.satellite_uplink(module, cls, 2400.050e6, 2400.300e6)` for
  every class, against the research's QO-100 table.
- `countries.station(<a callsign>)` lands in the country, and
  `countries.in_force(...)` gives the regime.

Run the files you changed (`python3 -m unittest test_licence_<iso>` with
`tests` on `PYTHONPATH`), not the whole suite.
