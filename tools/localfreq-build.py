#!/usr/bin/env python3
"""Build Radio's bundled local-frequencies data (ohsradio/data/localfreq/,
read by ohsradio/localfreq.py; docs/SERVER-API.md "Local frequencies").

    tools/localfreq-build.py [--src DIR] [--only NAME ...] [--offline]

Each source becomes a file of its own with its licence notice beside it,
because the licences differ (ohsradio/localfreq.py says why). What each
one is made from:

- ourairports.json.gz: OurAirports' airports.csv and
  airport-frequencies.csv (public domain), downloaded into --src (default
  ~/build/localfreq-src) unless already there, through the same builder
  Refresh uses.
- osm-marine.json: marinas, harbours, locks and coast radio with a VHF
  channel, from OpenStreetMap through Overpass, for Great Britain, Ireland,
  the Isle of Man and the Channel Islands. A derived database: the file is
  published under the ODbL 1.0.
- openaip.json: area and approach control from openAIP's API (CC BY-NC
  4.0). The API needs a key (x-openaip-api-key): give it in
  OPENAIP_API_KEY. Without one the file is written empty, saying so, and a
  station fills it with Refresh and its administrator's key.
- itu-marine.json, hmcg.json, channels.json, ncdxf.json: fixed tables,
  written from the literals below, which are their source of truth: the
  ITU RR Appendix 18 marine channels, HM Coastguard's MSI aerials and
  channels (MCA Advice Note 1033, OGL v3.0), PMR446, CB and LPD433, and the
  NCDXF/IARU beacons.

Run it with network access when a release wants fresher data; commit only
the files it writes, never the downloads in --src (12 MB of CSV).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ohsradio import localfreq as lf  # noqa: E402

OUT = ROOT / "ohsradio" / "data" / "localfreq"
BUNDLE_AREA = ("GB", "IE", "IM", "JE", "GG")

ITU_URL = "https://www.itu.int/pub/R-REG-RR"
HMCG_URL = ("https://www.gov.uk/government/publications/advice-note-1033-maritime-safety-information-msi-leaflet/"
            "advice-note-1033-maritime-safety-information-msi-leaflet")
NCDXF_URL = "https://www.ncdxf.org/beacon/"

# ---------------------------------------------------------------- ITU RR Appendix 18
# What each channel is for, as Appendix 18 and its notes allocate it (the
# uses a listener meets most; port operations and intership share many).
ITU_USES = {
    6: "intership; search and rescue with aircraft", 8: "intership", 9: "intership, port operations",
    10: "intership, port operations", 11: "port operations", 12: "port operations", 13: "navigation safety (bridge to bridge)",
    14: "port operations", 15: "on-board communications (low power)", 16: "distress, safety and calling",
    17: "on-board communications (low power)", 67: "intership, port operations", 68: "port operations",
    69: "intership, port operations", 70: "DSC distress, safety and calling (data, not voice)",
    71: "port operations", 72: "intership", 73: "intership, port operations", 74: "port operations",
    75: "AIS long-range (data, low power)", 76: "AIS long-range (data, low power)", 77: "intership",
}


def itu_marine() -> dict:
    entries = []
    for n in list(range(1, 29)) + list(range(60, 89)):
        ship = (156_000_000 + 50_000 * n) if n <= 28 else (156_025_000 + 50_000 * (n - 60))
        if n in (87, 88):
            # Since WRC-12 the B sides are AIS 1 and 2 and the A sides simplex.
            entries.append({"ref": f"{n}A", "name": f"Marine Ch {n}A", "freqHz": ship,
                            "sub": "intership, port operations (simplex)"})
            entries.append({"ref": f"AIS{n - 86}", "name": f"Marine AIS {n - 86} (Ch {n}B)",
                            "freqHz": ship + 4_600_000, "sub": "AIS ship positions (data, not voice)"})
            continue
        if n in lf.DUPLEX:
            entries.append({"ref": f"{n:02d}", "name": f"Marine Ch {n:02d}", "freqHz": ship + 4_600_000,
                            "sub": f"public correspondence, port operations (coast station; ships "
                                   f"{ship / 1e6:.3f} MHz)"})
        else:
            entries.append({"ref": f"{n:02d}", "name": f"Marine Ch {n:02d}", "freqHz": ship,
                            "sub": ITU_USES.get(n, "intership")})
    # The UK's own channels for marinas and yacht clubs (Ofcom, beside
    # Appendix 18): M (37A) and M2.
    entries.append({"ref": "M", "name": "Marine Ch M (37A)", "freqHz": 157_850_000,
                    "sub": "UK marinas and yacht clubs"})
    entries.append({"ref": "M2", "name": "Marine Ch M2", "freqHz": 161_425_000,
                    "sub": "UK yacht clubs and race management"})
    return {"schema": 1, "source": "itu-marine",
            "attribution": {"source": "ITU Radio Regulations", "licence": "Facts (no licence)",
                            "text": "Marine VHF channels from the ITU Radio Regulations, Appendix 18",
                            "url": ITU_URL},
            "fetched": "2026-10-23", "from": [ITU_URL], "coverage": "every country (channel plan)",
            "defaults": {"category": "marine", "mode": "fm", "step": 25000}, "entries": entries}


# ---------------------------------------------------------------- HM Coastguard
# MCA Advice Note 1033 (updated 4 April 2025), Table 5: each MRCC's MSI
# broadcast aerials and the channel each sends on. The leaflet names the
# aerial sites but gives no positions, so these are the named places'
# positions to about 5 km (a hill or headland), enough to say which
# aerial is near; never to point an antenna by.
HMCG = {
    "Aberdeen": [("Rosemarkie", 57.59, -4.12, 64), ("Windy Head", 57.64, -2.21, 63), ("Gregness", 57.13, -2.05, 64),
                 ("Inverbervie", 56.85, -2.28, 63), ("Fifeness", 56.28, -2.59, 62), ("Craigkelly", 56.07, -3.23, 63),
                 ("St Abbs Head", 55.91, -2.14, 64)],
    "Belfast": [("Limavady", 55.10, -6.93, 10), ("West Torr", 55.20, -6.10, 64), ("Black Mountain", 54.60, -6.02, 63),
                ("Orlock", 54.67, -5.58, 62), ("Lough Navar", 54.44, -7.90, 64), ("Slieve Martin", 54.10, -6.18, 64),
                ("Greenock", 55.94, -4.78, 62), ("Law Hill", 55.70, -4.85, 64), ("Rhu Stafnish", 55.36, -5.54, 10),
                ("Kilchiaran", 55.75, -6.45, 62), ("South Knapdale", 55.90, -5.55, 63)],
    "Dover": [("Bawdsey", 52.00, 1.42, 62), ("Walton", 51.85, 1.27, 63), ("Bradwell", 51.73, 0.89, 64),
              ("Shoeburyness", 51.53, 0.79, 63), ("Langdon", 51.13, 1.35, 64), ("Fairlight", 50.88, 0.64, 62)],
    "Falmouth": [("Berry Head", 50.40, -3.48, 63), ("Dartmouth", 50.35, -3.58, 10), ("Prawle", 50.21, -3.72, 62),
                 ("Rame Head", 50.31, -4.22, 64), ("Fowey", 50.33, -4.64, 10), ("Falmouth", 50.15, -5.06, 62),
                 ("Lizard", 49.96, -5.20, 63), ("Scilly", 49.92, -6.30, 64), ("Trevose Head", 50.55, -5.03, 62)],
    "Holyhead": [("Great Orme", 53.33, -3.86, 62), ("South Stack", 53.31, -4.70, 63), ("Moel-y-Parc", 53.22, -3.31, 63),
                 ("Caldbeck", 54.77, -3.06, 63), ("Langthwaite", 54.03, -2.76, 62), ("Snaefell", 54.26, -4.46, 64)],
    "Humber": [("Newton", 55.52, -1.62, 63), ("Cullercoats", 55.03, -1.43, 64), ("Boulby", 54.57, -0.82, 63),
               ("Ravenscar", 54.40, -0.49, 64), ("Flamborough", 54.12, -0.08, 63), ("Easington", 53.65, 0.12, 64),
               ("Mablethorpe", 53.34, 0.26, 62), ("Guy's Head", 52.80, 0.20, 63), ("Langham", 52.94, 0.96, 64),
               ("Trimingham", 52.90, 1.39, 63), ("Caister", 52.65, 1.72, 64), ("Lowestoft", 52.47, 1.75, 63)],
    "Milford Haven": [("Hartland", 51.02, -4.52, 64), ("Combe Martin", 51.20, -4.03, 63), ("Severn", 51.55, -2.65, 64),
                      ("St Hilary", 51.46, -3.40, 63), ("Mumbles", 51.57, -3.98, 64), ("Tenby", 51.67, -4.70, 62),
                      ("St Ann's Head", 51.68, -5.17, 62), ("Dinas Head", 52.02, -4.90, 64),
                      ("Blaenplwyf", 52.36, -4.10, 62)],
    "Shetland": [("Saxa Vord", 60.83, -0.84, 63), ("Collafirth Hill", 60.53, -1.39, 64), ("Lerwick", 60.15, -1.15, 62),
                 ("Fitful Head", 59.90, -1.38, 63), ("Wideford Hill", 58.99, -3.03, 64), ("Durness", 58.57, -4.75, 63),
                 ("Noss Head", 58.48, -3.05, 62)],
    "Solent": [("Newhaven", 50.78, 0.06, 62), ("St Boniface Down", 50.60, -1.20, 63), ("Needles", 50.66, -1.59, 62),
               ("Portland", 50.52, -2.45, 63), ("Beer Head", 50.68, -3.09, 62)],
    "Stornoway": [("Torosay", 56.45, -5.68, 10), ("Tiree", 56.50, -6.88, 63), ("Glengorm", 56.63, -6.17, 62),
                  ("Arisaig", 56.91, -5.84, 64), ("Barra", 57.00, -7.45, 10), ("Drumfearn", 57.15, -5.80, 63),
                  ("Skriaig", 57.38, -6.25, 10), ("Clettraval", 57.62, -7.43, 63), ("Rodel", 57.74, -6.96, 62),
                  ("Melvaig", 57.84, -5.80, 64), ("Forsnaval", 58.21, -7.00, 62), ("Portnaguran", 58.25, -6.17, 63),
                  ("Butt of Lewis", 58.51, -6.26, 10)],
}


def hmcg() -> dict:
    entries = []
    for mrcc, sites in HMCG.items():
        for site, lat, lon, ch in sites:
            hz, _note = lf.marine_channel_hz(str(ch))
            entries.append({"ref": f"{mrcc}-{site}".replace(" ", ""), "name": f"{mrcc} Coastguard ({site})",
                            "lat": lat, "lon": lon, "freqHz": hz,
                            "sub": f"Ch {ch} maritime safety information, every 3 hours (announced on Ch 16)"})
    entries.append({"ref": "67", "name": "HM Coastguard Ch 67", "freqHz": 156_375_000,
                    "sub": "UK small craft safety: the Coastguard's working channel after a call on Ch 16"})
    return {"schema": 1, "source": "hmcg",
            "attribution": {"source": "HM Coastguard (MCA)", "licence": "OGL v3.0",
                            "text": "Contains public sector information licensed under the Open Government Licence "
                                    "v3.0", "url": HMCG_URL},
            "fetched": "2026-10-23", "from": [HMCG_URL], "published": "2025-04-04",
            "coverage": "United Kingdom (aerial positions approximate)",
            "defaults": {"category": "marine", "mode": "fm", "step": 25000}, "entries": entries}


# ---------------------------------------------------------------- PMR446, CB, LPD433
CEPT_CB_KHZ = [26965, 26975, 26985, 27005, 27015, 27025, 27035, 27055, 27065, 27075, 27085, 27105, 27115, 27125,
               27135, 27155, 27165, 27175, 27185, 27205, 27215, 27225, 27255, 27235, 27245, 27265, 27275, 27285,
               27295, 27305, 27315, 27325, 27335, 27345, 27355, 27365, 27375, 27385, 27395, 27405]


def channels() -> dict:
    entries = []
    for n in range(1, 17):
        entries.append({"ref": f"pmr{n}", "category": "pmr", "name": f"PMR446 Ch {n}",
                        "freqHz": 446_006_250 + 12_500 * (n - 1), "step": 12500,
                        "sub": "licence-free handhelds" + (" (since 2018)" if n > 8 else "")})
    cept = {9: "emergency", 19: "calling and road users"}
    for n, khz in enumerate(CEPT_CB_KHZ, 1):
        entries.append({"ref": f"cept{n}", "category": "cb", "name": f"CB (CEPT) Ch {n}", "freqHz": khz * 1000,
                        "step": 10000, "sub": cept.get(n, "")})
    uk = {9: "emergency", 14: "calling", 19: "road users"}
    for n in range(1, 41):
        entries.append({"ref": f"uk{n}", "category": "cb", "name": f"CB (UK 27/81) Ch {n}",
                        "freqHz": 27_601_250 + 10_000 * (n - 1), "step": 10000, "sub": uk.get(n, "")})
    for n in range(1, 70):
        entries.append({"ref": f"lpd{n}", "category": "lpd", "name": f"LPD433 Ch {n}",
                        "freqHz": 433_075_000 + 25_000 * (n - 1), "step": 25000,
                        "sub": "licence-free low power (inside 70 cm)"})
    return {"schema": 1, "source": "channels",
            "attribution": {"source": "CEPT ERC Recommendation 70-03, Ofcom IR 2030", "licence": "Facts (no licence)",
                            "text": "", "url": "https://docdb.cept.org/document/845"},
            "fetched": "2026-10-23", "coverage": "Europe (CB UK 27/81: United Kingdom)",
            "defaults": {"mode": "fm"}, "entries": entries}


# ---------------------------------------------------------------- NCDXF/IARU
NCDXF_BEACONS = [("4U1UN", "United Nations, New York"), ("VE8AT", "Eureka, Nunavut, Canada"),
                 ("W6WX", "Mt Umunhum, California, USA"), ("KH6RS", "Maui, Hawaii"), ("ZL6B", "Masterton, New Zealand"),
                 ("VK6RBP", "Rolystone, Western Australia"), ("JA2IGY", "Mt Asama, Japan"),
                 ("RR9O", "Novosibirsk, Russia"), ("VR2B", "Hong Kong"), ("4S7B", "Colombo, Sri Lanka"),
                 ("ZS6DN", "Pretoria, South Africa"), ("5Z4B", "Kikuyu, Kenya"), ("4X6TU", "Tel Aviv, Israel"),
                 ("OH2B", "Lohja, Finland"), ("CS3B", "Sao Jorge, Madeira"), ("LU4AA", "Buenos Aires, Argentina"),
                 ("OA4B", "Lima, Peru"), ("YV5B", "Caracas, Venezuela")]
NCDXF_BANDS = [(14_100_000, "20 m"), (18_110_000, "17 m"), (21_150_000, "15 m"), (24_930_000, "12 m"),
               (28_200_000, "10 m")]


def ncdxf() -> dict:
    return {"schema": 1, "source": "ncdxf",
            "attribution": {"source": "NCDXF/IARU International Beacon Project", "licence": "Facts (no licence)",
                            "text": "Beacon schedule: the NCDXF/IARU International Beacon Project",
                            "url": NCDXF_URL},
            "credit": "NCDXF/IARU International Beacon Project", "fetched": "2026-10-23", "from": [NCDXF_URL],
            "coverage": "worldwide (HF)", "slotSeconds": 10,
            "frequencies": [f for f, _b in NCDXF_BANDS],
            "beacons": [{"call": c, "location": loc} for c, loc in NCDXF_BEACONS],
            "defaults": {"category": "beacon", "mode": "cw", "step": 10},
            "entries": [{"ref": b.replace(" ", ""), "name": f"NCDXF/IARU beacons {b}", "freqHz": f,
                         "sub": "18 beacons in turn, 10 s each, every 3 minutes"} for f, b in NCDXF_BANDS]}


# ---------------------------------------------------------------- licences
LICENCES = {
    "ourairports.json.gz": "Airfield frequencies extracted from OurAirports (https://ourairports.com/data/),\n"
                           "which its author has dedicated to the public domain.\n",
    "openaip.json": "Contains data from openAIP (www.openaip.net), CC BY-NC 4.0.\n\n"
                    "This file is licensed under the Creative Commons Attribution-NonCommercial 4.0\n"
                    "International licence: https://creativecommons.org/licenses/by-nc/4.0/\n"
                    "It may not be used for commercial purposes. It is kept apart from the rest of\n"
                    "OpenHamShack Radio, whose own licence (GPL-3.0-or-later) does not cover it.\n",
    "osm-marine.json": "Contains information from OpenStreetMap, which is made available here under the\n"
                       "Open Database License (ODbL).\n\n"
                       "This file is a derived database of OpenStreetMap data (c) OpenStreetMap\n"
                       "contributors (https://www.openstreetmap.org/copyright), and is itself made\n"
                       "available under the Open Database License 1.0:\n"
                       "https://opendatacommons.org/licenses/odbl/1-0/\n"
                       "Made by tools/localfreq-build.py from an Overpass API query (the query is in\n"
                       "that script, ohsradio/localfreq.py overpass_query_area).\n",
    "hmcg.json": "Contains public sector information licensed under the Open Government Licence v3.0:\n"
                 "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/\n"
                 "Source: Maritime and Coastguard Agency, Advice Note 1033 - Maritime Safety\n"
                 "Information (MSI) Leaflet, updated 4 April 2025. The aerial positions are\n"
                 "OpenHamShack's approximations of the places the leaflet names.\n",
    "itu-marine.json": "Marine VHF channel plan from the ITU Radio Regulations, Appendix 18 (facts;\n"
                       "compiled for OpenHamShack Radio, GPL-3.0-or-later with the rest of it).\n",
    "channels.json": "PMR446, CB (CEPT and UK 27/81) and LPD433 channel plans (facts; CEPT ERC\n"
                     "Recommendation 70-03 and Ofcom IR 2030), compiled for OpenHamShack Radio.\n",
    "ncdxf.json": "The NCDXF/IARU International Beacon Project's beacons and schedule\n"
                  "(https://www.ncdxf.org/beacon/), credited to NCDXF and the IARU.\n",
}


def write(name: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lf.write_file(OUT / name, data)
    (OUT / (name.split(".")[0] + ".LICENCE.txt")).write_text(LICENCES[name], encoding="utf-8")
    print(f"{name}: {len(lf.expand(data))} frequencies, {(OUT / name).stat().st_size} bytes")


def fetch_cached(src: Path, url: str, offline: bool) -> bytes:
    path = src / url.rsplit("/", 1)[-1]
    if not path.exists():
        if offline:
            raise SystemExit(f"{path} is missing and --offline was given")
        path.write_bytes(lf.http_fetch(url, timeout=300))
    return path.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(Path.home() / "build" / "localfreq-src"))
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--offline", action="store_true", help="use only what is already in --src")
    a = ap.parse_args()
    src = Path(a.src)
    src.mkdir(parents=True, exist_ok=True)
    want = set(a.only or ["ourairports", "osm-marine", "openaip", "itu-marine", "hmcg", "channels", "ncdxf"])
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if "itu-marine" in want:
        write("itu-marine.json", itu_marine())
    if "hmcg" in want:
        write("hmcg.json", hmcg())
    if "channels" in want:
        write("channels.json", channels())
    if "ncdxf" in want:
        write("ncdxf.json", ncdxf())
    if "ourairports" in want:
        a_csv = fetch_cached(src, lf.OURAIRPORTS_URLS[0], a.offline).decode("utf-8")
        f_csv = fetch_cached(src, lf.OURAIRPORTS_URLS[1], a.offline).decode("utf-8")
        write("ourairports.json.gz", lf.build_ourairports(a_csv, f_csv, today))
    if "osm-marine" in want:
        path = src / "osm-marine-overpass.json"
        if not path.exists():
            if a.offline:
                raise SystemExit(f"{path} is missing and --offline was given")
            q = lf.overpass_query_area(BUNDLE_AREA)
            path.write_bytes(lf.http_fetch(lf.OVERPASS_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                                           ("data=" + lf._quote(q)).encode(), timeout=400))
        coverage = "Great Britain, Ireland, the Isle of Man and the Channel Islands (" + ", ".join(BUNDLE_AREA) + ")"
        write("osm-marine.json", lf.build_osm_marine(json.loads(path.read_bytes()), today, coverage))
    if "openaip" in want:
        key = os.environ.get("OPENAIP_API_KEY", "")
        items: list = []
        coverage = "none: no openAIP API key when this release was built; Refresh fills it around the station"
        if key:
            items = []
            for iso in ("GB", "IE"):
                page = 1
                while True:
                    url = f"{lf.OPENAIP_URL}?country={iso}&limit=1000&page={page}" + "".join(
                        f"&type={t}" for t in sorted(lf.OPENAIP_TYPES))
                    ans = json.loads(lf.http_fetch(url, {"x-openaip-api-key": key}))
                    items += ans.get("items", [])
                    if page >= int(ans.get("totalPages") or 1):
                        break
                    page += 1
            coverage = "Great Britain and Ireland (GB, IE)"
        write("openaip.json", lf.build_openaip(items, today, coverage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
