"""Automatic transmit in the store form (ohscore/server/autotx.py,
docs/SERVER-API.md "Automatic transmit"): OpenHamShack Remote arms it, as
WSJT-X's Enable TX, chooses CQ, a reply or a line of text, and the server
keys a real QO-100 NB engine on the simulator for each over and unkeys at
its end - through the same key-up path as PTT, so the band plan, the
broker's on-air answer and the remote's lease all still decide. Into the
simulator only; the broker is test_server's fake.

The slot clock is the test's: the server is given a wall clock it can
move (UTC in 2017, so it is never mistaken for the real one), and decides
each over by it with the real slot rules. The engine's own wait for the
slot, which reads the real clock, answers "now", so an over starts as
soon as the sequencer hands it over rather than on a real 15 s boundary.
Decodes arrive through the engine's own event path (_emit_event), as the
FT8 decoder's do."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time
import unittest
from unittest import mock

import helpers
from ohscore import engine
from ohscore.modes import ft8
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohscore.server.autotx import IDLE_S
from ohsnb import server as nb_server

from test_server import SECRET, FakeBroker, ServerTest

FT8_DIAL = 10_489_540_000.0         # the narrow digimodes segment, where QO-100's FT8 is
SSB_DIAL = 10_489_700_000.0         # SSB only: the band plan refuses FT8 here
T0 = 1_500_000_000.0                # the test's UTC: a slot boundary for FT8 (even), FT4 and Q65
REAL_SLOT_START = engine.slot_start


def slot_start(now, mode, period=None):
    """The real rules on the test's clock; "now" on the real one."""
    return REAL_SLOT_START(now, mode, period) if now < T0 + 1e8 else now


@unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "no FT8 encoder here (ohsdigi: tools/build-ohsdigi.sh)")
class AutoTxTest(ServerTest):
    broker = True
    realtime = False        # True: overs take their real length (a halt can land mid-over)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("ohscore.engine.slot_start", slot_start)
        p.start()
        self.addCleanup(p.stop)
        self.audio = StreamAudio(realtime=False)
        cfg = helpers.sim_cfg(callsign="GM4BRI", locator="IO75RL", licenceClass="full", simRealtime=self.realtime)
        from ohsnb.radio import Radio
        self.radio = Radio(cfg, persist=False, data_dir=self.tmp.name, audio=self.audio)
        self.fake = FakeBroker() if self.broker else None
        bc = shack.BrokerClient(self.fake) if self.fake else None
        self.now = [1000.0]
        self.utc = [T0 + 15.2]           # just into an odd slot: young enough to start in
        info = nb_server.info("9.9.9")
        if self.broker:
            info.device_for = lambda dev: "pluto-1"
        self.srv = Server(self.radio, info, self.audio, secret=SECRET, broker=bc,
                          clock=lambda: self.now[0], wall=lambda: self.utc[0])
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")
        # What each over carried, from the real encoder.
        self.sent = []
        real = self.radio._render

        def render(mode, msg):
            self.sent.append((mode, dict(msg)))
            return real(mode, msg)
        self.radio._render = render

    def ft8(self, dial=FT8_DIAL):
        s, a = self.req("POST", "/api/set", {"mode": "ft8", "vfo": dial}, level="control")
        self.assertEqual(s, 200, a)

    def auto(self, body=None, level="transmit", remote="tv-1"):
        return self.req("POST", "/api/autotx", {"on": True, "remote": remote, **(body or {})}, level=level)

    def beat(self, remote="tv-1"):
        return self.req("POST", "/api/ptt/heartbeat", {"remote": remote})

    def status(self):
        return self.req("GET", "/api/status")[1]

    def over_ended(self, n):
        """The n-th over has gone out and the server has finished with it:
        RF off, the lease over, and the broker told (claim back to rx)."""
        def done():
            claims = list(self.fake.claims.values()) if self.fake else []
            return (len(self.sent) >= n and not self.radio.state()["keyed"] and self.srv.lease is None
                    and not self.srv.digi.in_flight and all(c["mode"] == "rx" and not c["onAir"] for c in claims))
        return self.wait(done)

    def next_slot(self, slots=2, beat=True):
        """Our next slot (two slots on: theirs comes between), the remote
        still there (its heartbeat) unless `beat` is False."""
        self.utc[0] += 15.0 * slots
        self.now[0] += 1.0
        if beat:
            self.assertEqual(self.beat()[0], 200)

    def decode(self, text, snr=-10, df=1200):
        """A decode of the slot just ended (theirs)."""
        self.radio._emit_event({"mode": "ft8", "slot": self.utc[0] - 15.2, "snr": snr, "dt": 0.1, "df": df,
                                "text": text})


class ArmingIsExplicit(AutoTxTest):
    def test_off_until_armed_and_arming_alone_sends_nothing(self):
        self.ft8()
        st = self.status()
        self.assertEqual((st["autoTx"]["armed"], st["onAir"]), (False, False))
        s, a = self.auto()
        self.assertEqual(s, 200, a)
        self.assertTrue(a["autoTx"]["armed"])
        self.assertEqual(a["autoTx"]["remote"], "tv-1")
        time.sleep(0.5)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.radio.state()["keyed"])

    def test_a_restarted_server_is_not_armed(self):
        # It lives only in memory: a new server over the same radio, as
        # after the app restarts, starts disarmed whatever was before.
        self.ft8()
        self.auto({"cq": True})
        again = Server(self.radio, nb_server.info("9.9.9"), self.audio, secret=SECRET)
        self.assertFalse(again.status()["autoTx"]["armed"])

    def test_needs_the_transmit_level_a_digital_mode_and_a_callsign(self):
        self.ft8()
        s, a = self.auto(level="control")
        self.assertEqual((s, a["needs"]), (403, "transmit"))
        self.req("POST", "/api/set", {"mode": "usb"}, level="control")
        s, a = self.auto()
        self.assertEqual((s, a["code"]), (409, "not_digital"))
        self.ft8()
        self.radio.st["callsign"] = ""
        s, a = self.auto({"cq": True})
        self.assertEqual((s, a["code"]), (409, "no_callsign"))
        self.assertEqual(self.sent, [])

    def test_one_remote_at_a_time(self):
        self.ft8()
        self.auto()
        s, a = self.auto(remote="phone-2")
        self.assertEqual((s, a["code"]), (409, "armed_elsewhere"))
        # Nor may another remote key PTT over it, or keep it alive.
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-2"})
        self.assertEqual((a["onAir"], a["txError"]), (False, "Automatic transmit is armed by another remote"))
        self.assertEqual(self.beat("phone-2")[0], 409)


class KeysItselfForEachOver(AutoTxTest):
    def test_cq_keys_after_the_broker_says_yes_and_unkeys_at_the_end(self):
        self.ft8()
        keyed_at_onair = []
        real_on_air = self.srv.broker.on_air

        def on_air(*args, **kw):
            keyed_at_onair.append(self.radio.state()["keyed"])
            return real_on_air(*args, **kw)
        self.srv.broker.on_air = on_air
        s, a = self.auto({"cq": True})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.over_ended(1))
        self.assertEqual(keyed_at_onair, [False])                 # asked before any RF
        self.assertEqual(self.sent[0][0], "ft8")
        self.assertEqual(self.sent[0][1]["text"], "CQ GM4BRI IO75")
        claim = next(iter(self.fake.claims.values()))
        self.assertEqual((claim["mode"], claim["onAir"]), ("rx", False))
        # Still armed, and calling again in our next slot - not in theirs.
        self.assertTrue(self.status()["autoTx"]["armed"])
        self.utc[0] += 15.0
        self.now[0] += 1.0
        self.beat()
        time.sleep(0.5)
        self.assertEqual(len(self.sent), 1)
        self.next_slot(1)
        self.assertTrue(self.over_ended(2))
        self.assertEqual(self.sent[1][1]["text"], "CQ GM4BRI IO75")

    def test_a_reply_runs_the_qso_through_to_the_log_and_stops(self):
        self.ft8()
        cq = {"mode": "ft8", "slot": T0, "snr": -7, "dt": 0.2, "df": 1234, "text": "CQ DL1ABC JO31",
              "call": "DL1ABC", "grid": "JO31"}
        self.utc[0] = T0 + 15.2                     # their CQ was even: we answer odd, now
        s, a = self.auto({"reply": cq})
        self.assertEqual(s, 200, a)
        self.assertEqual((a["autoTx"]["dx"], a["autoTx"]["period"]), ("DL1ABC", "odd"))
        self.assertTrue(self.over_ended(1))
        self.assertEqual(self.sent[0][1]["text"], "DL1ABC GM4BRI IO75")
        self.assertEqual(self.sent[0][1]["freq"], 1234.0)          # on their frequency
        self.decode("GM4BRI DL1ABC -12", snr=-7)
        self.next_slot()
        self.assertTrue(self.over_ended(2))
        self.assertEqual(self.sent[1][1]["text"], "DL1ABC GM4BRI R-07")
        self.decode("GM4BRI DL1ABC RR73")
        self.next_slot()
        self.assertTrue(self.over_ended(3))
        self.assertEqual(self.sent[2][1]["text"], "DL1ABC GM4BRI 73")
        # 73 is the last over: logged, and transmit is off by itself.
        self.assertTrue(self.wait(lambda: not self.status()["autoTx"]["armed"]))
        self.assertIn("DL1ABC", self.status()["autoTx"]["why"])
        log = self.req("GET", "/api/log")[1]["qsos"]
        self.assertEqual([(q["call"], q["rstSent"], q["rstRcvd"]) for q in log], [("DL1ABC", "-07", "-12")])
        self.next_slot(beat=False)
        time.sleep(0.5)
        self.assertEqual(len(self.sent), 3)

    def test_a_reply_to_a_cq_with_a_modifier_answers_the_station(self):
        # No call field, as a client that sends only the text: "CQ DX
        # OH8ZZ KP20" is OH8ZZ (it was answered as DX until 12/10/2026).
        self.ft8()
        self.utc[0] = T0 + 15.2
        for text, call, grid in (("CQ DX OH8ZZ KP20", "OH8ZZ", "KP20"), ("CQ POTA EA8XYZ IL18", "EA8XYZ", "IL18"),
                                 ("CQ 290 K1ABC FN42", "K1ABC", "FN42"), ("CQ DL1ABC JO31", "DL1ABC", "JO31")):
            s, a = self.auto({"reply": {"mode": "ft8", "slot": T0, "snr": -7, "df": 1234, "text": text}})
            self.assertEqual(s, 200, a)
            self.assertEqual(a["autoTx"]["dx"], call)
            self.assertEqual(a["autoTx"]["next"], f"{call} GM4BRI IO75")
            self.assertEqual(self.srv.digi.seq.dxgrid, grid)
            self.srv.halt_if_keyed("next")
        s, a = self.auto({"reply": {"mode": "ft8", "slot": T0, "text": "CQ DX"}})
        self.assertEqual((s, a.get("code")), (400, "no_call"))

    def test_heartbeats_keep_it_between_overs(self):
        self.ft8()
        self.auto({"cq": True})
        self.assertTrue(self.over_ended(1))
        for _n in range(3):                         # 9 s of lease time, each 3 s answered
            self.now[0] += 3.0
            self.assertEqual(self.beat()[0], 200)
            time.sleep(0.3)
        self.assertTrue(self.status()["autoTx"]["armed"])


class ATvAllowedDigitalTransmit(AutoTxTest):
    """CONTROLLER-CONTRACT 5.5 (Brian, 11/10/2026): an administrator may let
    one TV transmit digital modes. It arrives at the Control level with
    X-OpenHamShack-Transmit: digital, may arm Enable TX and keep the arm
    alive, and never keys PTT or sends TX audio."""

    def tv(self, method, path, body=None, transmit="digital"):
        return self.req(method, path, body, level="control", transmit=transmit)

    def test_a_tv_without_it_is_refused_enable_tx(self):
        self.ft8()
        s, a = self.tv("POST", "/api/autotx", {"on": True, "remote": "tv-1", "cq": True}, transmit="none")
        self.assertEqual((s, a["needs"]), (403, "transmit"))
        self.assertFalse(self.status()["autoTx"]["armed"])
        self.assertEqual(self.sent, [])

    def test_with_it_enable_tx_sends_and_the_broker_is_told_the_over_is_digital(self):
        self.ft8()
        s, a = self.tv("POST", "/api/autotx", {"on": True, "remote": "tv-1", "cq": True})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.over_ended(1))
        self.assertEqual(self.sent[0][1]["text"], "CQ GM4BRI IO75")
        onair = [b for _m, p, b, _h in self.fake.calls if p.endswith("/onair") and b.get("on")]
        self.assertEqual([b.get("digital") for b in onair], [True])
        # The TV keeps its own arm alive between overs.
        self.now[0] += 3.0
        self.assertEqual(self.tv("POST", "/api/ptt/heartbeat", {"remote": "tv-1"})[0], 200)
        self.assertTrue(self.status()["autoTx"]["armed"])

    def test_but_never_voice(self):
        self.req("POST", "/api/set", {"mode": "usb", "vfo": 10_489_700_000.0}, level="control")
        s, a = self.tv("POST", "/api/ptt", {"on": True, "remote": "tv-1"})
        self.assertEqual((s, a["needs"]), (403, "transmit"))
        self.assertEqual(self.tv("GET", "/api/audio/tx")[0], 403)
        # Nor a heartbeat for anything but its own arm.
        self.assertEqual(self.tv("POST", "/api/ptt/heartbeat", {"remote": "tv-1"})[0], 403)
        self.assertFalse(self.radio.state()["keyed"])
        self.assertFalse(any(p.endswith("/onair") for _m, p, _b, _h in self.fake.calls))

    def test_a_ptt_over_is_never_called_digital(self):
        self.req("POST", "/api/set", {"mode": "usb", "vfo": 10_489_700_000.0}, level="control")
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertEqual(s, 200, a)
        onair = [b for _m, p, b, _h in self.fake.calls if p.endswith("/onair") and b.get("on")]
        self.assertEqual(len(onair), 1)
        self.assertNotIn("digital", onair[0])
        self.req("POST", "/api/ptt", {"on": False})


class EveryGuardStillDecides(AutoTxTest):
    def assert_off(self, txt=None):
        self.assertTrue(self.wait(lambda: not self.status()["autoTx"]["armed"]))
        st = self.status()
        self.assertFalse(st["onAir"])
        if txt:
            self.assertIn(txt, st["autoTx"]["why"])
        return st

    def test_the_band_plan_refuses_and_it_disarms(self):
        self.ft8(SSB_DIAL)
        s, a = self.auto({"cq": True})
        st = self.assert_off()
        self.assertTrue(st["txError"])
        self.assertEqual(st["autoTx"]["why"], st["txError"])
        self.next_slot(beat=False)
        time.sleep(0.5)
        self.assertFalse(self.radio.state()["keyed"])

    def test_the_broker_refuses_and_it_disarms(self):
        self.ft8()
        self.fake.refuse_onair = "The station licence does not allow this."
        self.auto({"cq": True})
        self.assert_off("The station licence does not allow this.")
        self.assertEqual(self.sent, [])               # refused before the engine was asked

    def test_the_remote_going_quiet_disarms(self):
        self.ft8()
        self.auto({"cq": True})
        self.assertTrue(self.over_ended(1))
        self.now[0] += 5.5
        self.assert_off("remote controller lost")
        self.next_slot(beat=False)
        self.assertEqual(self.beat()[0], 409)
        time.sleep(0.5)
        self.assertEqual(len(self.sent), 1)

    def test_a_mode_change_disarms(self):
        self.ft8()
        self.auto({"cq": True})
        self.assertTrue(self.over_ended(1))
        self.req("POST", "/api/set", {"mode": "ft4"}, level="control")
        self.assert_off("mode changed")

    def test_nobody_choosing_anything_for_six_minutes_stops_it(self):
        # WSJT-X's Tx watchdog. Heartbeats come from a phone left on the
        # table by themselves, so they do not count as someone there.
        self.ft8()
        self.auto({"cq": True})
        self.assertTrue(self.over_ended(1))
        with self.srv.lock:
            self.srv.digi.last_action -= IDLE_S + 1
        self.assert_off("6 minutes")

    def test_a_stopped_radio_and_a_lost_claim_disarm(self):
        self.ft8()
        self.auto()
        self.req("POST", "/api/stop", level="control")
        self.assert_off()
        self.req("POST", "/api/start", level="control")
        self.ft8()
        self.auto()
        self.fake.claims.clear()            # the admin's "Stop all transmitting"
        with self.srv.broker.lock:
            c = self.srv.broker.claims["pluto-1"]
            c["beat"] = -1e9
        self.assert_off()


class HaltWins(AutoTxTest):
    realtime = True         # a real FT8 over: 12.6 s on the air, so a stop lands during it

    def on_air(self):
        self.ft8()
        self.auto({"cq": True})
        self.assertTrue(self.wait(lambda: self.radio.state().get("txSource") == "send:ft8"))
        self.assertTrue(self.radio.state()["keyed"])

    def gone(self):
        t = time.monotonic()
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"], timeout=3.0))
        self.assertLess(time.monotonic() - t, 2.0)
        st = self.status()
        self.assertFalse(st["autoTx"]["armed"])
        self.next_slot(beat=False)
        time.sleep(0.5)
        self.assertFalse(self.radio.state()["keyed"])
        self.assertEqual(len(self.sent), 1)

    def test_halt_ends_the_over_now_and_disarms(self):
        self.on_air()
        self.assertEqual(self.req("POST", "/api/halt", level="control")[0], 200)
        self.gone()

    def test_ptt_off_and_enable_tx_off_end_the_over_too(self):
        self.on_air()
        s, a = self.req("POST", "/api/autotx", {"on": False}, level="control")
        self.assertEqual(s, 200)
        self.gone()
        self.utc[0] += 60
        self.on_air()
        self.req("POST", "/api/ptt", {"on": False}, level="control")
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"], timeout=3.0))
        self.assertFalse(self.status()["autoTx"]["armed"])


class TextModes(AutoTxTest):
    def test_a_line_keys_for_its_length_and_stays_armed(self):
        s, a = self.req("POST", "/api/set", {"mode": "psk31", "vfo": FT8_DIAL}, level="control")
        self.assertEqual(s, 200, a)
        s, a = self.auto({"text": "CQ CQ DE GM4BRI K"})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.over_ended(1))
        self.assertEqual(self.sent[0], ("psk31", {"text": "CQ CQ DE GM4BRI K ", "freq": 1000.0}))
        self.assertTrue(self.status()["autoTx"]["armed"])
        s, a = self.auto({"cq": True})
        self.assertEqual((s, a["code"]), (409, "not_sequenced"))



class OwnOversOnEvents(AutoTxTest):
    """Each over we send goes on api/events nested under "tx", so a
    remote's Band Activity can list it in its slot - and nothing that reads
    decodes takes it for a station heard."""

    def test_each_over_is_published_in_its_slot_and_never_as_a_decode(self):
        feed = self.radio.subscribe("events", 64)
        self.addCleanup(self.radio.unsubscribe, feed)
        self.ft8()
        cq = {"mode": "ft8", "slot": T0, "snr": -7, "dt": 0.2, "df": 1234, "text": "CQ DL1ABC JO31",
              "call": "DL1ABC", "grid": "JO31"}
        self.utc[0] = T0 + 15.2
        self.assertEqual(self.auto({"reply": cq})[0], 200)
        self.assertTrue(self.over_ended(1))
        ours = [ev for ev in feed.drain() if "tx" in ev]
        self.assertEqual(len(ours), 1)
        ev = ours[0]
        self.assertEqual(ev["tx"], {"slot": T0 + 15.0, "df": 1234, "text": "DL1ABC GM4BRI IO75"})
        self.assertEqual(ev["mode"], "ft8")
        # No "text" or "slot" of its own: an older Remote drops it, and the
        # sequencer did not hear our own call and answer it.
        self.assertNotIn("text", ev)
        self.assertNotIn("slot", ev)
        self.assertEqual(self.status()["autoTx"]["next"], "DL1ABC GM4BRI IO75")


if __name__ == "__main__":
    unittest.main()
