"""The QSO log: the station's shared logbook (ohs-libs shack_client, see
ohscore/station.py), shown and edited the way both apps always have, and
ADIF export.

Up to M3 each app kept its own JSON-lines file (<data>/log.jsonl). The
platform rule is one logbook per station (SERVICES.md section 3: "an app
never keeps its own logbook"): every contact now lives in the shared
store with a UUID, so QO-100 NB and Radio on one computer keep one log,
and a paired controller merges it with every other app's. The first time
an engine opens the store, its old file is moved in (migrate()), each
record with a UUID derived from its own content, so a migration that is
interrupted and run again adds nothing twice; the file is then renamed
log.jsonl.migrated and kept.

The windows still see records in the shape they were built for - `call`,
`t` (UTC seconds), the app's frequency key (NB's "dl", Radio's "rf"),
`mode` (the engine's mode name) and the optional fields - plus `uuid`.
The stored contact is ADIF (lower-case ADIF names, SERVICES.md 3.1): the
app supplies its ADIF fields through `adif_fields` exactly as it did for
export (a QO-100 contact is 13 cm up and 3 cm down via QO-100), and the
engine's mode name rides along as app_shack_mode so a contact reads back
as the mode it was logged in.

Rows are addressed by their position in entries(), oldest first, as the
logbook view always has; a contact another app logged appears in both.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .i18n.text import _

# ADIF 3.1.4 MODE / SUBMODE for each engine mode name. FT4, JS8 and Q65 are
# MFSK submodes in 3.1.4 (SERVICES.md 3.1 settles on its enumeration; NB's
# own map used to say JS8 and Q65 as modes).
ADIF_MODE = {"usb": ("SSB", "USB"), "lsb": ("SSB", "LSB"), "cw": ("CW", ""), "am": ("AM", ""),
             "ft8": ("FT8", ""), "ft4": ("MFSK", "FT4"), "q65": ("MFSK", "Q65"), "js8": ("MFSK", "JS8"),
             "psk31": ("PSK", "PSK31"), "psk63": ("PSK", "PSK63"), "psk125": ("PSK", "PSK125"),
             "rtty": ("RTTY", ""), "freedv": ("DIGITALVOICE", "FREEDV"), "sstv": ("SSTV", ""), "fm": ("FM", ""),
             "wspr": ("WSPR", ""), "hsmodem": ("DYNAMIC", "HSMODEM")}
_FROM_ADIF = {v: k for k, v in ADIF_MODE.items()}

OPTIONAL = ("rstSent", "rstRcvd", "name", "grid", "comment")
# Legacy record key -> stored ADIF field.
_OPT_FIELD = {"rstSent": "rst_sent", "rstRcvd": "rst_rcvd", "name": "name", "grid": "gridsquare",
              "comment": "comment"}
# Export order: what goes between TIME_ON and MODE, and after it.
_BEFORE = ("band", "band_rx", "freq_hz", "freq_rx_hz")
_AFTER = ("prop_mode", "sat_name")
_ADIF_TAG = {"freq_hz": "FREQ", "freq_rx_hz": "FREQ_RX"}
_SKIP = {"call", "start", "end", "mode", "submode", "station_callsign", "my_gridsquare"}

# (fields before MODE, fields after MODE) for one record, as (tag, value)
# pairs; see Logbook.
AdifFields = Callable[[dict], "tuple[list[tuple[str, str]], list[tuple[str, str]]]"]


def _clean_call(call) -> str:
    return "".join(c for c in str(call).upper() if c.isalnum() or c == "/")


def _iso(t: float) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int(round((float(t) % 1) * 1000)) % 1000:03d}Z"


def _secs(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0


class Logbook:
    """`adif_fields(record)` returns the app's ADIF fields for a record:
    those that go between TIME_ON and MODE (band, frequencies), then those
    after MODE (propagation, satellite). `title` heads the export and
    `program_id` is its PROGRAMID. `freq_field` is the stored frequency the
    app's `freq_key` shows (NB: the downlink, freq_rx_hz).

    `station` is a shack_client Station; without one the log keeps a store
    of its own in `data_dir` (a tool, a test)."""

    def __init__(self, data_dir: Path, *, freq_key: str, adif_fields: AdifFields, title: str, program_id: str,
                 station=None, freq_field: str = "freq_hz", app: str = "", app_version: str = "",
                 identity: Callable[[], tuple[str, str]] | None = None):
        self.data_dir = Path(data_dir)
        self.freq_key = freq_key
        self.adif_fields = adif_fields
        self.title = title
        self.program_id = program_id
        self.freq_field = freq_field
        self.identity = identity or (lambda: ("", ""))
        self._own = station is None
        if station is None:
            def station():
                from .station import open_station
                return open_station(app or "shack-desktop", app_version, self.data_dir, background=False)
        # Opened on first use, not here: an engine is built many times over
        # in the test suite and in --analyse runs that never touch the log,
        # and each open is a SQLite file and connections.
        self._station = station if not callable(station) else None
        self._open = station if callable(station) else None
        self._migrated = False

    @property
    def station(self):
        if self._station is None:
            self._station = self._open()
        if not self._migrated:
            self._migrated = True
            self.migrate()
        return self._station

    # ---------------------------------------------------------- the old file
    @property
    def legacy_path(self) -> Path:
        return self.data_dir / "log.jsonl"

    def migrate(self) -> int:
        """Move <data>/log.jsonl into the store once (SERVICES.md 3.3: each
        app's first run converts its old log, keeping the old file).
        Returns how many contacts were added."""
        p = self.legacy_path
        if not p.is_file():
            return 0
        items = []
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or not _clean_call(rec.get("call", "")) or "t" not in rec:
                continue
            digest = hashlib.sha256(f"{self.station.app}\n{n}\n{line}".encode()).digest()
            fields = self._fields(rec)
            fields["uuid"] = str(_uuid.UUID(bytes=digest[:16], version=4))
            items.append(fields)
        added = self.station.logbook.add_many(items) if items else []
        p.replace(p.with_name(p.name + ".migrated"))
        return len(added)

    # ---------------------------------------------------------- shapes
    def _fields(self, rec: dict) -> dict:
        """A record in the windows' shape -> stored ADIF fields."""
        mode = str(rec.get("mode", "usb"))
        m, sub = ADIF_MODE.get(mode, (mode.upper(), ""))
        f = {"call": _clean_call(rec["call"]), "start": _iso(rec["t"]), "mode": m, "app_shack_mode": mode}
        if sub:
            f["submode"] = sub
        for k, fld in _OPT_FIELD.items():
            if rec.get(k) not in (None, ""):
                f[fld] = str(rec[k])
        before, after = self.adif_fields(rec)
        for tag, val in list(before) + list(after):
            name = {"FREQ": "freq_hz", "FREQ_RX": "freq_rx_hz"}.get(tag, tag.lower())
            f[name] = int(round(float(val) * 1_000_000)) if name.endswith("_hz") else str(val)
        call, grid = self.identity()
        if call:
            f["station_callsign"] = call
        if grid:
            f["my_gridsquare"] = grid
        return f

    def _record(self, q) -> dict:
        """A stored contact -> the windows' shape."""
        f = q.fields
        mode = f.get("app_shack_mode") or _FROM_ADIF.get((str(f.get("mode", "")).upper(),
                                                          str(f.get("submode", "")).upper()),
                                                         str(f.get("mode", "")).lower())
        freq = f.get(self.freq_field, f.get("freq_hz", 0))
        rec = {"call": f.get("call", ""), "t": _secs(f.get("start", "")), self.freq_key: float(freq or 0.0),
               "mode": mode}
        for k, fld in _OPT_FIELD.items():
            if f.get(fld) not in (None, ""):
                rec[k] = str(f[fld])
        rec["uuid"] = q.uuid
        return rec

    def _live(self) -> list:
        """Every live contact, oldest first (the order rows are addressed by)."""
        rows = self.station.logbook.query(limit=1_000_000)
        rows.reverse()
        return rows

    # ---------------------------------------------------------- the API the engines use
    def add(self, call: str, default_freq: float, default_mode: str, /, **fields) -> dict:
        """Log a QSO. `fields` may give the time `t` (default now, UTC),
        the frequency (default `default_freq`), the mode (default
        `default_mode`) and the optional fields."""
        call = _clean_call(call)
        if not call:
            raise ValueError(_("A QSO needs the other station's callsign"))
        rec = {"call": call, "t": float(fields.pop("t", time.time())),
               self.freq_key: float(fields.pop(self.freq_key, default_freq)),
               "mode": str(fields.pop("mode", default_mode))}
        for k in OPTIONAL:
            if k in fields and fields[k] not in (None, ""):
                rec[k] = str(fields[k])[:200].replace("\n", " ")
        q = self.station.logbook.add(self._fields(rec))
        rec["uuid"] = q.uuid
        return rec

    def entries(self) -> list[dict]:
        return [self._record(q) for q in self._live()]

    def _at(self, index: int):
        rows = self._live()
        if not 0 <= index < len(rows):
            raise ValueError(_("There is no such QSO in the log"))
        return rows[index]

    def edit(self, index: int, **fields) -> dict:
        """Change fields of the QSO at `index` in entries() order (the
        logbook view's row). Same fields and cleaning as add; an empty
        value removes an optional field.

        Only the stored fields the edit is about are written: the log is
        shared, so NB correcting a report on a contact Radio logged must
        not rewrite it as a QO-100 contact through NB's own ADIF fields,
        and each written field is its own last-edit-wins edit when synced
        (SYNC.md section 4)."""
        q = self._at(index)
        rec = self._record(q)
        rec.pop("uuid")
        touched: set = set()
        if "call" in fields:
            call = _clean_call(fields.pop("call"))
            if not call:
                raise ValueError(_("A QSO needs the other station's callsign"))
            rec["call"] = call
            touched.add("call")
        if "t" in fields:
            rec["t"] = float(fields.pop("t"))
            touched.add("start")
        if self.freq_key in fields:
            rec[self.freq_key] = float(fields.pop(self.freq_key))
            before, after = self.adif_fields(rec)
            touched |= {{"FREQ": "freq_hz", "FREQ_RX": "freq_rx_hz"}.get(t, t.lower()) for t, _v in before + after}
        if "mode" in fields:
            rec["mode"] = str(fields.pop("mode"))
            touched |= {"mode", "submode", "app_shack_mode"}
        for k in OPTIONAL:
            if k in fields:
                v = fields.pop(k)
                if v in (None, ""):
                    rec.pop(k, None)
                else:
                    rec[k] = str(v)[:200].replace("\n", " ")
                touched.add(_OPT_FIELD[k])
        want = self._fields(rec)
        diff = {k: want.get(k) for k in touched if q.fields.get(k) != want.get(k)}
        if diff:
            # A None clears the field: an edit with its own clock (SERVICES.md 3.2).
            q = self.station.logbook.update(q.uuid, diff)
        return self._record(q)

    def delete(self, index: int) -> None:
        self.station.logbook.delete(self._at(index).uuid)

    def export_adif(self, path: Path | None = None, *, callsign: str = "", locator: str = "") -> Path:
        """Write the whole log as ADIF 3.1.4 and return its path. Every
        record carries APP_SHACK_UUID (SERVICES.md 3.2), so a file exported
        here and imported by a controller or another app is the same
        contacts, not copies."""
        path = Path(path) if path else self.data_dir / "log.adi"
        path.parent.mkdir(parents=True, exist_ok=True)

        def fld(k, v):
            v = str(v)
            return f"<{k}:{len(v.encode('utf-8'))}>{v} "

        def val(k, v):
            return f"{int(v) / 1e6:.6f}" if k.endswith("_hz") else v

        lines = [f"{self.title}\n", fld("ADIF_VER", "3.1.4"), fld("PROGRAMID", self.program_id), "<EOH>\n"]
        for q in self._live():
            f = {k: v for k, v in q.fields.items() if v not in (None, "")}
            tm = time.gmtime(_secs(f.get("start", "")))
            rec = [fld("CALL", f["call"]), fld("QSO_DATE", time.strftime("%Y%m%d", tm)),
                   fld("TIME_ON", time.strftime("%H%M%S", tm))]
            rec += [fld(_ADIF_TAG.get(k, k.upper()), val(k, f[k])) for k in _BEFORE if k in f]
            rec.append(fld("MODE", f.get("mode", "")))
            rec += [fld(k.upper(), f[k]) for k in _AFTER if k in f]
            if f.get("submode"):
                rec.append(fld("SUBMODE", f["submode"]))
            for k in ("rst_sent", "rst_rcvd", "name", "gridsquare", "comment"):
                if k in f:
                    rec.append(fld(k.upper(), f[k]))
            done = set(_BEFORE) | set(_AFTER) | _SKIP | set(_OPT_FIELD.values())
            rec += [fld(k.upper(), val(k, v)) for k, v in sorted(f.items()) if k not in done]
            own_call = f.get("station_callsign") or callsign
            own_grid = f.get("my_gridsquare") or locator
            if own_call:
                rec.append(fld("STATION_CALLSIGN", own_call))
            if own_grid:
                rec.append(fld("MY_GRIDSQUARE", own_grid))
            rec.append(fld("APP_SHACK_UUID", q.uuid))
            if q.origin.get("app"):
                rec.append(fld("APP_SHACK_ORIGIN", q.origin["app"]))
            lines.append("".join(rec) + "<EOR>\n")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        tmp.replace(path)
        return path

    def import_adif(self, text: str) -> dict:
        """SERVICES.md 3.2 import: shack_client's, which keeps APP_SHACK_UUID
        and reports duplicates rather than skipping them silently."""
        return self.station.logbook.import_adif(text)

    def close(self) -> None:
        if self._own and self._station is not None:
            self._station.close()
