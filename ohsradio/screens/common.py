"""What Radio's screens share: the library, the map's ground, the station
mark, the receive audio, and small wording helpers."""
from __future__ import annotations

from ohscore import shacklibs
from ohscore.countries import distance_bearing, locator_position

from ohsradio.i18n import _

OSM = "© OpenStreetMap contributors"
# Words a ticking value needs (SCREENS.md §2.1 `words`), in the screen's
# language: the box translates, the client only ticks.
WORDS = {"s": "{n} s", "min": "{n} min", "h": "{n} h", "d": "{n} d", "ago": "{d} ago"}


def ui():
    return shacklibs.ui()


def ground(style_key: str, default: str = "real", zoom=(3, 14)) -> dict:
    """The map's ground: Radio's own tiles and land (SERVER-API "Map"),
    the land first and tiles over it as they come; `style` a per-device
    choice (night recolours the tiles)."""
    return {"tiles": "api/map/tiles/{z}/{x}/{y}.png", "land": "api/map/land", "zoom": list(zoom),
            "style": ui().local(style_key, default)}


def station(radio) -> tuple[float, float] | None:
    """The station: the centre of its locator square, as every table
    measures distance from (the station profile's locator)."""
    return locator_position(radio.state().get("locator") or "")


def station_layer(radio) -> dict:
    """The station's own mark, always labelled, or an empty layer without
    a locator."""
    p = ui().p
    here = station(radio)
    items = [] if here is None else [{"lat": round(here[0], 5), "lon": round(here[1], 5), "sym": "station",
                                      "tone": "default", "label": radio.state().get("callsign") or _("Station"),
                                      "pin": True}]
    return p.layer("station", "markers", items=items)


def audio(**kw) -> dict:
    """Radio's receive audio, stereo (the PCM stream is mono unless asked),
    played while the screen shows and stopped when it is popped (§9)."""
    return ui().p.audio("audio", "api/audio/rx", params={"channels": 2}, autoplay=True, **kw)


def volume() -> dict:
    """The volume: the box's own (api/set volume), patched as it moves."""
    a = ui().A
    return ui().p.slider(None, 0, 1, a.post("api/set", {"volume": a.VALUE}, level="control"), step=0.05,
                         id="volume", text=_("Volume"), w=220)


def mute() -> dict:
    # The player's own mute, as on the TV: nothing changes on the box.
    return ui().p.button(_("Mute"), ui().A.part("audio", "mute"), icon="mute", style="quiet")


def dist_text(km, bearing=None) -> str | None:
    if km is None:
        return None
    if bearing is None:
        return _("{km} km").format(km=f"{km:.1f}")
    return _("{km} km · {deg}°").format(km=f"{km:.1f}", deg=f"{bearing:.0f}")


def nm_text(km, bearing=None) -> str | None:
    """A distance at sea or in the air, in nautical miles as the old app
    and every chart and ATC say it (MapGeo.kt Nautical): a tenth under
    100 nm, whole miles beyond. Radio has no units setting; the old app
    used nm, kn and ft on Ships and Aircraft and metric on APRS and
    Sondes, and so do these screens."""
    if km is None:
        return None
    nm = km / 1.852
    n = f"{nm:.1f}" if nm < 100 else f"{nm:.0f}"
    if bearing is None:
        return _("{nm} nm").format(nm=n)
    return _("{nm} nm · {deg}°").format(nm=n, deg=f"{bearing:.0f}")


def place(here, lat, lon):
    """(km, bearing) from the station, or (None, None)."""
    if here is None or lat is None or lon is None:
        return None, None
    return distance_bearing(here[0], here[1], lat, lon)


def mhz(hz, decimals: int = 3) -> str | None:
    if hz is None:
        return None
    return _("{mhz} MHz").format(mhz=f"{float(hz) / 1e6:.{decimals}f}")


def sync(ch, coll: str, items: dict, order: list[str] | None = None, *, trail: str | None = None,
         trail_max: int = 30) -> None:
    """Make a channel's collection `coll` hold exactly `items` (key ->
    fields), in `order` (default: as given). Fields are replaced whole, so
    one that has gone is deleted; the hub sends only what changed.

    `trail`: an item field that tone; a point is pushed onto the item's
    `trail` each time its lat/lon has moved since the last, keeping the
    last `trail_max` (SCREENS.md §4.3: trails grow by push)."""
    with ch.lock:
        have = ch.state["collections"].get(coll, {}).get("items", {})
        old = {k: dict(v) for k, v in have.items()}
    gone = [k for k in old if k not in items]
    if gone:
        ch.rm(coll, *gone)
    for k, fields in items.items():
        prev = old.get(k)
        f = {kk: v for kk, v in fields.items()}
        if prev is not None:
            for kk in prev:
                if kk not in f and kk != "trail":
                    f[kk] = None
        ch.up(coll, k, f)
        if trail is not None and f.get("lat") is not None and f.get("lon") is not None:
            moved = prev is None or (prev.get("lat"), prev.get("lon")) != (f["lat"], f["lon"])
            if moved:
                ch.push(coll, k, "trail", [[f["lat"], f["lon"], f.get(trail) or "default"]], max=trail_max)
    ch.order(coll, list(order) if order is not None else list(items))
