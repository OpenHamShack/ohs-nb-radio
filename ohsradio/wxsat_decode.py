"""Weather-satellite pictures: SatDump decodes each Meteor-M pass Radio
recorded (wxsat.py) after LOS, and the pictures are kept and served
(docs/SERVER-API.md "Weather satellites"; Brian, 29/10/2026).

    dec = Decoder(folder, binary=None)   # made by WxSat
    dec.submit(job)                      # a pass recorded: decode it, later
    dec.images.listing()                 # GET api/wxsat/images
    dec.images.file(id, product, thumb, ext)  # GET api/wxsat/images/<id>/<product>.<ext>
    dec.images.composite(kind, since)    # GET api/wxsat/composite

**SatDump, never a decoder of our own** (Brian's rule): its CLI, GPL-3.0,
run headless as a separate program on the recording -

    satdump meteor_m2-x_lrpt baseband <recording> <out> --samplerate <rate>
            --baseband_format cs16 --tle_override <tle file>

- the same LRPT pipeline its GUI runs (OQPSK demodulator, the
Viterbi/Reed-Solomon CCSDS decoder, the MSU-MR imager's products), on the
SigMF data file as it is: complex int16 at the recording's own rate (800
kS/s from the RSPdx), the satellite at 0 Hz, the Doppler left for its
demodulator's loop to follow. Store images carry SatDump 1.2 (the
Containerfile says how); a form without the program (the desktop) records
passes as before and says the pictures need it.

**Offline, always.** SatDump fetches element sets from Celestrak at start
whenever its own list is empty or a day old - and "Never" in its settings
does not stop the first: an empty list fetches regardless (tle.cpp
autoUpdateTLE, measured 29/10/2026 in a container with no network: five
DNS lookups for celestrak.org before it gave up). `--tle_override <file>`
is the switch that does: SatDump then loads that file and nothing else,
and never calls autoUpdateTLE (init.cpp). The file is the element set the
pass was predicted from, which the recording carries (wxsat.py's
`openhamshack:wxsat.tle`), so the projection uses exactly the orbit Radio
used, from wxsat_tle.py's sources and nowhere else; with wxsatOnlineTle
off nothing at all leaves the station. Its settings (written as
settings.json in the run's own folder, which SatDump reads before
$HOME's) add log_to_file off and tle_update_interval "Never" besides, and
HOME is the run's folder, so nothing is written under Radio's own.
Space-Track, its other way out, is used only with an account set, which
these settings never have.

**One pass at a time, at the lowest priority.** One daemon thread at nice
19 (as dmrids.py's and wxsat_tle.py's), and SatDump started under nice(1)
at 19 too: a pass decodes
in a few minutes of one core, and must never take time from the receive
path or the decoders. Passes queue in order of LOS. A decode taking more
than TIMEOUT_S is ended, and the end does not depend on this process:
SatDump runs under timeout(1), which sends TERM and then KILL by itself.
On 29-30/10 a hung SatDump pushed the container into memory throttling
that froze the server's own threads for six hours, this one's
Popen.wait() with them, so a Python-side timeout never fired. A timeout
here still keeps whatever pictures SatDump had already written: 1.2.2's
hang on a missing map file came after every product was saved. SatDump
also runs under stdbuf(1) line-buffered, so its log holds its last line
even when it is killed - without it a killed run left only a start-up
line, which was then reported as the error.

**What it makes** (SatDump 1.2's tree, which the tests' fake SatDump
reproduces from its source - plugins/meteor_support .../msumr and
src-core/products/processor/image_processor.cpp):

    <out>/meteor_m2-x_lrpt.soft, .cadu       demodulated and decoded frames
    <out>/dataset.json, telemetry.json
    <out>/MSU-MR/product.cbor                the imager's product
    <out>/MSU-MR/MSU-MR-<n>.png              each channel heard (none: no lock)
    <out>/MSU-MR/msu_mr_rgb_<Name>.png       each RGB composite its channels allow
    <out>/MSU-MR/msu_mr_<Name>.png           each one-channel composite
    <out>/MSU-MR/..._corrected.png           the same, corrected for the Earth's curve
    <out>/MSU-MR/rgb_msu_mr_..._projected.tif  the composites asked to be projected

`<Name>` is the composite's name with spaces and slashes as "_" and "µ"
as "u" ("AVHRR 221 False Color" -> `AVHRR_221_False_Color`). Each
composite becomes a product named by its kind: `rgb` is "AVHRR 221 False
Color" (channels 2, 2, 1: the classic Meteor daylight picture), `ir` is
"10.8µm Thermal IR (Uncalibrated)" (day and night), every other one its
name in lower case with "-" between words (`mcir`, `natural-color`,
`msu-mr-124-false-color`...), and each channel `ch<n>`. The corrected
picture is the one kept where there is one: it is the one that looks
right. `_map` pictures (borders drawn on) are not made.

**Projection.** SatDump's own setting projects two of its composites onto
a whole-world 4096 x 2048 equirectangular PNG with borders drawn on: ~10
km a pixel, most of it empty, and nothing in the file saying where the
picture is. These settings instead project `rgb` and `ir` with its "auto"
equirectangular projection (the bounds of the pass, 2048 x 2048) and as a
GeoTIFF (`img_format` ".tif"), with no borders; SatDump writes the
projection into the file as GeoTIFF ModelTiepoint (the top-left corner's
longitude and latitude) and ModelPixelScale (degrees a pixel) tags
(geotiff_write.cpp), which is where the bounds here come from - read
from the file, never assumed. The 2048 x 2048 is not square in degrees;
the picture is resampled to square degrees (at most 2048 px on its long
side) so a client may also show it as it is.

**The projection is WebP with alpha**, transparent outside the swath
(29/10/2026; until then a JPEG, black outside, which a map showing
several passes at once had to draw over its neighbours). Lossy at
OVERLAY_QUALITY with the alpha plane lossless, so the swath's edge stays
exactly where SatDump put it.
Which pixels are outside comes from the GeoTIFF itself (swath_alpha):
its alpha sample, which SatDump's projection writes, else a GDAL_NODATA
value, else - a file with neither - the pixels black in every band,
shrunk by EDGE_PX so a dark pixel on the swath's edge is not cut out.
A Pillow built without WebP writes PNG with alpha instead, and says so in
the log once; never JPEG, which would lose the transparency the clients
now rely on. The format is in meta.json ("ext") and so in the URL; a
projection made before this, with no "ext", is the JPEG it always was
and is still served. The product pictures and their thumbnails stay
JPEG: they are shown on their own, never over a map.

**A pass with no usable lock is failed with a plain reason**, not an
error: nothing decoded at all (`.cadu` empty: no signal the decoder could
lock to), or frames decoded but too few image lines for a picture
(MIN_LINES). SatDump itself failing is failed with its last log line.

**Kept**: data/wxsat/images/<imageId>/ - the JPEGs, the projections
(WebP), a 400 px-wide thumbnail of each, and meta.json; SatDump's own
folder is deleted when it is done. The pictures obey the recordings'
disk rules (the limit wxsat.py's recordings obey): together they may
take at most IMAGES_SHARE of the recordings' limit, the oldest pass's
going first, and nothing is decoded while free space is below the
recordings' floor. The recording itself stays a recording, listed and
pruned as any other.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.wxsat")

PIPELINE = "meteor_m2-x_lrpt"
TIMEOUT_S = 1800.0
KILL_GRACE_S = 30                  # timeout(1)'s TERM to KILL
THUMB_W = 400
PROJ_MAX = 2048
MIN_LINES = 64                     # under this many lines there is no picture to speak of
IMAGES_SHARE = 0.1                 # of the recordings' limit
IMAGES_DEFAULT_LIMIT = 1 << 30     # with no recordings to share with (the desktop, a test)
WORK_ROOM = 600 << 20              # SatDump's working files for one pass: soft symbols, PNGs
JPEG_QUALITY = 88
OVERLAY_QUALITY = 80               # the projection's colour; its alpha is always lossless
EDGE_PX = 2                        # the black-pixel mask shrunk by this much (module docstring)
# What a picture is served as, by the extension its URL ends in.
CONTENT_TYPES = {"jpg": "image/jpeg", "webp": "image/webp", "png": "image/png"}
RGB_NAME = "AVHRR 221 False Color"
IR_NAME = "10.8µm Thermal IR (Uncalibrated)"
PROJECTED_KINDS = ("rgb", "ir")
# The projection asked of SatDump for the composites a client lays on a
# map (module docstring): its "auto" equirectangular - the pass's own
# bounds - written as a GeoTIFF, no borders drawn.
_PROJECT = {"draw_map_overlay": False, "img_format": ".tif",
            "config": {"type": "equirec", "auto": True, "width": PROJ_MAX, "height": PROJ_MAX}}
SETTINGS = {
    "satdump_general": {
        "log_to_file": {"value": False}, "log_level": {"value": "info"},
        "tle_update_interval": {"value": "Never"}, "product_format": {"value": "png"},
        "image_format": {"value": "png"}, "auto_process_products": {"value": True}},
    "viewer": {"instruments": {"msu_mr": {"rgb_composites": {
        RGB_NAME: {"project": _PROJECT},
        IR_NAME: {"project": _PROJECT},
        # Projected by SatDump's own settings onto the whole world; made
        # cheap here, and not kept (only rgb and ir are).
        "AVHRR 3a21 False Color": {"project": dict(_PROJECT, config=dict(_PROJECT["config"], width=256,
                                                                           height=256))},
        "MCIR": {"draw_map_overlay": False},
        "MSA": {"draw_map_overlay": False}}}}},
}
_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_KIND_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def file_stem(name: str) -> str:
    """A composite's name as SatDump names its file (image_processor.cpp)."""
    return name.replace(" ", "_").replace("/", "_").replace("µ", "u").replace("λ=", "")


KIND_BY_STEM = {file_stem(RGB_NAME): "rgb", file_stem(IR_NAME): "ir"}


def satdump_binary() -> str | None:
    """SatDump's CLI: OHS_SATDUMP if set (a test's fake), else on PATH."""
    want = os.environ.get("OHS_SATDUMP", "").strip()
    if want:
        return want if os.access(want, os.X_OK) else None
    return shutil.which("satdump")


# ------------------------------------------------------------------ pictures
def _pil():
    try:
        from PIL import Image
    except ImportError:
        return None
    return Image


def _as_rgb8(a: np.ndarray) -> np.ndarray:
    """Any SatDump picture as H x W x 3 uint8: 16-bit scaled down, grey
    made RGB, alpha dropped (black where transparent, as JPEG must)."""
    if a.dtype != np.uint8:
        a = (np.asarray(a, np.uint32) >> 8).astype(np.uint8) if a.dtype in (np.uint16, np.int32, np.uint32) \
            else np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        a = np.repeat(a[:, :, None], 3, axis=2)
    if a.shape[2] == 4:
        alpha = a[:, :, 3:4].astype(np.uint16)
        a = (a[:, :, :3].astype(np.uint16) * alpha // 255).astype(np.uint8)
    elif a.shape[2] == 2:                       # grey and alpha
        a = np.repeat((a[:, :, :1].astype(np.uint16) * a[:, :, 1:2] // 255).astype(np.uint8), 3, axis=2)
    return np.ascontiguousarray(a[:, :, :3])


def read_png(path: Path) -> np.ndarray:
    Image = _pil()
    with Image.open(path) as im:
        if im.mode in ("I;16", "I;16B", "I"):
            return _as_rgb8(np.asarray(im, dtype=np.uint16 if im.mode != "I" else np.int32))
        if im.mode == "P":
            im = im.convert("RGBA")
        return _as_rgb8(np.asarray(im))


_TIFF_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


def swath_alpha(a: np.ndarray, nodata: float | None) -> np.ndarray:
    """H x W uint8, 255 inside the satellite's swath and 0 outside, from a
    GeoTIFF's raw H x W x samples array (module docstring, "The projection
    is WebP with alpha"). Its alpha sample when it has one (2 or 4
    samples: SatDump's projection always writes RGBA), cut at half way so
    the mask is two-valued however SatDump blended its edge; else its
    GDAL_NODATA value in every band; else black in every band - which
    real pictures have inside the swath too, at its very edge where the
    projection's interpolation darkens it, so that mask is shrunk by
    EDGE_PX (a 3 x 3 minimum, EDGE_PX times) before it is used."""
    spp = a.shape[2]
    if spp in (2, 4):
        top = 0xffff if a.dtype.itemsize == 2 else 0xff
        return np.where(a[:, :, -1] >= (top + 1) // 2, 255, 0).astype(np.uint8)
    if nodata is not None:
        return np.where((a == nodata).all(axis=2), 0, 255).astype(np.uint8)
    from PIL import ImageFilter
    Image = _pil()
    outside = Image.fromarray(np.where((a == 0).all(axis=2), 255, 0).astype(np.uint8), "L")
    for _i in range(EDGE_PX):
        outside = outside.filter(ImageFilter.MinFilter(3))
    return (255 - np.asarray(outside)).astype(np.uint8)


def read_geotiff(path: Path) -> tuple[np.ndarray, dict]:
    """(picture as H x W x 4 uint8 RGBA, alpha from swath_alpha, and
    {"n","s","e","w"}) from the GeoTIFF SatDump writes for a projection
    (tiffio.cpp save_tiff, geotiff_write.cpp): uncompressed, contiguous
    samples in strips, 8 or 16 bits, ModelTiepoint (33922) and
    ModelPixelScale (33550) in degrees, perhaps GDAL_NODATA (42113).
    Read here rather than by Pillow, which takes 16-bit RGBA only in some
    versions; raises ValueError for anything else."""
    raw = Path(path).read_bytes()
    if raw[:4] not in (b"II*\0", b"MM\0*"):
        raise ValueError(_("not a TIFF"))
    e = "<" if raw[:2] == b"II" else ">"
    (ifd,) = struct.unpack_from(e + "I", raw, 4)
    (n,) = struct.unpack_from(e + "H", raw, ifd)
    tags: dict[int, tuple] = {}
    for i in range(n):
        tag, typ, count, val = struct.unpack_from(e + "HHI4s", raw, ifd + 2 + 12 * i)
        code = _TIFF_TYPES.get(typ)
        if code is None:
            continue
        size = struct.calcsize(code) * count
        data = val if size <= 4 else raw[struct.unpack(e + "I", val)[0]:][:size]
        tags[tag] = (data[:size].rstrip(b"\0"),) if code == "s" else struct.unpack(e + code * count, data[:size])
    w, h = tags[256][0], tags[257][0]
    bits = tags.get(258, (8,))[0]
    spp = tags.get(277, (1,))[0]
    if tags.get(259, (1,))[0] != 1 or bits not in (8, 16) or tags.get(284, (1,))[0] != 1:
        raise ValueError(_("a TIFF SatDump does not write"))
    dt = np.dtype(np.uint8 if bits == 8 else (e + "u2"))
    want = w * h * spp * dt.itemsize
    buf = b"".join(raw[o:o + c] for o, c in zip(tags[273], tags[279]))
    if len(buf) < want:
        raise ValueError(_("a TIFF cut short"))
    a = np.frombuffer(buf[:want], dt).reshape(h, w, spp)
    if 33922 not in tags or 33550 not in tags:
        raise ValueError(_("no GeoTIFF tags: the projection is not in the file"))
    i, j, _k, x, y, _z = tags[33922][:6]
    sx, sy = tags[33550][:2]
    west, north = x - i * sx, y + j * sy
    bounds = {"n": north, "s": north - h * sy, "e": west + w * sx, "w": west}
    nodata = None
    if 42113 in tags:
        try:
            nodata = float(tags[42113][0].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            nodata = None
    alpha = swath_alpha(a, nodata)
    rgb = _as_rgb8(a.astype(np.uint16) if bits == 16 else a)
    return np.dstack([rgb, alpha]), bounds


def _save_jpeg(a: np.ndarray, path: Path, width: int | None = None, height: int | None = None) -> tuple[int, int]:
    Image = _pil()
    im = Image.fromarray(a, "RGB")
    if width is not None and (width, height or im.height) != im.size:
        if height is None:
            height = max(1, round(im.height * width / im.width))
        im = im.resize((width, height), Image.LANCZOS)
    tmp = path.with_suffix(".tmp")
    im.save(tmp, "JPEG", quality=JPEG_QUALITY, optimize=True)
    os.replace(tmp, path)
    return im.size


_overlay_said = False


def webp_supported() -> bool:
    try:
        from PIL import features
        return bool(features.check("webp"))
    except Exception:  # noqa: BLE001 - a Pillow too old to say has none
        return False


def overlay_ext() -> str:
    """"webp", or "png" where this Pillow cannot write WebP (said in the
    log once): never JPEG, which has no transparency."""
    global _overlay_said
    if webp_supported():
        return "webp"
    if not _overlay_said:
        _overlay_said = True
        log.warning("weather satellites: this Pillow has no WebP support: projections are written as PNG")
    return "png"


def _save_overlay(rgba: np.ndarray, path: Path, width: int, height: int) -> tuple[int, int]:
    """The projection as `path` (.webp or .png, overlay_ext()) at
    width x height. Resampled as RGBA, which Pillow does premultiplied,
    so the swath's edge takes no black from outside; the alpha is then
    made two-valued again, as swath_alpha gave it."""
    Image = _pil()
    im = Image.fromarray(rgba, "RGBA")
    if (width, height) != im.size:
        im = im.resize((width, height), Image.LANCZOS)
        r, g, b, a = im.split()
        im = Image.merge("RGBA", (r, g, b, a.point(lambda v: 255 if v >= 128 else 0)))
    tmp = path.with_suffix(".tmp")
    if path.suffix == ".webp":
        # alpha_quality 100: the alpha plane lossless, whatever the colour's quality.
        im.save(tmp, "WEBP", quality=OVERLAY_QUALITY, alpha_quality=100, method=4)
    else:
        im.save(tmp, "PNG", optimize=True)
    os.replace(tmp, path)
    return im.size


# ------------------------------------------------------------------ SatDump's tree
def harvest(out: Path, night: bool = False) -> dict:
    """What SatDump made in `out` (module docstring's tree): {"lines": the
    most image lines of any channel, "cadu": bytes decoded, "products":
    [(kind, name, path)], "projected": {kind: path}}. A `night` pass leads
    with MCIR: its 221 composite is built from visible channels that are
    flat grey in the dark (ohs-box's first picture, 29/10 22:30Z), and
    N2-3 sends 3.9 um rather than 10.8 um then, so there is no "ir"."""
    msu = out / "MSU-MR"
    cadu = 0
    for p in out.glob("*.cadu"):
        try:
            cadu += p.stat().st_size
        except OSError:
            pass
    channels: dict[str, Path] = {}
    composites: dict[str, tuple[str, Path]] = {}
    projected: dict[str, Path] = {}
    lines = 0
    names = sorted(p.name for p in msu.iterdir()) if msu.is_dir() else []
    for name in names:
        p = msu / name
        m = re.fullmatch(r"MSU-MR-(\d+)\.png", name)
        if m:
            channels[f"ch{m.group(1)}"] = p
            continue
        m = re.fullmatch(r"rgb_msu_mr_(?:rgb_)?(.+)_projected\.tif", name)
        if m:
            kind = KIND_BY_STEM.get(m.group(1))
            if kind in PROJECTED_KINDS:
                projected[kind] = p
            continue
        m = re.fullmatch(r"msu_mr_(?:rgb_)?(.+?)(_corrected)?\.png", name)
        if m and not m.group(1).endswith("_map"):
            stem = m.group(1)
            kind = KIND_BY_STEM.get(stem) or slug(stem)
            if not kind:
                continue
            if m.group(2) or kind not in composites:      # the corrected one wins
                composites[kind] = (stem.replace("_", " "), p)
    if channels:
        Image = _pil()
        for p in channels.values():
            try:
                with Image.open(p) as im:
                    lines = max(lines, im.height)
            except OSError:
                pass
    products = [(k, n, p) for k, (n, p) in composites.items()]
    lead = ("mcir", "ir", "rgb") if night else ("rgb", "ir")
    products.sort(key=lambda t: (lead.index(t[0]) if t[0] in lead else len(lead), t[0]))
    products += [(k, _("Channel {n}").format(n=k[2:]), p) for k, p in sorted(channels.items())]
    return {"lines": lines, "cadu": cadu, "products": products, "projected": projected}


# ------------------------------------------------------------------ the pictures kept
class Images:
    """data/wxsat/images: one folder per decoded pass, named by its
    imageId, with meta.json beside the pictures."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def _metas(self) -> list[dict]:
        out = []
        try:
            dirs = list(self.folder.iterdir())
        except OSError:
            return out
        for d in dirs:
            try:
                m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("id") == d.name:
                out.append(m)
        out.sort(key=lambda m: str(m.get("aos", "")))
        return out

    def listing(self) -> list[dict]:
        """GET api/wxsat/images: newest pass first."""
        return [self.view(m) for m in reversed(self._metas())]

    @staticmethod
    def view(m: dict) -> dict:
        base = f"api/wxsat/images/{m['id']}"
        prod = [{"kind": p["kind"], "name": p["name"], "url": f"{base}/{p['kind']}.jpg", "w": p["w"], "h": p["h"]}
                for p in m.get("products", [])]
        pj = m.get("projected") or {}
        main = next((pj[k] for k in PROJECTED_KINDS if k in pj), None)
        return {"id": m["id"], "passId": m["passId"], "sat": m["sat"], "aos": m["aos"], "maxElDeg": m["maxElDeg"],
                "products": prod,
                "projected": None if main is None else {"url": Images.projected_url(m["id"], main),
                                                        "w": main["w"], "h": main["h"],
                                                        "bounds": main["bounds"]}}

    @staticmethod
    def projected_url(image_id: str, p: dict) -> str:
        # No "ext": a pass decoded before projections were WebP, still a JPEG.
        return f"api/wxsat/images/{image_id}/{p['kind']}-projected.{p.get('ext', 'jpg')}"

    def composite(self, kind: str, since_iso: str) -> list[dict]:
        """GET api/wxsat/composite: the projected `kind` of every pass with
        AOS at or after `since_iso`, oldest first."""
        out = []
        for m in self._metas():
            p = (m.get("projected") or {}).get(kind)
            if p is None or str(m.get("aos", "")) < since_iso:
                continue
            out.append({"imageId": m["id"], "aos": m["aos"], "url": Images.projected_url(m["id"], p),
                        "bounds": p["bounds"]})
        return out

    def file(self, image_id: str, product: str, thumb: bool, ext: str = "jpg") -> bytes | None:
        """One picture, or None for anything not in the folder (a path, a
        dot or an unknown product included). Products are JPEG only; a
        projection may be any of CONTENT_TYPES (the old ones JPEG)."""
        if not _ID_OK.match(image_id) or ".." in image_id:
            return None
        projected = product.endswith("-projected")
        kind = product[:-len("-projected")] if projected else product
        if not _KIND_OK.match(kind) or ext not in CONTENT_TYPES or (ext != "jpg" and not projected):
            return None
        name = f"{product}.thumb.{ext}" if thumb else f"{product}.{ext}"
        try:
            return (self.folder / image_id / name).read_bytes()
        except OSError:
            return None

    def used(self) -> int:
        total = 0
        for p in self.folder.glob("*/*"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def prune(self, limit_bytes: int, keep: str | None = None) -> list[str]:
        """Delete the oldest passes' pictures until they take at most
        `limit_bytes`, never `keep` (the one just made)."""
        gone = []
        with self.lock:
            used = self.used()
            for m in self._metas():
                if used <= limit_bytes:
                    break
                if m["id"] == keep:
                    continue
                d = self.folder / m["id"]
                size = sum(p.stat().st_size for p in d.glob("*") if p.is_file())
                shutil.rmtree(d, ignore_errors=True)
                used -= size
                gone.append(m["id"])
                log.info("weather satellites: pictures over their share of the disk: deleted %s", m["id"])
        return gone

    def save(self, image_id: str, job: dict, found: dict) -> dict:
        """Make the JPEGs, projections and thumbnails of `found` (harvest())
        into the pass's folder, written whole and renamed into place."""
        final = self.folder / image_id
        tmp = self.folder / f".{image_id}.part"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        products = []
        for kind, name, path in found["products"]:
            try:
                a = read_png(path)
            except Exception as e:  # noqa: BLE001 - one unreadable picture is not the pass's end
                log.warning("weather satellites: %s of %s unreadable: %s", kind, image_id, e)
                continue
            w, h = _save_jpeg(a, tmp / f"{kind}.jpg")
            _save_jpeg(a, tmp / f"{kind}.thumb.jpg", min(THUMB_W, w))
            products.append({"kind": kind, "name": name, "w": w, "h": h})
        projected = {}
        ext = overlay_ext()
        for kind, path in found["projected"].items():
            try:
                a, bounds = read_geotiff(path)
            except (OSError, ValueError, KeyError, struct.error) as e:
                log.warning("weather satellites: the projected %s of %s unreadable: %s", kind, image_id, e)
                continue
            # Square degrees: the "auto" projection fits the pass to a
            # square of pixels whatever its shape in degrees.
            dlon, dlat = bounds["e"] - bounds["w"], bounds["n"] - bounds["s"]
            if dlon <= 0 or dlat <= 0:
                continue
            scale = PROJ_MAX / max(dlon, dlat)
            pw, ph = max(1, round(dlon * scale)), max(1, round(dlat * scale))
            w, h = _save_overlay(a, tmp / f"{kind}-projected.{ext}", pw, ph)
            _save_overlay(a, tmp / f"{kind}-projected.thumb.{ext}", min(THUMB_W, w),
                          max(1, round(h * min(THUMB_W, w) / w)))
            projected[kind] = {"kind": kind, "ext": ext, "w": w, "h": h,
                               "bounds": {k: round(float(v), 5) for k, v in bounds.items()}}
        meta = {"id": image_id, "passId": job["passId"], "sat": job["sat"], "aos": job["aos"],
                "maxElDeg": job["maxElDeg"], "products": products, "projected": projected,
                "lines": found["lines"], "decodedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        with self.lock:
            shutil.rmtree(final, ignore_errors=True)
            os.replace(tmp, final)
        return meta


# ------------------------------------------------------------------ the worker
class Decoder:
    """The queue of passes to decode and the one thread that does it.
    `done(job, plan, why, image_id)` is called from that thread when a
    pass is finished; `disk()` gives {"limitBytes", "freeBytes",
    "floorBytes"} of the recordings (None: no limits but our own)."""

    def __init__(self, folder: Path, done, binary: str | None = None, disk=None, timeout_s: float = TIMEOUT_S):
        self.folder = Path(folder)
        self.images = Images(self.folder / "images")
        self.work = self.folder / "work"
        self.done = done
        self.binary = binary
        self.disk = disk
        self.timeout_s = timeout_s
        self.q: queue.Queue = queue.Queue()
        self.current: dict | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.stopping = False
        self.proc: subprocess.Popen | None = None

    def program(self) -> str | None:
        if self.binary is not None:
            return self.binary if os.access(self.binary, os.X_OK) else None
        return satdump_binary()

    def available(self) -> bool:
        return self.program() is not None and _pil() is not None

    def submit(self, job: dict) -> None:
        """Queue `job` - {"passId", "sat", "aos", "maxElDeg", "data" (the
        SigMF data file), "rate", "tle" (three lines)} - and start the
        thread if it is not running."""
        self.q.put(job)
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.stopping = False
                self.thread = threading.Thread(target=self._loop, name="wxsat-decode", daemon=True)
                self.thread.start()

    def idle(self) -> bool:
        return self.current is None and self.q.empty()

    def stop(self) -> None:
        self.stopping = True
        p = self.proc
        if p is not None and p.poll() is None:
            _kill_group(p)

    def _loop(self) -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (AttributeError, OSError):
            pass
        while not self.stopping:
            try:
                job = self.q.get(timeout=5.0)
            except queue.Empty:
                with self.lock:
                    if self.q.empty():
                        self.thread = None
                        return
                continue
            self.current = dict(job, started=time.time())
            try:
                plan, why, image_id = self.decode(job)
            except Exception as e:  # noqa: BLE001 - a bug here must fail the pass, not the thread
                log.warning("weather satellites: decoding %s failed", job.get("passId"), exc_info=True)
                plan, why, image_id = "failed", _("Decoding failed: {error}").format(error=e), None
            self.current = None
            try:
                self.done(job, plan, why, image_id)
            except Exception:  # noqa: BLE001
                log.warning("weather satellites: recording the decode of %s failed", job.get("passId"),
                            exc_info=True)

    def _budget(self) -> tuple[int, int | None]:
        """(the pictures' share of the disk, free space above the floor or None)."""
        d = None
        try:
            d = self.disk() if self.disk is not None else None
        except Exception:  # noqa: BLE001 - no figures: our own limit only
            d = None
        if not d:
            return IMAGES_DEFAULT_LIMIT, None
        return max(1, int(d["limitBytes"] * IMAGES_SHARE)), int(d["freeBytes"]) - int(d["floorBytes"])

    def decode(self, job: dict) -> tuple[str, str | None, str | None]:
        """Run SatDump on one pass and keep its pictures: (plan, why, imageId)."""
        prog = self.program()
        if prog is None or _pil() is None:
            return "failed", _("SatDump is not installed here, so the pass was recorded but not decoded"), None
        data = Path(job["data"])
        if not data.is_file():
            return "failed", _("The recording was deleted before it could be decoded"), None
        limit, room = self._budget()
        if room is not None and room < WORK_ROOM:
            return "failed", _("Not enough free disk space to decode the pass"), None
        pid = job["passId"]
        work = self.work / pid
        shutil.rmtree(work, ignore_errors=True)
        (work / "home").mkdir(parents=True)
        out = work / "out"
        tle = work / "tle.txt"
        tle.write_text("\n".join(job["tle"]) + "\n", encoding="utf-8")
        (work / "settings.json").write_text(json.dumps(SETTINGS, ensure_ascii=False, indent=1), encoding="utf-8")
        # nice(1) rather than setting the child's priority after it has
        # started: from its first instruction, whichever thread started it.
        nice = shutil.which("nice")
        timeout, stdbuf = shutil.which("timeout"), shutil.which("stdbuf")
        wrap = (([timeout, "-k", str(KILL_GRACE_S), f"{self.timeout_s:g}"] if timeout else [])
                + ([stdbuf, "-oL", "-eL"] if stdbuf else []) + ([nice, "-n", "19"] if nice else []))
        argv = wrap + [prog, PIPELINE, "baseband", str(data), str(out), "--samplerate", str(int(round(job["rate"]))),
                "--baseband_format", "cs16", "--tle_override", str(tle)]
        env = {k: v for k, v in os.environ.items() if k not in ("http_proxy", "https_proxy", "HTTP_PROXY",
                                                                "HTTPS_PROXY", "ALL_PROXY", "all_proxy")}
        env["HOME"] = str(work / "home")
        logf = work / "satdump.log"
        t0 = time.monotonic()
        timed_out = False
        try:
            with open(logf, "wb") as lf:
                # Its own session, so a kill reaches SatDump and not only
                # the timeout(1) or nice(1) in front of it.
                self.proc = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=lf,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    # timeout(1) ends it first; this is only the backstop.
                    rc = self.proc.wait(timeout=self.timeout_s + KILL_GRACE_S + 30)
                except subprocess.TimeoutExpired:
                    _kill_group(self.proc)
                    rc = self.proc.wait()
                    timed_out = True
        except OSError as e:
            return self._fail(work, _("SatDump could not be started: {error}").format(error=e))
        finally:
            self.proc = None
        if self.stopping:
            return self._fail(work, _("Radio stopped while the pass was being decoded"))
        # 124: timeout(1) sent TERM; 137 (128 + 9): it had to send KILL.
        timed_out = timed_out or (timeout is not None and rc in (124, 137))
        last = _last_line(logf)
        if timed_out:
            log.warning("weather satellites: SatDump on %s ran past %.0f s and was ended; its last line: %s",
                        pid, self.timeout_s, last or "-")
        found = harvest(out, bool(job.get("night")))
        log.info("weather satellites: SatDump on %s: exit %s in %.0f s, %d bytes of frames, %d lines, %s",
                 pid, rc, time.monotonic() - t0, found["cadu"], found["lines"],
                 ", ".join(k for k, _n, _p in found["products"]) or "no pictures")
        if not found["products"]:
            if timed_out:
                why = _("SatDump took longer than {m} minutes and was stopped").format(m=round(self.timeout_s / 60))
                return self._fail(work, f"{why}: {last}" if last else why)
            if rc < 0:
                return self._fail(work, _("SatDump was ended from outside Radio (signal {n}); its last line: {line}")
                                  .format(n=-rc, line=last or "-"))
            if rc != 0:
                return self._fail(work, _("SatDump failed: {line}").format(line=last or rc))
            if found["cadu"] == 0:
                return self._fail(work, _("No signal from the satellite could be locked to during the pass"))
            return self._fail(work, _("The signal was locked too briefly to make a picture"))
        if found["lines"] and found["lines"] < MIN_LINES:
            return self._fail(work, _("The signal was locked too briefly to make a picture ({n} lines)").format(
                n=found["lines"]))
        meta = self.images.save(pid, job, found)
        shutil.rmtree(work, ignore_errors=True)
        self.images.prune(limit, keep=pid)
        if not meta["products"]:
            shutil.rmtree(self.images.folder / pid, ignore_errors=True)
            return "failed", _("SatDump's pictures could not be read"), None
        return "done", None, pid

    @staticmethod
    def _fail(work: Path, why: str) -> tuple[str, str, None]:
        shutil.rmtree(work, ignore_errors=True)
        return "failed", why, None


def _kill_group(p: subprocess.Popen) -> None:
    """KILL SatDump's whole session: timeout(1), nice(1) and SatDump."""
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        p.kill()


def _last_line(path: Path) -> str:
    """SatDump's last error, or its last line, colours stripped."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", ln).strip() for ln in text.splitlines() if ln.strip()]
    errs = [ln for ln in lines if "(E)" in ln or "(C)" in ln]
    pick = (errs or lines or [""])[-1]
    return re.sub(r"^\[[^\]]*\]\s*", "", pick)[:200]
