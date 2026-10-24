"""DAB transmitters: which site a DAB signal comes from (23/10/2026;
docs/SERVER-API.md "DAB (Radio)", "Transmitters heard").

shack_sdr's DAB decoder reads each transmitter's TII code from the null
symbols (its feed's `tii`: main and sub identifier, its share of the
received power, a confidence). A code means nothing on its own: this
module looks it up in the regulator's list of transmitters, with the
ensemble's identifier (EId), and from the station's locator says where
the site is, how far and in which direction.

Where the data comes from, and why it is kept the way it is:

- **The UK list is Ofcom's** "Technical parameters for broadcast radio
  transmitters", DAB file (TxParamsDAB.csv): every BBC, national
  commercial, local and small-scale DAB transmitter with its ensemble,
  EId, block, TII, position and ERP. Published under the Open Government
  Licence v3.0 (the dataset's record on data.gov.uk says so), which allows
  bundling with attribution: the file carries it, and its notice sits
  beside it (`<file>.LICENCE.txt`), as local frequencies do.
- Ofcom writes TII main and sub in hex ("3E", "07" is 62/7, what the
  decoder reports); its ERP column as kW with a thousands comma in the
  decimals ("8.510,009" is 8.51 kW). Both are converted once, by the
  builder, so the app reads plain numbers.
- **Ireland has no open list** (RTÉ's DAB closed in 2021; ComReg publishes
  analogue only; the trial multiplex publishes no data), so an Irish
  station's codes show without a site.
- The bundled file is a snapshot made by tools/dabtx-build.py with the
  same builder as Refresh; it records its date and URL. Refresh (Radio's
  local-frequencies refresh, an administrator's action, never at start-up)
  downloads a newer copy into the data folder, which then wins.

**Matching.** The EId and the code name one transmitter - when Ofcom's
sheet is right, and on the air it is not always: on ohs-box's Ayr
recordings (23/10/2026) Darvel sends Central Scotland's 63/5 on every
multiplex it carries and West Kilbride 63/7, where the sheet gives Ayr
64/10 and 64/7. So a code is also matched by the site (another ensemble's
code at a site that carries this one) and by the sub identifier (this
ensemble's only transmitter with it), and for an ensemble the sheet lacks
by the code on the session's block; `match` says which (Transmitters.find).
What is shown is filtered by confidence and distance (describe).

Nothing here transmits or touches a radio.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from pathlib import Path

from ohscore.countries import distance_bearing, locator_position

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.dabtx")

BUNDLED = Path(__file__).resolve().parent / "data" / "dabtx"
REFRESHED = "dabtx"                     # the folder in the data folder Refresh writes to
FILE = "ofcom-dab.json"
SCHEMA = 1

OFCOM_URL = ("https://www.ofcom.org.uk/siteassets/resources/documents/spectrum/tv-transmitter-guidance/"
             "tech-parameters/txparamsdab.csv")
OFCOM_PAGE = "https://www.ofcom.org.uk/tv-radio-and-on-demand/coverage-and-transmitters/radio-tech-parameters"
ATTRIBUTION = {"source": "Ofcom", "licence": "Open Government Licence v3.0",
               "text": "Contains public sector information licensed under the Open Government Licence v3.0 "
                       "(Ofcom, Technical parameters for broadcast radio transmitters)",
               "url": OFCOM_PAGE}
# Each row of the file, in this order (columns keep 1,400 transmitters to
# about 130 kB).
# What a transmitters list shows (Transmitters.describe): a known code at
# this confidence or more, or nearer than this; an unknown one only at this.
KNOWN_CONFIDENCE = 0.5
NEAR_KM = 150.0
UNKNOWN_CONFIDENCE = 0.8
FIELDS = ("eid", "ensemble", "block", "main", "sub", "site", "area", "lat", "lon", "erpKw", "heightM")


# ---------------------------------------------------------------- building (Refresh and tools/)
def _hex(s: str, most: int) -> int | None:
    try:
        v = int(s.strip(), 16)
    except ValueError:
        return None
    return v if 0 <= v <= most else None


def _erp_kw(s: str) -> float | None:
    """Ofcom's "8.510,009" (kW, a thousands comma among the decimals)."""
    t = s.strip().replace(",", "")
    try:
        return round(float(t), 3) if t else None
    except ValueError:
        return None


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def build_ofcom(raw: bytes, fetched: str) -> dict:
    """The bundled file from Ofcom's TxParamsDAB.csv (Latin-1: a few labels
    carry accented letters). A row with no TII or no position is left out
    (it can never be matched or placed), and counted."""
    rows, skipped = [], 0
    for r in csv.DictReader(io.StringIO(raw.decode("latin-1"))):
        main = _hex(r.get("TII Main Id (Hex)") or "", 69)
        sub = _hex(r.get("TII Sub Id (Hex)") or "", 23)
        lat, lon = _num(r.get("Lat") or ""), _num(r.get("Long") or "")
        if main is None or sub is None or lat is None or lon is None:
            skipped += 1
            continue
        eid = (r.get("EID") or "").strip().upper()
        height = _num(r.get("In-Use Ae Ht") or "")
        rows.append([eid or None, (r.get("Ensemble") or "").strip() or None, (r.get("Block") or "").strip().upper(),
                     main, sub, (r.get("Site") or "").strip(), (r.get("Transmitter Area") or "").strip() or None,
                     round(lat, 5), round(lon, 5), _erp_kw(r.get("In-Use ERP Total") or ""),
                     height])
    if not rows:
        raise ValueError(_("There are no transmitters in the Ofcom file"))
    rows.sort(key=lambda x: (x[0] or "", x[3], x[4], x[5]))
    return {"schema": SCHEMA, "source": "ofcom", "fetched": fetched, "url": OFCOM_URL, "coverage": "United Kingdom",
            "attribution": ATTRIBUTION, "skipped": skipped, "fields": list(FIELDS), "rows": rows}


def write_file(path: Path, data: dict) -> None:
    """One transmitter a line, so a refreshed list diffs row by row."""
    head = json.dumps({k: v for k, v in data.items() if k != "rows"}, separators=(",", ":"), ensure_ascii=False)
    rows = ",\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in data["rows"])
    raw = (head[:-1] + ',"rows":[\n' + rows + "\n]}\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)


def read_file(path: Path) -> dict:
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("rows"), list) \
            or data.get("fields") != list(FIELDS):
        raise ValueError(_("{name}: not a DAB transmitters file").format(name=path.name))
    return data


# ---------------------------------------------------------------- the list
class Transmitters:
    """The transmitter list, read on first use (a station that never plays
    DAB never reads it), the refreshed copy in preference to the bundled."""

    def __init__(self, data_dir: Path | None, bundled: Path = BUNDLED):
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.bundled = Path(bundled)
        self._lock = threading.Lock()
        self._cache: tuple | None = None        # (stamp, by_eid, by_block, by_code, by_ens, data)

    def _path(self) -> Path | None:
        if self.data_dir is not None:
            fresh = self.data_dir / REFRESHED / FILE
            if fresh.exists():
                try:
                    read_file(fresh)
                    return fresh
                except (OSError, ValueError) as e:
                    log.warning("refreshed DAB transmitters unreadable, using the bundled copy: %s", e)
        p = self.bundled / FILE
        return p if p.exists() else None

    def _index(self):
        path = self._path()
        stamp = (str(path), path.stat().st_mtime_ns) if path else None
        with self._lock:
            if self._cache is not None and self._cache[0] == stamp:
                return self._cache[1:]
        by_eid: dict = {}
        by_block: dict = {}
        by_code: dict = {}
        by_ens: dict = {}
        data: dict = {}
        if path is not None:
            try:
                data = read_file(path)
            except (OSError, ValueError) as e:
                log.warning("%s: %s", path, e)
            for row in data.get("rows", []):
                try:
                    t = dict(zip(FIELDS, row))
                    key = (int(t["main"]), int(t["sub"]))
                except (TypeError, ValueError, KeyError):
                    continue
                if t["eid"]:
                    by_eid.setdefault((t["eid"], *key), []).append(t)
                    by_ens.setdefault(t["eid"], []).append(t)
                by_block.setdefault((t["block"], *key), []).append(t)
                by_code.setdefault(key, []).append(t)
        with self._lock:
            self._cache = (stamp, by_eid, by_block, by_code, by_ens, data)
        return by_eid, by_block, by_code, by_ens, data

    def about(self) -> dict:
        """What the list is: source, date, licence, how many."""
        data = self._index()[-1]
        return {"source": data.get("source", ""), "fetched": data.get("fetched", ""),
                "transmitters": len(data.get("rows", [])), "attribution": data.get("attribution") or {}}

    def find(self, eid: str, block: str, main: int, sub: int, here) -> tuple[dict | None, str | None]:
        """The list's transmitter for a code heard in ensemble `eid` on
        `block`, and how it was found (module docstring, "Matching"):

        - `eid`: the list has this code for this ensemble.
        - `site`: the list has this code for another ensemble at a site that
          also carries this one. Real sites send one code on every
          multiplex they carry while Ofcom's sheet gives each its own:
          Darvel sends Central Scotland's 63/5 on Ayr's 11B and Glasgow's
          11C too, where the sheet says 64/10 and 57/6 (ohs-box,
          23/10/2026).
        - `sub`: this ensemble has exactly one transmitter with this sub
          identifier, under another main one: West Kilbride, the sheet's
          64/7 for Ayr, is heard as 63/7.
        - `block`: this ensemble is not in the list at all (a new or
          small-scale one) and the code is on this block, nearest first.
        """
        by_eid, by_block, by_code, by_ens, _ = self._index()

        def nearest(rows):
            if not rows:
                return None
            return min(rows, key=lambda r: distance_bearing(here[0], here[1], r["lat"], r["lon"])[0] if here else 0.0)

        mine = by_ens.get(eid, []) if eid else []
        hit = nearest(by_eid.get((eid, main, sub), [])) if eid else None
        if hit:
            return hit, "eid"
        if mine:
            # A site carrying this ensemble whose other row has this code.
            for other in by_code.get((main, sub), []):
                same = [r for r in mine if abs(r["lat"] - other["lat"]) < 0.005 and abs(r["lon"] - other["lon"]) < 0.008]
                if same:
                    return same[0], "site"
            subs = [r for r in mine if int(r["sub"]) == sub]
            if len(subs) == 1:
                return subs[0], "sub"
            return None, None
        hit = nearest(by_block.get((block, main, sub), [])) if block else None
        return (hit, "block") if hit else (None, None)

    def describe(self, meta: dict, locator: str) -> list[dict]:
        """The feed's `tii` list as transmitters: each code with its site,
        distance and bearing from the station (None without a locator), and
        ERP, strongest first as the decoder put them - but only those worth
        showing (`shown`), since the decoder lists what it cannot rule out
        at low confidence, and a list someone reads should not name a
        transmitter that is not there:

        - a code the list knows for this ensemble (`eid`, `site`, `sub`, or
          `block` for an ensemble the list lacks) at confidence 0.5 or
          more, or at any confidence within NEAR_KM of the station - a weak
          neighbour of a loud transmitter is listed at 0.3 by the decoder,
          and a real one nearby (Rothesay on 12B) is worth showing, a
          code from the far end of the country (Bow Brickhill's 22/9 heard
          "on" 12B in Ayrshire) is not;
        - a code it does not know only at UNKNOWN_CONFIDENCE or more.

        Measured on nine real blocks (ohs-libs rust/shack_sdr
        tests/dab_tii_real.rs): this shows every transmitter that is there
        and nothing else."""
        tii = meta.get("tii")
        if not isinstance(tii, list) or not tii:
            return []
        ens = meta.get("ensemble") if isinstance(meta.get("ensemble"), dict) else {}
        eid = str(ens.get("id") or "").upper()
        block = str(meta.get("block") or "").upper()
        here = locator_position(locator or "")
        out = []
        for t in tii:
            try:
                main, sub = int(t["main"]), int(t["sub"])
                conf = float(t.get("confidence") or 0.0)
            except (TypeError, ValueError, KeyError):
                continue
            item = {"main": main, "sub": sub, "levelDb": t.get("levelDb"), "confidence": t.get("confidence"),
                    "site": None, "area": None, "ensemble": None, "erpKw": None, "lat": None, "lon": None,
                    "distanceKm": None, "bearingDeg": None, "match": None, "listedAs": None}
            row, match = self.find(eid, block, main, sub, here)
            if row is not None:
                item.update(site=row["site"], area=row["area"], ensemble=row["ensemble"], erpKw=row["erpKw"],
                            lat=row["lat"], lon=row["lon"], match=match)
                if (int(row["main"]), int(row["sub"])) != (main, sub):
                    item["listedAs"] = {"main": int(row["main"]), "sub": int(row["sub"])}
                if here:
                    km, deg = distance_bearing(here[0], here[1], row["lat"], row["lon"])
                    item.update(distanceKm=round(km, 1), bearingDeg=round(deg))
                shown = conf >= KNOWN_CONFIDENCE or (item["distanceKm"] is not None and item["distanceKm"] <= NEAR_KM)
            else:
                shown = conf >= UNKNOWN_CONFIDENCE
            if shown:
                out.append(item)
        return out

    # ------------------------------------------------------------ refresh
    def refresh(self, fetch, clock=time.time) -> dict:
        """Download Ofcom's current list into the data folder (part of the
        local-frequencies refresh). The bundled copy stays in use if it
        fails."""
        res = {"source": "ofcom-dab", "ok": False, "entries": 0, "why": ""}
        if self.data_dir is None:
            res["why"] = _("There is no data folder to keep a copy in")
            return res
        try:
            fetched = time.strftime("%Y-%m-%d", time.gmtime(clock()))
            data = build_ofcom(fetch(OFCOM_URL), fetched)
            write_file(self.data_dir / REFRESHED / FILE, data)
            res.update(ok=True, entries=len(data["rows"]), fetched=fetched)
        except Exception as e:  # noqa: BLE001  the bundled copy carries on
            log.warning("refresh ofcom-dab: %s", e)
            res["why"] = str(e) or e.__class__.__name__
        return res
