"""Where the station is, and what follows from it: the IARU region, the
licence regime and the default band plan.

Until 08/10/2026 both apps assumed the United Kingdom: Ofcom's licence
classes, the RSGB band plan. Brian asked for both to work abroad, so the
station's country is now a setting, derived by default from the callsign
through cty.dat (ohscore/dxcc.py): GM4BRI is in Scotland, so the UK, so
Ofcom's licence, the RSGB plan and IARU Region 1. EA8/GM4BRI is in the
Canary Islands, so Spain's rules - the country of *operation* is the
prefix's, as a reciprocal or CEPT licence says it is.

The unit here is the DXCC entity, because that is what a callsign tells
us and what an operator knows a station by (Scotland, Canary Islands,
Hawaii). A regulator's rules usually cover several entities - Ofcom's the
four home nations, the Isle of Man and the Channel Islands - so a written
country lists the entities it governs (`Country.entities`, primary
prefixes as cty.dat gives them). An entity no written country lists has a
region and nothing else: no regime, and the IARU plan of its region.

Never a guess about a country's rules. A country appears in WRITTEN only
when its licence regime is written (ohscore/licences/) from a cited source;
everywhere else transmit stays locked until the operator chooses a regime
or enters their own licence (docs/ham/adding-a-country.md).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import callsign, dxcc


@dataclass(frozen=True)
class Country:
    iso: str                  # ISO 3166-1 alpha-2
    name: str
    regulator: str
    entities: tuple           # DXCC primary prefixes (cty.dat) its rules cover
    regimes: tuple            # licence regime ids (ohscore/licences), the first the default
    plan: str = ""            # band plan id (OpenHamShack Radio's ohsradio/plans); "" = the region's IARU plan
    region: int = 1
    note: str = ""            # what an operator should know about how far the mapping is sure


# The countries whose licence regime is written. The UK's: "The licence
# authorises use of the designated spectrum across and over the UK and the
# Crown Dependencies of Jersey, Guernsey and the Isle of Man, including
# their territorial seas" (Ofcom, Amateur Radio Guidance, updated 14 Oct
# 2025, section 3.4 p.25; fetched 08/10/2026, sha256 89fe14a5...dcd76).
# Shetland is a WAE entity of Scotland's.
WRITTEN: tuple[Country, ...] = (
    Country("GB", "United Kingdom", "Ofcom", ("G", "GM", "GM/s", "GW", "GI", "GD", "GJ", "GU"),
            ("ofcom-2024",), "rsgb-2026", 1),
    # The fifteen researched on 08/10/2026 (docs/ham/countries/<iso>.md;
    # territorial extent from each file's section 1 or 6). An entity is
    # listed only where the research says the licence covers it; the rest
    # (the Faroes, Greenland, Svalbard, the Dutch Caribbean, Australia's
    # external territories, ZL5, Lampedusa's IG9) stay unwritten, so a
    # station there is told no licence is written rather than given one
    # that may not apply. France's Region 2 departments and the US Region 3
    # territories are left out for another reason: region_of() gives every
    # entity of a written country that country's region, which would put
    # Guadeloupe in Region 1 and Guam in Region 2 (the regimes already carry
    # their region-specific rows, ready for when entities get a region each).
    Country("IE", "Ireland", "ComReg", ("EI",), ("comreg-2023",), "", 1),        # ComReg 09/45R6 s.4.2
    Country("DE", "Germany", "BNetzA", ("DL",), ("bnetza-2024",), "", 1),         # AfuV Anlage 1
    Country("NL", "Netherlands", "RDI", ("PA",), ("rdi-2024",), "", 1),
    Country("BE", "Belgium", "BIPT", ("ON",), ("bipt-2019",), "", 1),
    Country("FR", "France", "ARCEP", ("F", "TK", "FR", "FH"), ("arcep-2019",), "", 1),   # ARCEP 2012-1241
    Country("ES", "Spain", "SETID", ("EA", "EA6", "EA8", "EA9"), ("setid-2026",), "", 1),  # Orden IET/1311/2013 art.14
    Country("IT", "Italy", "MIMIT", ("I", "IS", "IT9"), ("mimit-2022",), "", 1),           # CCE art.140
    Country("NO", "Norway", "Nkom", ("LA",), ("nkom-2026",), "", 1),              # FOR-2026-03-23-465, mainland
    Country("SE", "Sweden", "PTS", ("SM",), ("pts-2025",), "", 1),                # PTSFS 2025:1
    Country("DK", "Denmark", "Digitaliseringsstyrelsen", ("OZ",), ("digst-2026",), "", 1),  # BEK 499/2026
    Country("FI", "Finland", "Traficom", ("OH", "OH0", "OJ0"), ("traficom-2026",), "", 1),  # 6 K/2019M; F2 s.6 Aland
    Country("US", "United States", "FCC", ("K", "KL", "KH6", "KP4", "KP2", "KP1", "KH3", "KH4"),
            ("fcc-2026",), "", 2),                                                 # 47 CFR 97, Appendix 1
    Country("CA", "Canada", "ISED", ("VE", "CY0", "CY9"), ("ised-2022",), "", 2),  # RBR-4 Schedule I
    Country("AU", "Australia", "ACMA", ("VK",), ("acma-2023",), "", 3),           # Class Licence 2023 s.10, s.17
    Country("NZ", "New Zealand", "RSM", ("ZL", "ZL7", "ZL8", "ZL9"), ("rsm-2025",), "", 3),  # GURL 2025 cl.4(1), 8(3)
)
BY_ENTITY = {e: c for c in WRITTEN for e in c.entities}
BY_ISO = {c.iso: c for c in WRITTEN}

# --- IARU region -------------------------------------------------------------
# The IARU's regions are the ITU's (Radio Regulations, Article 5, Nos.
# 5.2-5.9). cty.dat gives each entity a continent, which settles most:
# Europe and Africa are Region 1, the Americas Region 2, Asia and Oceania
# Region 3. What the continent gets wrong is listed by primary prefix:
#
# - Region 1 in Asia (RR 5.3 and line A): the former Soviet republics,
#   Mongolia, Turkey, and the Middle East west of line A, which runs from
#   40°N 40°E to the Tropic of Cancer at 60°E - the Arabian peninsula, the
#   Levant, Iraq and the Gulf states. Iran and Afghanistan are east of it
#   (and RR 5.8 puts the whole of Iran in Region 3).
# - Region 3 in Africa: islands east of 60°E (line A runs down 60°E):
#   Rodrigues, Chagos, Amsterdam & St Paul, Kerguelen, Heard.
# - Region 2 in Oceania: east of line C, which runs from 50°N 165°E to
#   10°N 170°W and then along 10°N to 120°W: Hawaii, Midway, Kure and
#   Johnston. (Line C is checked here against each entity's centre.)
#
# Antarctica (CE9 and others) spans all three and is left to its continent.
_REGION1_ASIA = frozenset({"4J", "4L", "4X", "5B", "7O", "9K", "A4", "A6", "A7", "A9", "E4", "EK", "EX", "EY",
                           "EZ", "HZ", "JT", "JY", "OD", "TA", "UA9", "UK", "UN", "YI", "YK", "ZC4"})
_REGION3_AFRICA = frozenset({"3B9", "VQ9", "FT/Z", "FT/X", "VK0H"})
_REGION2_OCEANIA = frozenset({"KH6", "KH7K", "KH4", "KH3"})
_BY_CONTINENT = {"EU": 1, "AF": 1, "NA": 2, "SA": 2, "AS": 3, "OC": 3}


def region_of(ent: dxcc.Entity | None) -> int | None:
    if ent is None:
        return None
    if ent.prefix in _REGION1_ASIA:
        return 1
    if ent.prefix in _REGION3_AFRICA:
        return 3
    if ent.prefix in _REGION2_OCEANIA:
        return 2
    if ent.prefix in BY_ENTITY:
        return BY_ENTITY[ent.prefix].region
    return _BY_CONTINENT.get(ent.continent)


# --- QO-100 -----------------------------------------------------------------
# Es'hail-2 is geostationary at 26°E (docs/qo100-research.md). Where it is
# below the horizon a station cannot reach it at all; under a few degrees
# it is behind most horizons. Neither is an error: the operator may be
# testing, receiving a recording, or about to travel.
QO100_LON = 26.0
_RE_KM, _GEO_KM = 6378.137, 42164.0


def geo_elevation(lat: float, lon: float, sat_lon: float = QO100_LON) -> float:
    """Elevation, degrees, of a geostationary satellite at `sat_lon` °E
    from `lat`, `lon` (°N, °E) on a spherical Earth: good to a fraction of
    a degree, which is all a footprint note needs."""
    phi, dl = math.radians(lat), math.radians(sat_lon - lon)
    cos_g = math.cos(phi) * math.cos(dl)
    sin_g = math.sqrt(max(0.0, 1 - cos_g * cos_g))
    if sin_g < 1e-9:
        return 90.0
    return math.degrees(math.atan2(cos_g - _RE_KM / _GEO_KM, sin_g))


def locator_position(loc: str) -> tuple[float, float] | None:
    """The centre of a Maidenhead square (4, 6 or 8 characters), (°N, °E).

    8 characters because the station profile allows them (SERVICES.md 2.1)
    and local frequencies measure from the station: an extended square is
    about 1 km across where a subsquare is 5 km by 9."""
    loc = (loc or "").strip()
    if len(loc) not in (4, 6, 8):
        return None
    try:
        a, b = loc[0].upper(), loc[1].upper()
        if not ("A" <= a <= "R" and "A" <= b <= "R" and loc[2:4].isdigit()):
            return None
        lon = (ord(a) - 65) * 20 - 180 + int(loc[2]) * 2
        lat = (ord(b) - 65) * 10 - 90 + int(loc[3])
        if len(loc) == 4:
            return lat + 0.5, lon + 1.0
        c, d = loc[4].lower(), loc[5].lower()
        if not ("a" <= c <= "x" and "a" <= d <= "x"):
            return None
        lat, lon = lat + (ord(d) - 97) / 24, lon + (ord(c) - 97) / 12
        if len(loc) == 6:
            return lat + 1 / 48, lon + 1 / 24
        if not loc[6:8].isdigit():
            return None
        return lat + int(loc[7]) / 240 + 1 / 480, lon + int(loc[6]) / 120 + 1 / 240
    except (IndexError, ValueError):
        return None


EARTH_KM = 6371.0088        # the IUGG mean radius: a sphere is good to 0.5 %, plenty for "how far"


def distance_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """Great-circle distance (km) and initial bearing (degrees from true
    north, 0-360) from the first point to the second, on a sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    km = 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return km, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


# --- the station -------------------------------------------------------------
@dataclass(frozen=True)
class Station:
    """What the callsign (or the operator's choice) says about where the
    station is. `source` is "callsign", "setting" or "" (nothing known)."""
    entity: str = ""            # "Scotland"
    prefix: str = ""            # "GM"
    region: int | None = None
    country: Country | None = None
    source: str = ""
    lat: float | None = None
    lon: float | None = None
    home_entity: str = ""       # where the operator's own call is from, when that is elsewhere (EA8/GM4BRI)
    home_country: Country | None = None
    at_sea: bool = False        # /MM or /AM: in no country
    notes: tuple = field(default_factory=tuple)

    @property
    def regime(self) -> str:
        return self.country.regimes[0] if self.country is not None and self.country.regimes else ""

    @property
    def visiting(self) -> bool:
        return bool(self.home_entity) and self.home_entity != self.entity


def _entity_by_prefix(cty: dxcc.Countries, prefix: str) -> dxcc.Entity | None:
    for ent in list(cty.prefixes.values()) + list(cty.exact.values()):
        if ent.prefix == prefix:
            return ent
    return None


def entities(data_dir: Path | None = None) -> list[tuple[str, str]]:
    """Every entity in cty.dat as (primary prefix, name), sorted by name:
    the choices for the station-country setting."""
    cty = dxcc.load(data_dir)
    seen = {}
    for ent in cty.prefixes.values():
        seen.setdefault(ent.prefix, ent.name)
    return sorted(seen.items(), key=lambda kv: kv[1].lower())


def station(call: str, override: str = "", data_dir: Path | None = None) -> Station:
    """Where the station is. `override` (a primary prefix from entities())
    wins; otherwise the callsign's location part (ohscore/dxcc.py) - the
    prefix of EA8/GM4BRI, the area of W1AW/4."""
    cty = dxcc.load(data_dir)
    call = callsign.normalise(call)
    home = cty.lookup(callsign.home(call)) if callsign.valid(call) else None
    if override:
        ent = _entity_by_prefix(cty, override)
        if ent is None:
            return Station(source="setting", prefix=override,
                           notes=(f"The chosen country ({override}) is not in this cty.dat.",))
        source = "setting"
    else:
        if not callsign.valid(call):
            return Station()
        if dxcc.location_part(call) is None:
            return Station(source="callsign", at_sea=True, home_entity=home.name if home else "",
                           home_country=BY_ENTITY.get(home.prefix) if home else None)
        ent = cty.lookup(call)
        if ent is None:
            return Station(source="callsign")
        source = "callsign"
    home_name = home.name if home is not None and home.prefix != ent.prefix else ""
    home_country = BY_ENTITY.get(home.prefix) if home is not None and home_name else None
    return Station(entity=ent.name, prefix=ent.prefix, region=region_of(ent), country=BY_ENTITY.get(ent.prefix),
                   source=source, lat=ent.lat, lon=ent.lon, home_entity=home_name, home_country=home_country)


# --- the licence in force -----------------------------------------------------
# Whole sentences, with the names put in by format(): never assembled from
# fragments, so a later translation can take each one whole.
NO_REGIME_IN = ("No licence for {country} is written into OpenHamShack yet: transmit stays locked until you enter your "
                "own licence's segments and power limits (Settings › Licence & plan › Your own licence)")
NO_COUNTRY = ("The station's country is not known: transmit stays locked until you set your callsign or choose "
              "the country (Settings › Station), or enter your own licence (Settings › Licence & plan)")
AT_SEA = ("Maritime or aeronautical mobile (/MM, /AM): no country's licence applies by itself. Transmit stays "
          "locked until you choose the licence you operate under (Settings › Licence & plan)")
NO_SEGMENTS = ("Your own licence has no segments yet: transmit stays locked until you enter them (Settings › "
               "Licence & plan › Your own licence)")
UNKNOWN_REGIME = "The licence {regime!r} is not one this version knows: choose yours again (Settings › Licence & plan)"
NOT_THIS_COUNTRY = ("The station is in {country}, but the licence chosen is {regime}: the guard applies {regime} "
                    "because you chose it")
ABROAD = ("Signing from {country} with a call from {home}: {country}'s rules apply there, not your home "
          "licence's")
QO100_BELOW = ("QO-100 is below the horizon from {country}: it can be seen from Europe, Africa, the Middle East, "
               "India and eastern Brazil")
QO100_LOW = "QO-100 is only {elevation:.0f}° above the horizon from {country}: a clear view to the south-east or west is needed"


@dataclass(frozen=True)
class InForce:
    """The licence the transmit guard applies, and why. `regime` is a
    ohscore/licences module, the operator's own (licences.custom), or None
    with `why_none` the sentence that refuses."""
    station: Station
    regime: object = None
    regime_id: str = ""
    cls: str = ""
    why_none: str = ""
    notes: tuple = ()

    def info(self) -> dict:
        """The engine's `station` status: what Settings and the transmit
        card show."""
        s, r = self.station, self.regime
        return {"entity": s.entity, "prefix": s.prefix, "region": s.region or 0, "source": s.source,
                "country": s.country.name if s.country else "", "iso": s.country.iso if s.country else "",
                "regulator": s.country.regulator if s.country else "",
                "regime": self.regime_id, "regimeTitle": getattr(r, "TITLE", ""), "regimeShort": getattr(r, "SHORT", ""),
                "classes": list(getattr(r, "CLASSES", ())),
                "classNames": dict(getattr(r, "CLASS_NAME", {})), "why": self.why_none, "notes": list(self.notes),
                "home": s.home_entity, "atSea": s.at_sea,
                "conditions": [{"key": c["key"], "label": c["label"], "default": bool(c.get("default", False))}
                               for c in getattr(r, "CONDITIONS", [])]}


def in_force(st: dict, data_dir: Path | None = None) -> InForce:
    """The licence in force for a state dict's callsign, stationCountry,
    licence ("auto", "custom" or a regime id), customLicence and
    licenceClass."""
    from . import licences
    s = station(st.get("callsign", ""), st.get("stationCountry", ""), data_dir)
    choice = st.get("licence") or licences.AUTO
    cls = st.get("licenceClass", "")
    notes = list(s.notes)
    abroad = s.visiting and s.home_country is not s.country
    if abroad:
        notes.append(ABROAD.format(country=s.entity, home=s.home_entity))
    if choice == licences.CUSTOM:
        segs = st.get("customLicence") or []
        if not segs:
            return InForce(s, None, licences.CUSTOM, licences.CUSTOM_CLASS, NO_SEGMENTS, tuple(notes))
        return InForce(s, licences.custom(segs, s.entity), licences.CUSTOM, licences.CUSTOM_CLASS, "", tuple(notes))
    if choice == licences.AUTO:
        rid = s.regime
        if not rid:
            why = (AT_SEA if s.at_sea else NO_REGIME_IN.format(country=s.entity) if s.entity else NO_COUNTRY)
            if abroad and s.home_country is not None:
                home = licences.get(s.home_country.regimes[0])
                hint = licences.cept_suggestion(home, cls, None) if home is not None and cls in home.CLASSES else ""
                if hint:
                    notes.append(hint)
            return InForce(s, None, "", cls, why, tuple(notes))
    else:
        rid = choice
    lic = licences.get(rid)
    if lic is None:
        return InForce(s, None, rid, cls, UNKNOWN_REGIME.format(regime=rid), tuple(notes))
    if choice != licences.AUTO and s.entity and (s.country is None or rid not in s.country.regimes):
        notes.append(NOT_THIS_COUNTRY.format(country=s.entity, regime=lic.SHORT))
    if abroad and s.home_country is not None:
        home = licences.get(s.home_country.regimes[0])
        hint = licences.cept_suggestion(home, "", lic) if home is not None else ""
        if hint:
            notes.append(hint)
    return InForce(s, lic, rid, cls, "", tuple(notes))


def qo100_note(st: dict, data_dir: Path | None = None) -> str:
    """A gentle sentence when QO-100 is low or out of sight from the
    station - from the locator when there is one (finer), else the
    country's centre; "" when it is in view or nothing is known."""
    s = station(st.get("callsign", ""), st.get("stationCountry", ""), data_dir)
    pos = locator_position(st.get("locator", ""))
    if pos is None and s.lat is not None and s.lon is not None:
        pos = (s.lat, s.lon)
    if pos is None:
        return ""
    el = geo_elevation(*pos)
    where = s.entity or "your locator"
    if el < 0:
        return QO100_BELOW.format(country=where)
    if el < 5:
        return QO100_LOW.format(elevation=el, country=where)
    return ""
