"""Radio's weather-satellite pictures (ohsradio/wxsat_decode.py; SERVER-API
"Weather satellites"): SatDump run after LOS on each recorded pass, its
output turned into JPEGs, thumbnails and a projected picture with bounds
(WebP, transparent outside the swath), kept within the recordings' disk rules and served by api/wxsat.

SatDump is a fake here: a script that writes the tree SatDump 1.2.2 writes
for `meteor_m2-x_lrpt baseband` - file for file, named as its source names
them (plugins/meteor_support/.../module_meteor_msumr_lrpt.cpp,
src-core/products/image_products.cpp and processor/image_processor.cpp) -
and records how it was run. Its "nolock" tree is the one the real
SatDump 1.2.2 wrote on 29/10/2026 for a real 137.1 MHz recording with no
lock in it (an empty .cadu, dataset.json, telemetry.json holding "null",
MSU-MR/product.cbor and no picture), exit 0. The projected pictures are
GeoTIFFs as SatDump writes them (tiffio.cpp, geotiff_write.cpp):
uncompressed RGBA, 16 bits, ModelTiepoint and ModelPixelScale. The real
binary on a pass with a picture is not run here: no freely licensed LRPT
recording with a lock was found to keep as a fixture.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.server.shack import SHACK_SECRET_HEADER
from ohsradio import wxsat_decode
from ohsradio.wxsat_decode import Decoder, read_geotiff, webp_supported
from satdump_fake import NORTH, SX, SY, WEST, write_geotiff

TESTS = Path(__file__).resolve().parent

try:
    from PIL import Image
except ImportError:          # the decoder says it cannot work without it; so do these tests
    Image = None

TLE3 = ["METEOR-M2 3", "1 57166U 23091A   26301.59639450 -.00000006  00000+0  16049-4 0  9993",
        "2 57166  98.5923 353.7327 0004774 132.4850 227.6734 14.24055162173505"]
def make_fake(folder: Path, mode: str, **kw) -> Path:
    exe = folder / "satdump"
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(TESTS)!r})\n"
                   "import satdump_fake\nsatdump_fake.main()\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    (folder / "fake.json").write_text(json.dumps(dict(kw, mode=mode)))
    return exe


def set_mode(fake: Path, mode: str, **kw) -> None:
    (fake.parent / "fake.json").write_text(json.dumps(dict(kw, mode=mode)))


def runs(fake: Path) -> list[dict]:
    p = fake.parent / "runs.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def a_job(folder: Path, pid="meteor-m2-3-20261029T0919Z", aos="2026-10-29T09:19:21Z") -> dict:
    data = folder / f"{pid}.sigmf-data"
    data.write_bytes(b"\0\0" * 2048)
    return {"passId": pid, "sat": "Meteor-M N2-3", "aos": aos, "maxElDeg": 41.9, "data": str(data),
            "rate": 800_000.0, "tle": TLE3}


def wait(cond, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@unittest.skipIf(Image is None, "no Pillow")
class Decoding(unittest.TestCase):
    """The decoder on its own, given a job as wxsat.py gives one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.fake = make_fake(self.dir, "day")
        self.results = []
        self.dec = Decoder(self.dir / "wxsat", lambda *a: self.results.append(a), binary=str(self.fake))

    def decode(self, **kw):
        return self.dec.decode(a_job(self.dir, **kw))

    def assert_swath(self, im, w, h):
        """The fake's projection painted a block a quarter to three
        quarters down and an eighth in from each side, alpha 0 around it:
        opaque inside, clear outside, nothing in between."""
        self.assertEqual((im.mode, im.size), ("RGBA", (w, h)))
        a = np.asarray(im)
        self.assertEqual(int(a[h // 2, w // 2, 3]), 255)
        self.assertGreater(int(a[h // 2, w // 2, 0]), 200)
        for y, x in ((h // 8, w // 2), (h // 2, w // 16), (h - 1, w - 1), (0, 0)):
            self.assertEqual(int(a[y, x, 3]), 0, (y, x))
        self.assertEqual(set(np.unique(a[:, :, 3]).tolist()), {0, 255})

    def test_a_day_pass_becomes_jpegs_thumbnails_and_a_projection_with_bounds(self):
        plan, why, image_id = self.decode()
        self.assertEqual((plan, why, image_id), ("done", None, "meteor-m2-3-20261029T0919Z"))
        [img] = self.dec.images.listing()
        self.assertEqual(set(img), {"id", "passId", "sat", "aos", "maxElDeg", "products", "projected"})
        self.assertEqual((img["id"], img["passId"], img["sat"], img["aos"], img["maxElDeg"]),
                         (image_id, image_id, "Meteor-M N2-3", "2026-10-29T09:19:21Z", 41.9))
        # Named by kind: rgb and ir first, the other composites, then each channel; no "_map" picture.
        self.assertEqual([p["kind"] for p in img["products"]], ["rgb", "ir", "msa", "ch1", "ch2", "ch5"])
        rgb = img["products"][0]
        self.assertEqual(set(rgb), {"kind", "name", "url", "w", "h"})
        self.assertEqual((rgb["name"], rgb["url"]), ("AVHRR 221 False Color", f"api/wxsat/images/{image_id}/rgb.jpg"))
        self.assertEqual((rgb["w"], rgb["h"]), (1400, 600))                 # the corrected picture is the one kept
        self.assertEqual(img["products"][1]["name"], "10.8um Thermal IR (Uncalibrated)")
        for p in img["products"]:
            with Image.open(self.dec.images.folder / image_id / f"{p['kind']}.jpg") as full, \
                    Image.open(self.dec.images.folder / image_id / f"{p['kind']}.thumb.jpg") as thumb:
                self.assertEqual((full.format, full.size), ("JPEG", (p["w"], p["h"])))
                self.assertEqual(thumb.width, 400)
        # The 16-bit one-channel picture is scaled, not clipped to white.
        with Image.open(self.dec.images.folder / image_id / "ir.jpg") as im:
            ir = np.asarray(im.convert("L"), float)
        self.assertTrue(200 < ir.mean() < 256)
        # The projection: bounds from the GeoTIFF, the picture in square degrees.
        pj = img["projected"]
        self.assertEqual(set(pj), {"url", "w", "h", "bounds"})
        self.assertEqual(pj["url"], f"api/wxsat/images/{image_id}/rgb-projected.webp")
        b = pj["bounds"]
        self.assertEqual(b, {"n": NORTH, "s": round(NORTH - 256 * SY * 8, 5), "e": round(WEST + 256 * SX * 8, 5),
                             "w": WEST})
        self.assertEqual(max(pj["w"], pj["h"]), 2048)
        self.assertAlmostEqual(pj["w"] / pj["h"], (b["e"] - b["w"]) / (b["n"] - b["s"]), places=2)
        # The painted block lands where the GeoTIFF put it, and the rest is clear.
        with Image.open(self.dec.images.folder / image_id / "rgb-projected.webp") as im:
            self.assertEqual(im.format, "WEBP")
            self.assert_swath(im, pj["w"], pj["h"])
        with Image.open(self.dec.images.folder / image_id / "rgb-projected.thumb.webp") as im:
            self.assertEqual((im.format, im.mode, im.width), ("WEBP", "RGBA", 400))
        # SatDump's own folder is gone; only the pictures and meta.json are kept.
        self.assertFalse((self.dir / "wxsat" / "work" / image_id).exists())
        self.assertEqual({p.suffix for p in (self.dec.images.folder / image_id).iterdir()}, {".jpg", ".webp", ".json"})

    def test_satdump_runs_offline_on_the_passes_own_element_set_at_the_lowest_priority(self):
        os.environ["https_proxy"] = "http://proxy.invalid:3128"
        self.addCleanup(os.environ.pop, "https_proxy", None)
        self.decode()
        [run] = runs(self.fake)
        argv = run["argv"][1:]
        work = self.dir / "wxsat" / "work" / "meteor-m2-3-20261029T0919Z"
        self.assertEqual(argv[:4], ["meteor_m2-x_lrpt", "baseband", str(self.dir / "meteor-m2-3-20261029T0919Z.sigmf-data"),
                                    str(work / "out")])
        flags = dict(zip(argv[4::2], argv[5::2]))
        self.assertEqual((flags["--samplerate"], flags["--baseband_format"]), ("800000", "cs16"))
        # --tle_override is what keeps SatDump off the network (module docstring):
        # it must always be there, holding exactly the pass's own element set.
        self.assertEqual(flags["--tle_override"], str(work / "tle.txt"))
        self.assertEqual(run["tle"], "\n".join(TLE3) + "\n")
        st = run["settings"]["satdump_general"]
        self.assertEqual((st["tle_update_interval"]["value"], st["log_to_file"]["value"]), ("Never", False))
        self.assertEqual((run["cwd"], run["home"]), (str(work), str(work / "home")))
        self.assertEqual(run["proxy"], [])
        self.assertEqual(run["nice"], 19)
        proj = run["settings"]["viewer"]["instruments"]["msu_mr"]["rgb_composites"]
        for name in (wxsat_decode.RGB_NAME, wxsat_decode.IR_NAME):
            self.assertEqual((proj[name]["project"]["img_format"], proj[name]["project"]["config"]["auto"]),
                             (".tif", True))

    def test_a_night_pass_has_infrared_only_and_projects_it(self):
        set_mode(self.fake, "night")
        self.assertEqual(self.decode()[0], "done")
        [img] = self.dec.images.listing()
        self.assertEqual([p["kind"] for p in img["products"]],
                         ["ir", "3-9-um-shortwave-ir-uncalibrated", "ch4", "ch5"])
        self.assertTrue(img["projected"]["url"].endswith("/ir-projected.webp"))

    def test_without_webp_in_pillow_the_projection_is_png_with_alpha_never_jpeg(self):
        with mock.patch.object(wxsat_decode, "webp_supported", return_value=False), \
                mock.patch.object(wxsat_decode, "_overlay_said", False), \
                self.assertLogs("ohsradio.wxsat", "WARNING") as said:
            _plan, _why, image_id = self.decode()
        self.assertIn("written as PNG", "\n".join(said.output))
        [img] = self.dec.images.listing()
        pj = img["projected"]
        self.assertEqual(pj["url"], f"api/wxsat/images/{image_id}/rgb-projected.png")
        self.assertEqual(self.dec.images.composite("ir", "")[0]["url"], f"api/wxsat/images/{image_id}/ir-projected.png")
        with Image.open(io.BytesIO(self.dec.images.file(image_id, "rgb-projected", False, "png"))) as im:
            self.assertEqual(im.format, "PNG")
            self.assert_swath(im, pj["w"], pj["h"])
        self.assertIsNone(self.dec.images.file(image_id, "rgb-projected", False, "webp"))

    def test_a_projection_made_before_webp_is_still_the_jpeg_it_was(self):
        _plan, _why, image_id = self.decode()
        d = self.dec.images.folder / image_id
        meta = json.loads((d / "meta.json").read_text())
        for kind, p in meta["projected"].items():          # as meta.json was before "ext"
            del p["ext"]
            for thumb in ("", ".thumb"):
                with Image.open(d / f"{kind}-projected{thumb}.webp") as im:
                    im.convert("RGB").save(d / f"{kind}-projected{thumb}.jpg", "JPEG")
                (d / f"{kind}-projected{thumb}.webp").unlink()
        (d / "meta.json").write_text(json.dumps(meta))
        [img] = self.dec.images.listing()
        self.assertEqual(img["projected"]["url"], f"api/wxsat/images/{image_id}/rgb-projected.jpg")
        self.assertEqual(self.dec.images.composite("rgb", "")[0]["url"], img["projected"]["url"])
        self.assertEqual(self.dec.images.file(image_id, "rgb-projected", False, "jpg")[:2], b"\xff\xd8")

    def test_no_lock_is_failed_with_a_plain_reason(self):
        set_mode(self.fake, "nolock")
        plan, why, image_id = self.decode()
        self.assertEqual((plan, image_id), ("failed", None))
        self.assertEqual(why, "No signal from the satellite could be locked to during the pass")
        self.assertEqual(self.dec.images.listing(), [])
        self.assertFalse((self.dir / "wxsat" / "work").exists() and any((self.dir / "wxsat" / "work").iterdir()))

    def test_a_lock_too_short_for_a_picture_is_failed_too(self):
        set_mode(self.fake, "short")
        plan, why, _id = self.decode()
        self.assertEqual(plan, "failed")
        self.assertIn("too briefly", why)

    def test_satdump_failing_says_its_own_error(self):
        set_mode(self.fake, "crash")
        plan, why, _id = self.decode()
        self.assertEqual(plan, "failed")
        self.assertEqual(why, "SatDump failed: (E) Fatal error running pipeline : Could not open input file")

    def test_a_decode_that_runs_too_long_is_stopped(self):
        set_mode(self.fake, "slow", sleep=30)
        self.dec.timeout_s = 1.0
        t0 = time.monotonic()
        plan, why, _id = self.decode()
        self.assertLess(time.monotonic() - t0, 10.0)
        self.assertEqual(plan, "failed")
        self.assertIn("longer than", why)

    def test_the_pictures_keep_to_their_share_of_the_recordings_limit(self):
        self.decode(pid="meteor-m2-3-20261028T0919Z", aos="2026-10-28T09:19:21Z")
        one = self.dec.images.used()
        # Room for a pass and a half under a tenth of the recordings' limit:
        # the oldest goes when the third is made, never the new one.
        self.dec.disk = lambda: {"limitBytes": int(one * 15), "freeBytes": 50 << 30, "floorBytes": 2 << 30}
        self.decode(pid="meteor-m2-3-20261029T0919Z", aos="2026-10-29T09:19:21Z")
        self.assertEqual([i["id"] for i in self.dec.images.listing()],
                         ["meteor-m2-3-20261029T0919Z"])
        # Below the recordings' free-space floor nothing is decoded at all.
        self.dec.disk = lambda: {"limitBytes": 10 << 30, "freeBytes": (2 << 30) + 1000, "floorBytes": 2 << 30}
        plan, why, _id = self.decode(pid="meteor-m2-4-20261029T1301Z")
        self.assertEqual((plan, why), ("failed", "Not enough free disk space to decode the pass"))
        self.assertEqual(len(runs(self.fake)), 2)

    def test_one_pass_at_a_time_through_the_queue(self):
        for i, pid in enumerate(("meteor-m2-3-20261029T0919Z", "meteor-m2-4-20261029T1301Z")):
            self.dec.submit(a_job(self.dir, pid=pid, aos=f"2026-10-29T{9 + 4 * i:02d}:00:00Z"))
        self.assertTrue(wait(lambda: len(self.results) == 2))
        self.assertEqual([(r[0]["passId"], r[1]) for r in self.results],
                         [("meteor-m2-3-20261029T0919Z", "done"), ("meteor-m2-4-20261029T1301Z", "done")])
        self.assertTrue(self.dec.idle())

    def test_without_satdump_nothing_is_attempted(self):
        self.dec.binary = None
        os.environ["OHS_SATDUMP"] = str(self.dir / "nonesuch")
        self.addCleanup(os.environ.pop, "OHS_SATDUMP", None)
        self.assertFalse(self.dec.available())

    def test_a_file_outside_the_pictures_is_never_served(self):
        _plan, _why, image_id = self.decode()
        self.assertIsNotNone(self.dec.images.file(image_id, "rgb", False))
        self.assertGreater(len(self.dec.images.file(image_id, "rgb", False)),
                           len(self.dec.images.file(image_id, "rgb", True)))
        (self.dec.images.folder / "secret.jpg").write_bytes(b"x")
        for iid, product in ((image_id, "../secret"), ("..", "secret"), (image_id, "meta"), (image_id, "nonesuch"),
                             (image_id, "rgb.thumb")):
            self.assertIsNone(self.dec.images.file(iid, product, False), (iid, product))
        # Only a projection is anything but JPEG, and only as one of the three.
        self.assertIsNotNone(self.dec.images.file(image_id, "rgb-projected", False, "webp"))
        self.assertIsNone(self.dec.images.file(image_id, "rgb", False, "webp"))
        self.assertIsNone(self.dec.images.file(image_id, "rgb-projected", False, "json"))


class GeoTiff(unittest.TestCase):
    def test_bounds_come_from_the_tiepoint_and_pixel_scale(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.tif"
            a = np.zeros((10, 20, 4), np.uint16)
            a[..., 0] = 0xff00
            a[..., 3] = 0xffff
            write_geotiff(p, a, -10.0, 60.0, 0.5, 0.25)
            img, b = read_geotiff(p)
            self.assertEqual(img.shape, (10, 20, 4))
            self.assertEqual((int(img[0, 0, 0]), int(img[0, 0, 3])), (255, 255))
            self.assertEqual(b, {"n": 60.0, "s": 57.5, "e": 0.0, "w": -10.0})

    def geotiff(self, a, **kw):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "x.tif"
        write_geotiff(p, a, -10.0, 60.0, 0.5, 0.25, **kw)
        return read_geotiff(p)[0][:, :, 3]

    def test_the_alpha_sample_is_the_swath_whatever_the_colour(self):
        a = np.zeros((20, 20, 4), np.uint16)
        a[5:15, 5:15, 3] = 0xffff                  # black but inside: opaque
        a[0:5, :, :3] = 0x8000                     # grey but outside: clear
        a[15:, :, 3] = 0x7000                      # SatDump's blended edge: under half is out
        al = self.geotiff(a)
        self.assertEqual((int(al[10, 10]), int(al[2, 10]), int(al[17, 10])), (255, 0, 0))

    def test_without_alpha_the_nodata_value_is_outside(self):
        a = np.full((20, 20, 3), 7, np.uint16)
        a[5:15, 5:15] = (0, 0, 0)                  # black is a picture's here: nodata says what is not
        al = self.geotiff(a, nodata="7")
        self.assertEqual((int(al[10, 10]), int(al[2, 10]), int(al[5, 5])), (255, 0, 255))

    def test_with_neither_black_in_every_band_is_outside_shrunk_off_the_edge(self):
        a = np.zeros((30, 30, 3), np.uint16)
        a[10:20, 10:20] = (0x4000, 0x8000, 0)      # one band 0 is still a picture
        al = self.geotiff(a)
        self.assertEqual(int(al[15, 15]), 255)
        # Black within EDGE_PX of the swath stays opaque (the projection
        # darkens its edge); beyond that it is clear.
        self.assertEqual([int(v) for v in al[15, 5:12]], [0, 0, 0, 255, 255, 255, 255])
        self.assertEqual(int(al[0, 0]), 0)

    @unittest.skipIf(Image is None or not webp_supported(), "no WebP in this Pillow")
    def test_the_webp_keeps_its_alpha_exact(self):
        rgba = np.zeros((64, 96, 4), np.uint8)
        rgba[:, :, :3] = np.random.default_rng(3).integers(0, 255, (64, 96, 3))
        rgba[16:48, 20:70, 3] = 255
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.webp"
            wxsat_decode._save_overlay(rgba, p, 96, 64)
            with Image.open(p) as im:
                self.assertEqual(im.format, "WEBP")
                np.testing.assert_array_equal(np.asarray(im)[:, :, 3], rgba[:, :, 3])


# ---------------------------------------------------------------- on the server, from a recorded pass
from test_ham_wxsat import (AFTER, BEFORE, HOME, M23, TLE, Carrier, ThreeInputs, by_id,  # noqa: E402
                            fix, utc)


@unittest.skipIf(Image is None, "no Pillow")
class OnTheServer(unittest.TestCase):
    """A pass recorded on Radio's real server, then decoded by the fake."""

    def setUp(self):
        from ohscore.server.app import Server
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.radio import Radio
        from test_server import SECRET
        self.SECRET = SECRET
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
               "locator": "IO75RL", "soapyAntenna": "Antenna C"}
        self.audio = StreamAudio(realtime=False)
        self.dev = ThreeInputs(dict(cfg), 2_400_000.0, [Carrier()])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=self.dev)
        self.clock = fix(self.radio, self.dir, BEFORE)
        self.fake = make_fake(self.dir, "slow", sleep=1.0)
        self.radio.wxsat.decoder.binary = str(self.fake)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, level="view", raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request(method, path, None, {SHACK_SECRET_HEADER: self.SECRET, "X-OpenHamShack-User": "brian",
                                       "X-OpenHamShack-Level": level, "X-OpenHamShack-Device": "dev_TEST",
                                       "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        body = r.read()
        c.close()
        return (r.status, body, r.getheader("Content-Type")) if raw else (r.status, json.loads(body))

    def plan(self):
        return by_id(self.req("GET", "/api/wxsat/passes?hours=6")[1])[M23]

    def record_the_pass(self):
        self.clock.t = utc("2026-10-29T09:22:00Z")
        self.radio.wxsat.tick()
        job = self.radio.wxsat.job
        self.assertTrue(wait(lambda: job["rec"].accepted >= 200_000), "no samples reached the recording")
        self.clock.t = AFTER
        self.radio.wxsat.tick()

    def test_a_recorded_pass_is_decoded_and_served(self):
        self.assertEqual(self.req("GET", "/api/wxsat/images"), (200, []))
        self.record_the_pass()
        self.assertEqual((self.plan()["plan"], self.plan()["imageId"]), ("decoding", None))
        self.assertTrue(wait(lambda: self.radio.wxsat.decoder.current is not None))
        st = self.req("GET", "/api/wxsat/status")[1]
        self.assertEqual((st["state"], st["passId"], st["sat"], st["freqHz"]),
                         ("decoding", M23, "Meteor-M N2-3", 137_100_000))
        self.assertTrue(wait(lambda: self.plan()["plan"] != "decoding"))
        p = self.plan()
        self.assertEqual((p["plan"], p["why"], p["imageId"]), ("done", None, M23))
        # SatDump was given the recording as it is: its rate, its file.
        [run] = runs(self.fake)
        self.assertEqual(run["argv"][run["argv"].index("--samplerate") + 1], "800000")
        self.assertTrue(run["argv"][3].endswith(".sigmf-data"))
        self.assertEqual(run["tle"].splitlines()[1:], [ln for ln in TLE.splitlines() if ln.startswith(("1 57166",
                                                                                                    "2 57166"))])

        s, images = self.req("GET", "/api/wxsat/images")
        self.assertEqual(s, 200)
        [img] = images
        self.assertEqual((img["id"], img["passId"], img["maxElDeg"]), (M23, M23, 41.9))
        s, body, ctype = self.req("GET", f"/{img['products'][0]['url']}", raw=True)
        self.assertEqual((s, ctype, body[:2]), (200, "image/jpeg", b"\xff\xd8"))
        s, thumb, _c = self.req("GET", f"/{img['products'][0]['url']}?w=400", raw=True)
        with Image.open(io.BytesIO(thumb)) as im:
            self.assertEqual((s, im.width), (200, 400))
        # The projection, served as WebP and clear outside the swath (the
        # fake's painted block: a quarter to three quarters down, an eighth
        # in from each side).
        pj = img["projected"]
        self.assertTrue(pj["url"].endswith("/rgb-projected.webp"))
        s, body, ctype = self.req("GET", f"/{pj['url']}", raw=True)
        self.assertEqual((s, ctype), (200, "image/webp"))
        with Image.open(io.BytesIO(body)) as im:
            a = np.asarray(im)
            self.assertEqual((im.format, im.mode, im.size), ("WEBP", "RGBA", (pj["w"], pj["h"])))
        h, w = a.shape[:2]
        self.assertEqual((int(a[h // 2, w // 2, 3]), int(a[h // 8, w // 2, 3]), int(a[h // 2, w // 16, 3])),
                         (255, 0, 0))
        self.assertEqual(self.req("GET", f"/{pj['url'][:-5]}.jpg", raw=True)[0], 404)
        self.assertEqual(self.req("GET", f"/api/wxsat/images/{M23}/nonesuch.jpg", raw=True)[0], 404)
        self.assertEqual(self.req("GET", f"/api/wxsat/images/{M23}/..%2Fmeta.jpg", raw=True)[0], 404)

        s, comp = self.req("GET", "/api/wxsat/composite?product=rgb&hours=24")
        self.assertEqual(s, 200)
        self.assertEqual(comp, {"frames": [{"imageId": M23, "aos": "2026-10-29T09:19:21Z",
                                            "url": img["projected"]["url"], "bounds": img["projected"]["bounds"]}]})
        ir = self.req("GET", "/api/wxsat/composite?product=ir&hours=24")[1]["frames"][0]["url"]
        self.assertEqual(ir, f"api/wxsat/images/{M23}/ir-projected.webp")
        s, body, ctype = self.req("GET", f"/{ir}?w=400", raw=True)
        with Image.open(io.BytesIO(body)) as im:
            self.assertEqual((s, ctype, im.mode, im.width), (200, "image/webp", "RGBA", 400))
            self.assertEqual(int(np.asarray(im)[0, 0, 3]), 0)
        self.clock.t = utc("2026-10-29T11:00:00Z")                      # more than an hour after its AOS
        self.assertEqual(self.req("GET", "/api/wxsat/composite?product=rgb&hours=1")[1], {"frames": []})
        self.assertEqual(self.req("GET", "/api/wxsat/composite?product=msa")[0], 400)
        self.assertEqual(self.req("GET", "/api/wxsat/composite?hours=0")[0], 400)

    def test_a_pass_with_no_lock_ends_failed_and_says_why(self):
        set_mode(self.fake, "nolock")
        self.record_the_pass()
        self.assertTrue(wait(lambda: self.plan()["plan"] not in ("decoding", "done")))
        p = self.plan()
        self.assertEqual((p["plan"], p["imageId"]), ("failed", None))
        self.assertEqual(p["why"], "No signal from the satellite could be locked to during the pass")
        self.assertEqual(self.req("GET", "/api/wxsat/images"), (200, []))

    def test_a_pass_left_decoding_by_a_restart_is_decoded_again(self):
        set_mode(self.fake, "day")
        self.radio.wxsat.decoder.binary = str(self.dir / "nonesuch")    # this run cannot decode
        self.record_the_pass()
        m = self.radio.wxsat.marks[M23]
        self.assertEqual(m["plan"], "done")                             # nothing to decode with: as before
        m["plan"] = "decoding"                                          # as a stop mid-decode leaves it
        self.radio.wxsat.decoder.binary = str(self.fake)
        self.radio.wxsat.resume_decoding()
        self.assertTrue(wait(lambda: self.plan()["plan"] == "done"))
        self.assertEqual(self.plan()["imageId"], M23)
        # One whose recording has gone is failed, saying so.
        m["plan"] = "decoding"
        m["file"] = "gone.sigmf-data"
        self.radio.wxsat.resume_decoding()
        self.assertEqual((self.plan()["plan"], self.plan()["why"]),
                         ("failed", "The recording was deleted before it could be decoded"))


if __name__ == "__main__":
    unittest.main()
