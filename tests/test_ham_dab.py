"""DAB in Radio (23/10/2026): a decoder session that takes the receiver.

On the RSPdx-shaped simulator (listen_helpers) with shack_sdr's own DAB
transmitter model on 11D (ohsradio/devices/simdab.py), end to end:

- **A session plays a station:** the receiver goes to the block's centre
  (DC on it) and says who holds it (`rxOwner`); the feed lists the
  ensemble and its two services with the programme text; the station's
  sound - 1 kHz left, 1.5 kHz right - is the ordinary receive audio at
  48 kHz, stereo.
- **The service is chosen live,** and a DAB+ one without faad2 says why in
  words, with silence (not a stopped stream) in its place.
- **Stopping gives the receiver back:** the dial, mode and repeater offset
  from before, the centre following the dial again, the mode's own audio.
- **Refusals,** each with its sentence: tuning or keying while DAB holds
  the receiver, a second DAB session, a receiver too slow, transmitting,
  a block that is not one.
- **Over the API:** the session's routes, 409 on api/set, the sound on
  api/audio/rx at 48 kHz (stereo when asked), a recording of it, status.
- **Host libraries:** the sentences with and without SHACK_HOSTLIBS.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore import decoders, host, hostlibs, sdr
from ohscore.decoders import Refused
from ohscore.engine import ReceiverHeld, TxRefused
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, TapAudio, make_listener, peak_hz, tone_snr
from test_ham_audio48 import flac_rate_and_channels
from test_server import SECRET

BLOCK, CENTRE = "11D", 222_064_000.0
HOME = 145_500_000.0
MP2, PLUS = "C221", "C3A7"
DLS = "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right"
UPDATE = "Update the controller to use SDRplay radios and DAB+"


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


def stereo_since(audio: TapAudio, mark: int) -> np.ndarray:
    """The stereo blocks played since chunk `mark`, as (n, 2)."""
    parts = [c for c in audio.chunks[mark:] if c.ndim == 2]
    return np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OnTheSimulator(unittest.TestCase):
    def radio(self, fs=2_400_000.0, receive_only=True, **over):
        cfg = {"vfo": HOME, "mode": "fm", **over}
        r, audio, dev = make_listener([ensemble()], receive_only=receive_only, fs=fs, **cfg)
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r, audio

    def play(self, r, **params):
        sess = r.decoders.start("dab", CENTRE, {"service": MP2, **params})
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("dls") == DLS),
                        r.decoders.session(sess["id"]))
        return sess

    def test_a_station_plays_end_to_end(self):
        r, audio = self.radio()
        sess = r.decoders.start("dab", CENTRE, {"service": MP2})
        self.assertEqual((sess["decoder"], sess["freqHz"], sess["block"], sess["holdsReceiver"], sess["panel"]),
                         ("dab", CENTRE, BLOCK, True, "meta"))
        self.assertEqual(sess["params"], {"service": MP2, "block": BLOCK})
        st = r.state()
        self.assertEqual(st["vfo"], CENTRE)
        own = st["rxOwner"]
        self.assertEqual((own["by"], own["session"], own["block"], own["freqHz"]), ("dab", sess["id"], BLOCK, CENTRE))
        self.assertEqual(own["prior"], {"vfo": HOME, "mode": "fm", "rptOffsetHz": 600_000.0})
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("dls") == DLS))
        self.assertEqual(r.centre, CENTRE)                   # DC on the block's unused middle carrier
        meta = r.decoders.session(sess["id"])["meta"]
        self.assertTrue(meta["sync"] and meta["complete"])
        self.assertEqual(meta["ensemble"]["label"], "Shack Test Mux")
        self.assertEqual([(s["sid"], s["label"], s["kind"]) for s in meta["services"]],
                         [(MP2, "Shack MP2 Tone", "dab"), (PLUS, "Shack DAB+ Data", "dab+")])
        self.assertEqual((meta["playing"], meta["why"], meta["whyText"], meta["audio"]),
                         (MP2, None, "", {"codec": "mp2"}))
        # Its sound is the receive audio, at 48 kHz in stereo.
        mark = len(audio.chunks)
        self.assertTrue(wait(r, lambda: len(stereo_since(audio, mark)) >= 2 * 48_000))
        lr = stereo_since(audio, mark)[-2 * 48_000:]
        self.assertAlmostEqual(peak_hz(lr[:, 0]), 1000.0, delta=2.0)
        self.assertAlmostEqual(peak_hz(lr[:, 1]), 1500.0, delta=2.0)
        self.assertGreater(tone_snr(lr[:, 0], 1000.0)[1], 10.0)
        self.assertGreater(tone_snr(lr[:, 1], 1500.0)[1], 10.0)
        self.assertEqual(r.audio_channels(), 2)

    def test_the_block_by_name_alone(self):
        r, _audio = self.radio()
        sess = r.decoders.start("dab", None, {"block": "11d", "service": ""})
        self.assertEqual((sess["freqHz"], sess["block"]), (CENTRE, BLOCK))
        # No service: the ensemble is listed, nothing plays.
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("complete")))
        self.assertIsNone(r.decoders.session(sess["id"])["meta"]["playing"])

    def test_the_service_is_chosen_live(self):
        r, audio = self.radio()
        sess = self.play(r)
        faad2 = next(c for c in r.decoders.codecs() if c["id"] == "faad2")
        if faad2["state"] == "found":
            self.skipTest("faad2 is installed here: the DAB+ station would play rather than say why")
        got = r.decoders.configure(sess["id"], {"service": PLUS})
        self.assertEqual(got["params"]["service"], PLUS)
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("playing") == PLUS))
        self.assertTrue(wait(r, lambda: r.decoders.session(sess["id"])["meta"]["why"] == "needs_codec:faad2"))
        meta = r.decoders.session(sess["id"])["meta"]
        said = "Needs faad2: install it to hear DAB+ stations. Radio never includes it: see Help › Codecs."
        self.assertEqual(meta["whyText"], said)
        self.assertEqual([s["whyText"] for s in meta["services"]], ["", said])
        self.assertIsNone(meta["dls"])                  # cleared when the service changed
        # Silent for want of faad2, but the stream goes on: silence.
        mark = len(audio.chunks)
        self.assertTrue(wait(r, lambda: sum(len(c) for c in audio.chunks[mark:]) >= 48_000))
        self.assertFalse(np.concatenate([np.ravel(c) for c in audio.chunks[mark + 4:]]).any())
        # And back.
        r.decoders.configure(sess["id"], {"service": MP2})
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("dls") == DLS))
        mark = len(audio.chunks)
        self.assertTrue(wait(r, lambda: len(stereo_since(audio, mark)) >= 48_000))
        self.assertAlmostEqual(peak_hz(stereo_since(audio, mark)[-48_000:, 0]), 1000.0, delta=3.0)

    def test_a_bad_service_or_another_block_is_refused_live(self):
        r, _audio = self.radio()
        sess = r.decoders.start("dab", CENTRE, {"service": MP2})
        with self.assertRaises(Refused) as cm:
            r.decoders.configure(sess["id"], {"block": "12B"})
        self.assertEqual(cm.exception.code, "bad_params")
        self.assertIn("stop it and start one on 12B", str(cm.exception))
        with self.assertRaises(Refused) as cm:
            r.decoders.configure(sess["id"], {"service": "not hex"})
        self.assertEqual(cm.exception.code, "bad_params")
        with self.assertRaises(Refused) as cm:
            r.decoders.configure("ds_none", {"service": MP2})
        self.assertEqual(cm.exception.code, "unknown_session")

    def test_stopping_gives_the_receiver_back(self):
        r, audio = self.radio(rptOffsetHz=1_600_000.0)
        sess = self.play(r)
        self.assertTrue(r.decoders.stop(sess["id"]))
        st = r.state()
        self.assertEqual((st["vfo"], st["mode"], st["rptOffsetHz"], st["rxOwner"]), (HOME, "fm", 1_600_000.0, {}))
        self.assertNotIn("DAB", st["txBlocked"])
        self.assertTrue(wait(r, lambda: r.centre != CENTRE and r._rx_settled()))
        self.assertLess(abs(r.centre - HOME), r.geo.fs / 2)
        self.assertEqual(r.audio_channels(), 1)
        mark = len(audio.chunks)
        self.assertTrue(wait(r, lambda: len(audio.chunks) > mark + 4))
        self.assertTrue(all(c.ndim == 1 for c in audio.chunks[mark:]))    # the FM demodulator's again
        r.set(vfo=145_000_000.0)                                          # and the operator may tune
        self.assertEqual(r.state()["vfo"], 145_000_000.0)

    def test_stopping_the_radio_gives_the_dial_back_and_starts_no_dab_again(self):
        r, _audio = self.radio()
        self.play(r)
        r.stop()
        self.assertEqual((r.state()["vfo"], r.state()["mode"], r.state()["rxOwner"]), (HOME, "fm", {}))
        self.assertEqual(r.state()["decoderSessions"], [])     # never saved: no surprise retune at the next start
        r.start()
        self.assertEqual((r.state()["vfo"], r.decoders.sessions()), (HOME, []))

    def test_while_held_tuning_and_keying_are_refused_with_a_sentence(self):
        r, _audio = self.radio(receive_only=False)
        r.decoders.start("dab", CENTRE, {"service": MP2})
        tune = "The receiver is playing DAB from block 11D: stop the DAB station to tune or change mode"
        for change in ({"vfo": 145_000_000.0}, {"mode": "usb"}, {"rit": 100.0, "ritOn": True}):
            with self.assertRaises(ReceiverHeld) as cm:
                r.set(**change)
            self.assertEqual(str(cm.exception), tune)
        r.set(volume=0.5)                                     # what does not tune still changes
        key = "The receiver is playing DAB from block 11D: stop the DAB station to transmit"
        self.assertEqual(r.state()["txBlocked"], key)
        with self.assertRaises(TxRefused) as cm:
            r.ptt(True)
        self.assertEqual(str(cm.exception), key)
        self.assertFalse(r.state()["keyed"])

    def test_one_session_holds_the_receiver(self):
        r, _audio = self.radio()
        r.decoders.start("dab", CENTRE, {"service": MP2})
        with self.assertRaises(Refused) as cm:
            r.decoders.start("dab", 225_648_000.0, {})
        self.assertEqual(cm.exception.code, "receiver_busy")
        self.assertEqual(str(cm.exception), "A DAB station on block 11D already has the receiver: stop it first")
        self.assertEqual(r.state()["vfo"], CENTRE)

    def test_a_receiver_too_slow_is_refused_and_told_how(self):
        r, _audio = self.radio(fs=1_200_000.0)
        with self.assertRaises(Refused) as cm:
            r.decoders.start("dab", CENTRE, {"service": MP2})
        self.assertEqual(cm.exception.code, "rate_too_low")
        self.assertEqual(str(cm.exception), "DAB needs the receiver to run at 2.048 MS/s or more, and the sdrplay "
                                            "runs at 1.2 MS/s: choose 2.4 MS/s in Settings › Radio (the radio "
                                            "restarts)")
        self.assertEqual((r.state()["vfo"], r.state()["rxOwner"], r.decoders.sessions()), (HOME, {}, []))

    def test_a_radio_with_no_fast_rate_says_it_cannot(self):
        r, _audio = self.radio(fs=1_200_000.0)
        with mock.patch.object(r, "_faster_rate", lambda least: None):
            with self.assertRaises(Refused) as cm:
                r.decoders.start("dab", CENTRE, {})
        self.assertIn("and the sdrplay cannot (it runs at 1.2 MS/s)", str(cm.exception))

    def test_not_while_transmitting(self):
        # An over in progress is a transmit thread still running (keyed
        # drops first, the key-down follows). Stood in for rather than keyed,
        # even into the simulator: a real over ends by itself on dead air or
        # the watchdog when a loaded host is slow, and the test with it.
        r, _audio = self.radio(receive_only=False, mode="usb", vfo=144_300_000.0)
        with mock.patch.object(r, "tx_thread", types.SimpleNamespace(is_alive=lambda: True)):
            with self.assertRaises(Refused) as cm:
                r.decoders.start("dab", CENTRE, {})
        self.assertEqual((cm.exception.code, str(cm.exception)),
                         ("on_air", "Not while transmitting: DAB takes the receiver to Band III"))
        self.assertEqual((r.state()["rxOwner"], r.state()["vfo"]), ({}, 144_300_000.0))

    def test_what_is_not_a_block_is_refused(self):
        r, _audio = self.radio()
        # Frequencies as the catalog's formatter writes them: a no-break
        # space before the unit.
        cases = [(CENTRE + 100_000.0, {}, "222.1640\u00a0MHz is not the centre of a DAB block (5A-13F)"),
                 (CENTRE, {"block": "12B"}, "Block 12B is centred on 225.6480\u00a0MHz, not 222.0640\u00a0MHz"),
                 (None, {"block": "14Z"}, "There is no DAB block called 14Z"),
                 (None, {}, "Give the block's centre frequency (freqHz) or its name (params.block)")]
        for freq, params, said in cases:
            with self.assertRaises(Refused) as cm:
                r.decoders.start("dab", freq, dict(params))
            self.assertEqual((cm.exception.code, str(cm.exception)), ("bad_params", said), (freq, params))
        self.assertEqual(r.state()["rxOwner"], {})

    def test_the_catalogue_says_dab_is_partial_without_faad2(self):
        r, _audio = self.radio()
        (dab,) = [e for e in r.decoders.catalogue() if e["id"] == "dab"]
        self.assertTrue(dab["available"])
        if "faad2" not in dab["missing"]:
            self.skipTest("faad2 is installed here")
        self.assertTrue(dab["partial"])
        self.assertEqual(dab["missingText"], "Needs faad2: install it to hear DAB+ stations. Radio never "
                                             "includes it: see Help › Codecs.")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheBandSimulator(unittest.TestCase):
    def test_the_default_simulator_has_an_ensemble_on_11d(self):
        from ham_helpers import close, make_radio
        r = make_radio(sampleRate=2_400_000, vfo=HOME, mode="fm")
        self.addCleanup(close, r)
        r.start()
        sess = r.decoders.start("dab", None, {"block": BLOCK, "service": MP2})
        self.assertTrue(wait(r, lambda: (r.decoders.session(sess["id"])["meta"] or {}).get("complete")))
        self.assertEqual(r.decoders.session(sess["id"])["meta"]["ensemble"]["label"], "Shack Test Mux")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [ensemble()]))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
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

    def listen(self, query="", nbytes=4 * 48_000 * 2):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("GET", "/api/audio/rx" + query, headers={shack.SHACK_SECRET_HEADER: SECRET,
                                                           "X-OpenHamShack-User": "b", "X-OpenHamShack-Level": "view"})
        r = c.getresponse()
        ct, fmt = r.getheader("Content-Type"), json.loads(r.getheader("X-Audio-Format"))
        data = r.read(nbytes)
        c.close()
        return ct, np.frombuffer(data, "<i2").reshape(-1, fmt["channels"]).astype(np.float32) / 32768.0

    def start(self):
        s, a = self.req("POST", "/api/decoders/sessions",
                        {"decoder": "dab", "freqHz": CENTRE, "params": {"block": BLOCK, "service": MP2}})
        self.assertEqual(s, 201, a)
        sid = a["id"]
        self.assertTrue(wait(self.radio, lambda: (self.req("GET", f"/api/decoders/sessions/{sid}",
                                                           level="view")[1].get("meta") or {}).get("dls") == DLS))
        return sid

    def test_a_session_over_the_api(self):
        sid = self.start()
        s, a = self.req("GET", "/api/status", level="view")
        self.assertEqual((a["rxOwner"]["session"], a["rxOwner"]["block"], a["vfo"]), (sid, BLOCK, CENTRE))
        self.assertTrue(a["audio"]["stereo"])
        # Tuning is the session's while it plays.
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": HOME}})
        self.assertEqual((s, a["code"], a["rxOwner"]["session"]), (409, "receiver_busy", sid))
        self.assertIn("stop the DAB station to tune", a["error"])
        # The service, live.
        s, a = self.req("POST", f"/api/decoders/sessions/{sid}", {"params": {"service": PLUS}})
        self.assertEqual((s, a["params"]["service"]), (200, PLUS), a)
        s, a = self.req("POST", f"/api/decoders/sessions/{sid}", {"params": "C221"})
        self.assertEqual((s, a["code"]), (400, "bad_params"))
        s, a = self.req("POST", "/api/decoders/sessions/ds_none", {"params": {"service": MP2}})
        self.assertEqual((s, a["code"]), (404, "unknown_session"))
        # A second one, and one at a rate or block that is wrong.
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "params": {"block": "12B"}})
        self.assertEqual((s, a["code"]), (409, "receiver_busy"))
        # Stopped: the receiver is the operator's again.
        s, a = self.req("DELETE", f"/api/decoders/sessions/{sid}")
        self.assertEqual(s, 200, a)
        s, a = self.req("GET", "/api/status", level="view")
        self.assertEqual((a["rxOwner"], a["vfo"], a["mode"]), ({}, HOME, "fm"))
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "freqHz": CENTRE + 100_000.0})
        self.assertEqual((s, a["code"]), (400, "bad_params"))
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab"})
        self.assertEqual((s, a["code"]), (400, "bad_params"))

    def test_the_sound_reaches_api_audio_rx_at_48_khz(self):
        self.start()
        ct, lr = self.listen("?channels=2")
        self.assertEqual(ct, "audio/L16; rate=48000; channels=2")
        lr = lr[-48_000:]
        self.assertAlmostEqual(peak_hz(lr[:, 0]), 1000.0, delta=3.0)
        self.assertAlmostEqual(peak_hz(lr[:, 1]), 1500.0, delta=3.0)
        ct, mono = self.listen()
        self.assertEqual(ct, "audio/L16; rate=48000; channels=1")
        # Mono is L+R: both tones, as a mono receiver hears a stereo station.
        f = np.fft.rfftfreq(48_000, 1 / 48_000)
        spec = np.abs(np.fft.rfft(mono[-48_000:, 0] * np.hanning(48_000)))
        for hz in (1000.0, 1500.0):
            near = np.abs(f - hz) < 5
            self.assertGreater(spec[near].max(), 30 * np.median(spec))

    def test_a_recording_is_the_station_in_stereo(self):
        self.start()
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio"})
        self.assertEqual(s, 200, a)
        self.assertTrue(wait(self.radio, lambda: any(
            x["kind"] == "audio" and x["seconds"] >= 1.0
            for x in self.req("GET", "/api/recordings/status", level="view")[1]["active"])))
        s, a = self.req("POST", "/api/recordings/stop", {"kind": "audio"})
        (e,) = [x for x in self.req("GET", "/api/recordings", level="view")[1]["recordings"]
                if x["id"] == a["stopped"][0]["id"]]
        self.assertEqual((e["sampleRate"], e["channels"], e["freqHz"]), (48_000, 2, CENTRE))
        self.assertEqual(flac_rate_and_channels(Path(self.radio.recordings_dir(), e["parts"]["data"]["name"])),
                         (48_000, 2))

    def test_not_while_automatic_transmit_is_armed(self):
        # Armed by a client with no heartbeats: the arm's own watchdog
        # (tick) is held off for the length of the request.
        with mock.patch.object(self.srv.digi, "tick", lambda: None):
            self.srv.digi.remote = "tv-1"
            try:
                s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "freqHz": CENTRE})
            finally:
                self.srv.digi.remote = None
        self.assertEqual((s, a["code"]), (409, "on_air"))
        self.assertEqual(self.radio.state()["rxOwner"], {})

    def test_the_catalogue_and_status_page(self):
        s, a = self.req("GET", "/api/decoders", level="view")
        (dab,) = [e for e in a["decoders"] if e["id"] == "dab"]
        self.assertEqual((dab["panel"], dab["available"], dab["inputs"]), ("meta", True, ["iq"]))
        s, a = self.req("GET", "/api/status", level="view")
        self.assertEqual(a["hostLibs"], {})        # not the store form: nothing to say


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class NotInQo100Nb(unittest.TestCase):
    def test_nb_lists_dab_as_not_for_its_receiver_and_refuses_it(self):
        import helpers
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio as NbRadio
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = NbRadio(helpers.sim_cfg(), persist=False, data_dir=tmp.name, audio=NullAudio(realtime=False))
        said = "This app's receiver stays on its own frequencies and cannot play DAB"
        (dab,) = [e for e in r.decoders.catalogue() if e["id"] == "dab"]
        self.assertEqual((dab["available"], dab["why"], dab["whyText"]), (False, "receiver_fixed", said))
        self.addCleanup(r.stop)
        r.start()
        with self.assertRaises(Refused) as cm:
            r.decoders.start("dab", CENTRE, {})
        self.assertEqual((cm.exception.code, str(cm.exception)), ("decoder_unavailable", said))


class HostLibraries(unittest.TestCase):
    """ohscore/hostlibs.py: a controller with host libraries, and one too
    old to have them (SHACK_HOSTLIBS unset in the store form)."""

    def env(self, store, libs):
        env = {k: v for k, v in os.environ.items() if k != "SHACK_HOSTLIBS"}
        if libs is not None:
            env["SHACK_HOSTLIBS"] = libs
        return mock.patch.object(host, "STORE", store), mock.patch.dict(os.environ, env, clear=True)

    def test_the_desktop_has_nothing_to_say(self):
        a, b = self.env(False, None)
        with a, b:
            self.assertEqual(hostlibs.status(), {})
            self.assertFalse(hostlibs.controller_too_old())
            self.assertIn("install it to hear DAB+", decoders.faad2_sentence())

    def test_a_controller_without_shack_hostlibs_says_update_it(self):
        a, b = self.env(True, None)
        with a, b:
            self.assertEqual(hostlibs.status(), {"supported": False, "root": None, "libraries": {}, "why": UPDATE})
            self.assertEqual(decoders.faad2_sentence(), UPDATE)
            self.assertEqual(decoders.codec_sentence({"id": "faad2", "state": "missing", "host": False,
                                                      "shippable": False}), UPDATE)
            # codec2 is ours to ship, so its sentence does not change.
            self.assertNotEqual(decoders.codec_sentence({"id": "codec2", "state": "missing", "host": False,
                                                         "shippable": True}), UPDATE)

    def test_a_controller_with_host_libraries_lists_them(self):
        with tempfile.TemporaryDirectory() as libs:
            Path(libs, "faad2").mkdir()
            Path(libs, "faad2", "libfaad.so.2").write_bytes(b"")
            Path(libs, "sdrplay-api").mkdir()          # mounted, nothing installed yet
            a, b = self.env(True, libs)
            with a, b:
                self.assertEqual(hostlibs.status(), {"supported": True, "root": libs, "why": "",
                                                     "libraries": {"faad2": True, "sdrplay-api": False}})
                self.assertIn("ask your controller's administrator", decoders.faad2_sentence())

    def test_the_store_server_says_update_in_status_and_on_its_page(self):
        a, b = self.env(True, None)
        with a, b:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSignals": False,
                   "callsign": "GM4BRI", "licenceClass": "full"}
            audio = StreamAudio(realtime=False)
            radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
            srv = Server(radio, ham_server.info("9.9.9"), audio, secret=SECRET)
            httpd = srv.serve("127.0.0.1", 0)
            self.addCleanup(srv.shutdown)
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
            hdr = {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "b", "X-OpenHamShack-Level": "view"}
            c.request("GET", "/api/status", headers=hdr)
            st = json.loads(c.getresponse().read())
            self.assertEqual((st["hostLibs"]["supported"], st["hostLibs"]["why"]), (False, UPDATE))
            c.request("GET", "/", headers=hdr)
            page = c.getresponse().read().decode()
            c.close()
            self.assertIn(f"<p class=warn>{UPDATE}</p>", page)


if __name__ == "__main__":
    unittest.main()
