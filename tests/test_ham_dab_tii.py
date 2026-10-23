"""DAB transmitters heard, in Radio (23/10/2026; docs/SERVER-API.md "DAB
(Radio)", "Transmitters heard"): shack_sdr's TII codes (the DAB feed's
`tii`) named as sites from the bundled Ofcom list, with distance and
bearing from the station's locator, in the session's `meta` as
`transmitters` - on the simulator end to end, over the API, and on the
desktop's session card.

The simulator's ensemble is sent by two transmitters (simdab.SITES):
Sound Digital's Crystal Palace and, 8 dB down, Wrotham; the model's EId,
C1CE, is Sound Digital's.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest

from ohscore import sdr
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from listen_helpers import ListeningSim
from test_server import SECRET

BLOCK, CENTRE = "11D", 222_064_000.0
HOME = 145_500_000.0
LONDON = "IO91WK"           # 51.44 N 0.12 W: Crystal Palace 4 km, Wrotham 30 km east


def ensemble():
    from ohsradio.devices.simdab import DabEnsemble
    return DabEnsemble(BLOCK, level_db=-30.0)


def wait(radio, cond, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        radio.heartbeat()
        if cond():
            return True
        time.sleep(0.02)
    return False


def radio_at(test, locator: str) -> tuple[Radio, StreamAudio]:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
           "locator": locator}
    audio = StreamAudio(realtime=False)
    return Radio(cfg, persist=False, data_dir=tmp.name, audio=audio,
                 device=ListeningSim(dict(cfg), 2_400_000.0, [ensemble()])), audio


class TheFeed(unittest.TestCase):
    """Radio.decoder_meta, which Decoders applies to every feed."""

    def test_codes_become_sites_from_the_station(self):
        r, _ = radio_at(self, LONDON)
        meta = {"ensemble": {"id": "C1CE"}, "block": "11D",
                "tii": [{"main": 11, "sub": 1, "levelDb": -0.5, "confidence": 1.0},
                        {"main": 1, "sub": 7, "levelDb": -8.5, "confidence": 0.9}]}
        out = r.decoder_meta(meta)
        self.assertEqual(out["tii"], meta["tii"])
        cp, wr = out["transmitters"]
        self.assertEqual((cp["site"], cp["ensemble"], cp["erpKw"], cp["match"]),
                         ("Crystal Palace", "SDL National", 5.73, "eid"))
        self.assertLess(cp["distanceKm"], 10)
        self.assertEqual((wr["site"], wr["levelDb"], wr["confidence"]), ("Wrotham", -8.5, 0.9))
        self.assertTrue(25 < wr["distanceKm"] < 40 and 80 < wr["bearingDeg"] < 130, wr)

    def test_a_feed_without_tii_is_left_as_it_is(self):
        r, _ = radio_at(self, LONDON)
        meta = {"sync": True, "services": []}
        self.assertIs(r.decoder_meta(meta), meta)

    def test_a_failing_addition_never_costs_the_feed(self):
        r, _ = radio_at(self, LONDON)

        def broken(_m):
            raise RuntimeError("lookup broke")
        r.decoder_meta = broken
        out = r.decoders._meta({"why": "no_signal", "tii": []})
        self.assertEqual((out["why"], out["whyText"]), ("no_signal", "No DAB signal on this block."))
        self.assertNotIn("transmitters", out)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    def setUp(self):
        self.radio, audio = radio_at(self, LONDON)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_the_session_names_the_transmitters_it_hears(self):
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "freqHz": CENTRE, "params": {"service": ""}})
        self.assertEqual(s, 201, a)
        sid = a["id"]

        def heard():
            return (self.req("GET", f"/api/decoders/sessions/{sid}", level="view")[1].get("meta") or {}).get(
                "transmitters") or []
        self.assertTrue(wait(self.radio, lambda: len(heard()) == 2, timeout=90), heard())
        cp, wr = heard()
        self.assertEqual((cp["site"], wr["site"]), ("Crystal Palace", "Wrotham"))
        self.assertEqual((cp["main"], cp["sub"], wr["main"], wr["sub"]), (11, 1, 1, 7))
        self.assertGreater(cp["levelDb"], wr["levelDb"] + 4)
        self.assertLess(cp["distanceKm"], 10)
        self.assertTrue(80 < wr["bearingDeg"] < 130, wr)
        self.assertEqual((cp["erpKw"], wr["erpKw"]), (5.73, 25.0))
        # The decoder's own codes stay in the feed beside them.
        meta = self.req("GET", f"/api/decoders/sessions/{sid}", level="view")[1]["meta"]
        self.assertEqual([(t["main"], t["sub"]) for t in meta["tii"]], [(11, 1), (1, 7)])


class TheCard(unittest.TestCase):
    """The desktop's DAB session card says what it hears."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def test_the_lines(self):
        from ohscore.ui.decodersview import transmitters_text
        meta = {"transmitters": [
            {"main": 11, "sub": 1, "site": "Crystal Palace", "distanceKm": 4.2, "bearingDeg": 7, "levelDb": -0.5},
            {"main": 1, "sub": 7, "site": "Wrotham", "distanceKm": None, "bearingDeg": None, "levelDb": -8.5},
            {"main": 5, "sub": 5, "site": None, "distanceKm": None, "bearingDeg": None, "levelDb": -20.0}]}
        self.assertEqual(transmitters_text(meta).splitlines(),
                         ["Transmitters heard:", "Crystal Palace, 4 km at 007°, 0 dB", "Wrotham, -8 dB",
                          "TII 5/5 (not in the list), -20 dB"])
        self.assertEqual(transmitters_text({"transmitters": []}), "")
        self.assertEqual(transmitters_text({}), "")


if __name__ == "__main__":
    unittest.main()
