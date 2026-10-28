#!/usr/bin/env python3
"""Build the AIS map's bundled land: OpenStreetMap's land polygons for Great
Britain, Ireland and their islands, simplified and cut into cells, so the
map draws a real coastline with no network at all (ohsradio/mapdata.py,
`GET api/map/land`).

    <python with pyshp and shapely> tools/mapland-build.py --shp DIR/land_polygons [--date YYYY-MM-DD]

DIR is osmdata.openstreetmap.de's land-polygons-split-4326.zip, fetched
once by hand (https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip,
930 MB, the whole world) and unpacked. pyshp and shapely are needed only
here, never by Radio.

Writes ohsradio/data/mapland/land.json.gz and land.LICENCE.txt beside it.

**Why OSM's land polygons and not Natural Earth.** The map is for ships off
the coast near the station, viewed a few to a few tens of kilometres
across. Natural Earth's 1:10m land (public domain) is accurate to about a
kilometre: the Cumbraes are blobs, Ardrossan and Troon harbours are not
there, and a ship alongside a quay is drawn on land. OSM's land polygons
are the coastline as mapped, to metres; simplified to FINE_TOL they still
show every harbour wall a ship lies against. 0.0004 degree made 0.51 MB
and lost the narrower piers; 0.0002 is 0.77 MB gzipped (377,000 points)
for the fine level, and the coarse level adds 17,000. The cost is the licence: the
file is a derived database under the ODbL, so the map must say "(c)
OpenStreetMap contributors" whenever it is drawn, and the file is offered
under the ODbL (land.LICENCE.txt, and `attribution` in api/map/info).

**Two levels.** `fine`: FINE_TOL degrees (about 22 m north-south, 12 m
east-west at 56 N), in CELL-degree cells, for views up to a couple of
degrees across; `coarse`: COARSE_TOL (about 500 m) in COARSE_CELL cells, for the
whole of the islands at once. A cell holds the land polygons cut to it,
each a list of rings (the outline, then any holes), each ring a flat list
of integers of 1e-4 degree (about 11 m, finer than either tolerance): the
first point whole, the rest as differences from the point before (lon, lat
pairs). Cutting at build time means the server never does geometry: a
bounding box is answered with the cells it touches.

The cells are cut on straight lines, so neighbours meet exactly on their
shared edge and a filled map shows no seam; a client must not stroke the
polygons' outlines (the cut edges would show) - the land's edge against
the sea is the coastline.

Coverage (BOUNDS): 11 W to 2.5 E, 49 N to 61 N - Great Britain, Ireland,
the Isle of Man, the Channel Islands, the Scillies, Orkney and Shetland,
and the coasts of France and Belgium across the Channel.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ohsradio" / "data" / "mapland"
BOUNDS = (-11.0, 49.0, 2.5, 61.0)  # west, south, east, north
SCALE = 1e4
FINE_TOL, CELL = 0.0002, 0.5
COARSE_TOL, COARSE_CELL = 0.005, 2.0
SOURCE = "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"

LICENCE = """Contains information from OpenStreetMap, which is made available here under the
Open Database License (ODbL).

land.json.gz is a derived database of OpenStreetMap data (c) OpenStreetMap
contributors (https://www.openstreetmap.org/copyright), and is itself made
available under the Open Database License 1.0:
https://opendatacommons.org/licenses/odbl/1-0/

Made by tools/mapland-build.py from osmdata.openstreetmap.de's land polygons
(land-polygons-split-4326, data of {date}): cut to {bounds} (west, south,
east, north), simplified (Douglas-Peucker, topology kept) to {fine} degrees
for the fine level and {coarse} for the coarse, and cut into cells.
Any map showing it must credit "(c) OpenStreetMap contributors".
"""


def ring_ints(coords) -> list[int]:
    out, plon, plat = [], None, None
    for lon, lat in coords:
        x, y = round(lon * SCALE), round(lat * SCALE)
        if plon is None:
            out += [x, y]
        else:
            if x == plon and y == plat:
                continue
            out += [x - plon, y - plat]
        plon, plat = x, y
    return out


def build_level(pieces, cell: float, tol: float):
    from shapely.geometry import box
    from shapely.validation import make_valid

    w, s, e, n = BOUNDS
    cells: dict[str, list] = {}
    points = 0
    for i in range(math.ceil((e - w) / cell)):
        for j in range(math.ceil((n - s) / cell)):
            x0, y0 = w + i * cell, s + j * cell
            cbox = box(x0, y0, min(x0 + cell, e), min(y0 + cell, n))
            polys = []
            for p in pieces.query(cbox):
                g = pieces.geoms[p].intersection(cbox)
                if g.is_empty:
                    continue
                g = make_valid(g.simplify(tol, preserve_topology=True))
                for poly in getattr(g, "geoms", [g]):
                    if poly.geom_type != "Polygon" or poly.area < (tol * tol):
                        continue
                    rings = [ring_ints(poly.exterior.coords)] + [ring_ints(r.coords) for r in poly.interiors]
                    rings = [r for r in rings if len(r) >= 8]
                    if rings:
                        polys.append(rings)
                        points += sum(len(r) // 2 for r in rings)
            if polys:
                cells[f"{round(x0 * SCALE)},{round(y0 * SCALE)}"] = polys
    return cells, points


class Pieces:
    """The land pieces in BOUNDS with a spatial index."""

    def __init__(self, shp: str):
        import shapefile
        from shapely import STRtree
        from shapely.geometry import shape

        sf = shapefile.Reader(shp)
        self.geoms = [shape(s.__geo_interface__) for s in sf.iterShapes(bbox=list(BOUNDS))]
        self.tree = STRtree(self.geoms)

    def query(self, g):
        return self.tree.query(g)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shp", required=True, help="land_polygons (without .shp)")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="the data's date (its README says)")
    a = ap.parse_args()
    pieces = Pieces(a.shp)
    print(f"{len(pieces.geoms)} pieces in {BOUNDS}", file=sys.stderr)
    fine, nf = build_level(pieces, CELL, FINE_TOL)
    coarse, nc = build_level(pieces, COARSE_CELL, COARSE_TOL)
    doc = {
        "schema": 1,
        "source": "osm-land-polygons",
        "from": SOURCE,
        "date": a.date,
        "licence": "ODbL-1.0",
        "attribution": {"text": "(c) OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright"},
        "bounds": list(BOUNDS),
        "scale": 1 / SCALE,
        "levels": {
            "fine": {"cell": CELL, "toleranceDeg": FINE_TOL, "points": nf, "cells": fine},
            "coarse": {"cell": COARSE_CELL, "toleranceDeg": COARSE_TOL, "points": nc, "cells": coarse},
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(doc, separators=(",", ":")).encode()
    # mtime 0: the same data makes the same file.
    (OUT / "land.json.gz").write_bytes(gzip.compress(raw, 9, mtime=0))
    (OUT / "land.LICENCE.txt").write_text(LICENCE.format(date=a.date, bounds=BOUNDS, fine=FINE_TOL,
                                                         coarse=COARSE_TOL))
    size = (OUT / "land.json.gz").stat().st_size
    print(f"fine {len(fine)} cells {nf} points; coarse {len(coarse)} cells {nc} points; "
          f"{len(raw) / 1e6:.1f} MB raw, {size / 1e6:.2f} MB gzipped", file=sys.stderr)


if __name__ == "__main__":
    main()
