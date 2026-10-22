"""OpenHamShack HAM transmitting on the band simulator: FM through a repeater
(the right tone opens it, the wrong one does not, a toneburst does where
it is accepted), repeater shift and reverse, split/RIT/XIT, the power
chain against the licence, the SWR and PA-temperature trips, the PTT
sequencer's order, and where a signal lands. Nothing here touches real
hardware: the device is the simulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import time
import unittest

import numpy as np

from ham_helpers import close, make_radio, pump, speech
from ohscore.engine import TxRefused
from ohsradio.sequencer import NoOutput, Sequencer, SequencerError, SerialOutput


def sim_seconds(r):
    return r.dev.n / r.dev.fs


def run_sim(r, seconds, until=None):
    """Heartbeat until `seconds` of simulated time have passed."""
    end = sim_seconds(r) + seconds
    t_wall = time.monotonic() + 60
    while sim_seconds(r) < end and time.monotonic() < t_wall:
        r.heartbeat()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


class Repeaters(unittest.TestCase):
    def setUp(self):
        self.r = make_radio(audio_source=speech, simHourUtc=3.0, drive=0.5)
        self.r.set(authorise=True, licenceClass="full")
        self.r.start()
        self.assertTrue(run_sim(self.r, 30, until=lambda: bool(self.r.dev.repeaters)))
        self.rep = next(x for x in self.r.dev.repeaters if 145e6 < x.dl < 146e6 and x.toneburst)
        self.r.set(mode="fm", vfo=self.rep.dl, rptShift="auto")

    def tearDown(self):
        close(self.r)

    def over(self, seconds=2.5):
        self.r.ptt(True)
        self.assertTrue(self.r.state()["keyed"])
        run_sim(self.r, seconds)
        self.r.ptt(False)
        # The over ends when the transmit thread has walked the sequence down.
        pump(self.r, 5, until=lambda: not (self.r.tx_thread and self.r.tx_thread.is_alive()))

    def test_transmit_dial_is_the_input(self):
        st = self.r.state()
        self.assertEqual(st["txDial"], self.rep.dl - 600_000)
        self.assertEqual(st["rxDial"], self.rep.dl)
        self.assertEqual(st["shift"], -600_000)

    def test_right_tone_opens_it_and_its_courtesy_comes_back_with_the_tone(self):
        self.r.set(ctcssTx=self.rep.tone)
        self.over()
        self.assertEqual(self.rep.opened, 1)
        # Unkeyed: we hear the repeater's output carrying its own tone.
        heard = run_sim(self.r, 3.0, until=lambda: self.r.state()["ctcssHeard"] == self.rep.tone)
        self.assertTrue(heard, self.r.state()["ctcssHeard"])

    def test_wrong_tone_or_none_and_it_stays_shut(self):
        wrong = 67.0 if self.rep.tone != 67.0 else 71.9
        self.r.set(ctcssTx=wrong)
        self.over()
        self.r.set(ctcssTx=0.0)
        self.over()
        self.assertEqual(self.rep.opened, 0)

    def test_toneburst_opens_a_repeater_that_takes_one(self):
        self.r.set(ctcssTx=0.0)
        self.r.toneburst()
        self.assertTrue(self.r.state()["keyed"])
        run_sim(self.r, 2.0, until=lambda: not self.r.state()["keyed"])
        self.assertFalse(self.r.state()["keyed"])            # a burst is a short over by itself
        self.assertEqual(self.rep.opened, 1)

    def test_reverse_listens_on_the_input(self):
        self.r.set(rptReverse=True)
        st = self.r.state()
        self.assertEqual((st["rxDial"], st["txDial"]), (self.rep.dl - 600_000, self.rep.dl))

    def test_an_offset_that_moves_the_input_out_of_bounds_unkeys_at_once(self):
        # The guard judges where the transmission lands, so changing the
        # offset mid-over is a change of transmit frequency like any other:
        # +5 MHz from a 2 m output is 150 MHz, outside every licence.
        self.r.set(ctcssTx=self.rep.tone)
        self.r.ptt(True)
        self.assertTrue(self.r.state()["keyed"])
        self.r.set(rptShift="plus", rptOffsetHz=5_000_000.0)
        pump(self.r, 0.5)
        st = self.r.state()
        self.assertFalse(st["keyed"])
        self.assertEqual(st["txDial"], self.rep.dl + 5_000_000)
        self.assertNotEqual(st["txBlocked"], "")


class Dials(unittest.TestCase):
    def setUp(self):
        self.r = make_radio()

    def tearDown(self):
        close(self.r)

    def test_split_rit_xit(self):
        self.r.set(vfo=14_200_000.0, mode="usb", txVfo=14_205_000.0, split=True)
        self.assertEqual(self.r.state()["txDial"], 14_205_000.0)
        self.r.set(xit=120.0, xitOn=True, rit=-50.0, ritOn=True)
        st = self.r.state()
        self.assertEqual((st["rxDial"], st["txDial"]), (14_199_950.0, 14_205_120.0))

    def test_manual_shift_and_simplex(self):
        self.r.set(vfo=433_500_000.0, mode="fm")
        self.assertEqual(self.r.state()["txDial"], 433_500_000.0)        # U280: simplex channel
        self.r.set(vfo=433_200_000.0)
        self.assertEqual(self.r.state()["txDial"], 434_800_000.0)        # RB8: +1.6 MHz, UK way round
        self.r.set(rptShift="minus", rptOffsetHz=1_600_000.0)
        self.assertEqual(self.r.state()["txDial"], 431_600_000.0)
        self.r.set(rptShift="simplex")
        self.assertEqual(self.r.state()["txDial"], 433_200_000.0)

    def test_each_band_arrives_with_its_uk_repeater_split(self):
        # bandplan-r1-uk.md section 3: RV 600 kHz, RB 1.6 MHz, RM 6 MHz.
        for name, offset in (("70cm", 1_600_000.0), ("23cm", 6_000_000.0), ("2m", 600_000.0)):
            self.r.band(name)
            self.assertEqual(self.r.state()["rptOffsetHz"], offset, name)
        self.r.set(vfo=433_200_000.0)                                    # typed, not the band button
        self.assertEqual(self.r.state()["rptOffsetHz"], 1_600_000.0)

    def test_a_5_mhz_rbw_split_can_be_set_and_the_band_stack_keeps_it(self):
        self.r.band("70cm")
        self.r.set(mode="fm", vfo=433_150_000.0, rptShift="plus", rptOffsetHz=5_000_000.0)
        self.assertEqual(self.r.state()["txDial"], 438_150_000.0)       # an RBW repeater's input
        self.r.band("2m")
        self.assertEqual(self.r.state()["rptOffsetHz"], 600_000.0)
        self.r.band("70cm")
        st = self.r.state()
        self.assertEqual((st["vfo"], st["rptShift"], st["rptOffsetHz"]), (433_150_000.0, "plus", 5_000_000.0))
        self.assertEqual(st["txDial"], 438_150_000.0)

    def test_the_guard_judges_the_shifted_input_not_the_output(self):
        # An odd offset that puts the input in 2 m's satellite sub-band is
        # refused although the dial (the output) is an ordinary RV channel.
        self.r.set(authorise=True, licenceClass="full")
        self.r.set(mode="fm", vfo=145_600_000.0, rptShift="plus", rptOffsetHz=300_000.0)
        st = self.r.state()
        self.assertEqual(st["txDial"], 145_900_000.0)
        self.assertEqual(st["licenceInfo"]["level"], "refused")
        self.assertIn("satellite", st["licenceInfo"]["why"].lower())
        self.r.set(rptShift="minus")
        self.assertEqual(self.r.state()["licenceInfo"]["level"], "ok")

    def test_shift_only_in_fm(self):
        self.r.set(vfo=145_650_000.0, mode="usb")
        self.assertEqual(self.r.state()["txDial"], 145_650_000.0)


class Power(unittest.TestCase):
    def setUp(self):
        self.r = make_radio(audio_source=speech)

    def tearDown(self):
        close(self.r)

    def test_an_estimate_over_the_licence_warns_and_does_not_hold_the_drive(self):
        # Foundation, 2 m: 25 W PEP. A PA making 100 W at full drive: the
        # estimate passes 25 W at drive 0.5, and that is only a warning now.
        self.r.set(authorise=True, bandPower={"2m": {"devW": 1.0, "paGainDb": 20.0}})
        st = self.r.state()
        self.assertAlmostEqual(st["maxDrive"], 1.0)
        self.r.set(drive=0.5)
        self.assertEqual(self.r.state()["licenceInfo"]["powerWarning"], "")
        self.r.set(drive=0.8)
        st = self.r.state()
        self.assertAlmostEqual(st["estPep"], 64.0, places=3)
        info = st["licenceInfo"]
        self.assertEqual(info["level"], "warn")
        self.assertIn("25 W PEP maximum", info["powerWarning"])
        self.assertIn("estimate", info["why"])
        self.assertFalse(info["measured"])           # a PA: the sensor cannot see the antenna power

    def test_am_pep_is_a_quarter_of_usb_at_the_same_drive(self):
        # AM's envelope peaks at -6 dBFS (ohscore/dsp/mod.py AmMod): the
        # estimate the licence is judged by must say so, not the USB figure.
        self.r.set(authorise=True, bandPower={"2m": {"devW": 1.0, "paGainDb": 20.0}})
        self.r.set(drive=0.8, mode="usb")
        usb = self.r.state()["estPep"]
        self.r.set(mode="am")
        self.assertAlmostEqual(self.r.state()["estPep"], usb / 4, places=3)

    def test_ceiling(self):
        self.r.set(authorise=True, bandPower={"2m": {"ceiling": 0.3}})
        self.assertAlmostEqual(self.r.state()["maxDrive"], 0.3)
        self.assertAlmostEqual(self.r.state()["drive"], 0.25)

    def test_ham_bandpower_is_validated(self):
        with self.assertRaisesRegex(ValueError, "paGainDb must be between"):
            self.r.set(authorise=True, bandPower={"2m": {"paGainDb": 99.0}})
        with self.assertRaisesRegex(ValueError, "no band called"):
            self.r.set(authorise=True, bandPower={"7m": {}})

    def test_estimate_over_the_limit_keys_with_a_warning(self):
        # Intermediate on 1850-2000 kHz: 32 W PEP. The HL2-like 5 W device with a
        # 10 dB amplifier at full drive estimates 50 W: it used to be refused;
        # now it keys, and says the estimate is over: on the transmit card's
        # standing warning, before keying and through the over, not a toast
        # at every key-up (until 0.1.10).
        self.r.set(authorise=True, licenceClass="intermediate",
                   bandPower={"160m": {"paGainDb": 10.0, "ceiling": 1.0}})
        self.r.set(vfo=1_900_000.0, mode="lsb")
        toasts = self.r.subscribe("toast", 64)
        self.r.start()
        self.r.set(drive=1.0)
        self.assertEqual(self.r.state()["txBlocked"], "")
        w = self.r.state()["txWarning"]
        self.assertEqual((w["key"], w["level"]), ("power", "warn"))
        self.assertIn("not refused", w["text"])
        self.assertIn("32 W PEP maximum", w["detail"])
        self.r.ptt(True)
        pump(self.r, 1.0)
        self.assertTrue(self.r.state()["keyed"])     # the PA gain means nothing measured unkeys it
        self.assertEqual(self.r.state()["txWarning"], w)
        self.r.ptt(False)
        said = [t["text"] for t in toasts.drain()]
        self.assertFalse(any("32 W PEP maximum" in t for t in said), said)
        # Under the limit again, it goes.
        self.r.set(drive=0.5)
        self.assertEqual(self.r.state()["txWarning"], {})


class Protection(unittest.TestCase):
    def tune_on_20m(self, **over):
        r = make_radio(**over)
        r.set(vfo=14_060_000.0, mode="cw", drive=1.0)
        r.start()
        return r

    def test_high_swr_unkeys_and_holds_until_acknowledged(self):
        r = self.tune_on_20m(simAntSwr=3.5)
        try:
            toasts = r.subscribe("toast", 64)
            r.tune(True)
            run_sim(r, 3.0, until=lambda: not r.state()["keyed"])
            st = r.state()
            self.assertFalse(st["keyed"])
            self.assertTrue(st["swrTripped"])
            self.assertTrue(any("SWR" in t["text"] for t in toasts.drain()))
            with self.assertRaisesRegex(TxRefused, "high SWR"):
                r.ptt(True)
            r.ack_swr()
            self.assertEqual(r.state()["txBlocked"], "")
        finally:
            close(r)

    def test_good_swr_keeps_transmitting(self):
        r = self.tune_on_20m(simAntSwr=1.5)
        try:
            r.tune(True)
            run_sim(r, 2.0)
            st = r.state()
            self.assertTrue(st["keyed"])
            self.assertAlmostEqual(st["swr"], 1.5, delta=0.1)
            r.tune(False)
        finally:
            close(r)

    def test_tune_sends_tune_drive_times_drive(self):
        # What Settings and the guide promise: Tune drive is a share of the
        # current Drive, not of the band's ceiling.
        r = self.tune_on_20m(simAntSwr=1.2)
        try:
            r.set(drive=0.4)
            r.set(authorise=True, tuneDrive=0.25)
            r.tune(True)
            run_sim(r, 0.5)
            self.assertTrue(r.state()["keyed"])
            self.assertAlmostEqual(r.dev.drive, 0.1, places=6)
            r.tune(False)
        finally:
            close(r)

    def test_pa_temperature_trip(self):
        r = self.tune_on_20m()
        try:
            r.set(authorise=True, paTempLimit=30.0)      # the sim's PA starts at 31 C
            r.tune(True)
            run_sim(r, 2.0, until=lambda: not r.state()["keyed"])
            self.assertFalse(r.state()["keyed"])
        finally:
            close(r)


class MeasuredPower(unittest.TestCase):
    """The licence's power limit is enforced on what the radio measures
    (the simulator reports forward power, as the HL2 does). 60 m, Full
    licence: 200 W EIRP. A tune carrier from the simulator's 5 W at 25 %
    drive is about 0.3 W; a 35 dBi antenna gain makes that ~1 kW EIRP."""

    def tune_on_60m(self, ant_gain, **chain):
        r = make_radio(licenceClass="full")
        r.set(authorise=True, bandPower={"60m": {"antGainDbi": ant_gain, **chain}})
        r.set(vfo=5_355_000.0, mode="cw", drive=1.0)
        r.start()
        return r

    def test_a_measured_excess_unkeys_with_the_reason(self):
        r = self.tune_on_60m(35.0)
        try:
            toasts = r.subscribe("toast", 64)
            r.tune(True)
            run_sim(r, 3.0, until=lambda: not r.state()["keyed"])
            self.assertFalse(r.state()["keyed"])
            said = [t["text"] for t in toasts.drain()]
            self.assertTrue(any("Unkeyed" in t and "200 W EIRP maximum on 60 m" in t and "measured" in t
                                for t in said), said)
            # Not latched like the SWR trip: the reason says what to lower.
            self.assertTrue(any("Lower Drive" in t for t in said), said)
            self.assertFalse(r.state()["swrTripped"])
        finally:
            close(r)

    def test_measured_under_the_limit_keeps_transmitting(self):
        r = self.tune_on_60m(0.0)
        try:
            r.tune(True)
            run_sim(r, 2.0)
            st = r.state()
            self.assertTrue(st["keyed"])
            self.assertGreater(st["fwdW"], 0.1)
            self.assertTrue(st["licenceInfo"]["measured"])
            r.tune(False)
        finally:
            close(r)

    def test_with_a_pa_the_reading_is_not_the_antenna_power(self):
        # 10 dB of entered PA gain: the radio's sensor sees the PA's input,
        # so the excess is an estimate again, and only warns.
        r = self.tune_on_60m(35.0, paGainDb=10.0)
        try:
            self.assertFalse(r.state()["licenceInfo"]["measured"])
            self.assertIn("estimate", r.state()["licenceInfo"]["powerWarning"])
            r.tune(True)
            run_sim(r, 2.0)
            self.assertTrue(r.state()["keyed"])
            r.tune(False)
        finally:
            close(r)


class Lands(unittest.TestCase):
    def test_cw_carrier_lands_at_the_pitch_above_the_dial(self):
        r = make_radio()
        try:
            r.set(authorise=True, licenceClass="full")
            r.set(vfo=14_050_000.0, mode="cw", drive=0.5)
            wide = r.subscribe("wide", 512)
            r.start()
            run_sim(r, 1.0)
            r.ptt(True)
            run_sim(r, 1.5)
            lines = wide.drain()
            r.ptt(False)
            t, start, bin_hz, db = lines[-1]
            peak = start + bin_hz * int(np.argmax(db))
            self.assertLess(abs(peak - 14_050_700.0), 2 * bin_hz)
        finally:
            close(r)

    def test_am_transmits_double_sideband_and_the_plan_warns_on_its_width(self):
        r = make_radio(audio_source=speech)
        try:
            r.set(authorise=True, licenceClass="full")
            r.set(vfo=14_286_000.0, mode="am")
            r.start()
            self.assertTrue(r.state()["modes"]["am"]["encode"])
            self.assertEqual(r._occupied("am", 14_286_000.0), (14_283_300.0, 14_288_700.0))
            info = r.state()["licenceInfo"]
            self.assertEqual(info["level"], "warn")
            self.assertIn("2700 Hz", info["why"])
            w = r.state()["txWarning"]
            self.assertEqual(w["key"], "plan")
            self.assertIn("2700 Hz", w["text"])
            self.assertIn("not refused", w["text"])
            r.ptt(True)
            run_sim(r, 0.5)
            self.assertTrue(r.state()["keyed"])
            r.ptt(False)
        finally:
            close(r)

    def test_half_duplex_mutes_receive_audio(self):
        r = make_radio(audio_source=speech)
        try:
            r.set(authorise=True, licenceClass="full")
            r.set(vfo=145_500_000.0, mode="fm", volume=1.0)
            r.start()
            self.assertEqual(r._rx_audio_gain(r.state()), 1.0)
            r.ptt(True)
            self.assertEqual(r._rx_audio_gain(r.state()), 0.0)
            r.ptt(False)
        finally:
            close(r)

    def test_ft8_reply_above_1khz_on_60m_leaves_the_uk_segment(self):
        from ohscore import modes_glue
        if modes_glue.encoder("ft8") is None:
            self.skipTest("no FT8 encoder (wsjtx) here")
        r = make_radio()
        try:
            r.set(authorise=True, licenceClass="full")
            r.set(vfo=5_357_000.0, mode="ft8")
            r.start()
            with self.assertRaisesRegex(TxRefused, "eleven UK segments"):
                r.send("ft8", text="CQ GM4BRI IO86", freq=1500.0)
            r.send("ft8", text="CQ GM4BRI IO86", freq=600.0)
            self.assertTrue(r.state()["keyed"] or r.tx_req is not None)
            r.ptt(False)
        finally:
            close(r)


class FakeLine:
    def __init__(self, log):
        self.log = log

    def set(self, on):
        self.log.append(("line", on, time.monotonic()))

    def close(self):
        self.log.append(("closed", None, time.monotonic()))


class Sequencing(unittest.TestCase):
    def test_line_before_rf_and_after_it(self):
        log = []
        s = Sequencer(FakeLine(log), delay_ms=30, on_state=lambda st: log.append(("state", st, time.monotonic())))
        self.assertTrue(s.key_up())
        log.append(("rf", True, time.monotonic()))
        log.append(("rf", False, time.monotonic()))
        s.key_down()
        kinds = [(k, v) for k, v, _ in log]
        self.assertEqual(kinds, [("line", True), ("state", "seq"), ("state", "tx"), ("rf", True), ("rf", False),
                                 ("state", "hang"), ("line", False), ("state", "rx")])
        t = {(k, v): ts for k, v, ts in log}
        self.assertGreaterEqual(t[("rf", True)] - t[("line", True)], 0.029)
        self.assertGreaterEqual(t[("line", False)] - t[("rf", False)], 0.029)

    def test_cancel_during_the_wait_drops_the_line_and_no_rf(self):
        log = []
        s = Sequencer(FakeLine(log), delay_ms=200)
        t0 = time.monotonic()
        self.assertFalse(s.key_up(still_wanted=lambda: time.monotonic() - t0 < 0.05))
        self.assertEqual([(k, v) for k, v, _ in log], [("line", True), ("line", False)])

    def test_key_down_always_drops_the_line(self):
        log = []

        def bad_sleep(_):
            raise RuntimeError("interrupted")
        s = Sequencer(FakeLine(log), delay_ms=10, sleep=bad_sleep)
        s.out.set(True)
        with self.assertRaises(RuntimeError):
            s.key_down()
        self.assertEqual(log[-1][:2], ("line", False))
        self.assertEqual(s.state, "rx")

    def test_engine_runs_the_sequence_around_the_device(self):
        r = make_radio(audio_source=speech)
        try:
            r.set(authorise=True, licenceClass="full")
            r.set(vfo=145_500_000.0, mode="fm")
            r.start()
            log = []
            r.seq = Sequencer(FakeLine(log), delay_ms=20, on_state=lambda st: None)
            dev = r.dev
            start, stop = dev.tx_start, dev.tx_stop
            dev.tx_start = lambda: (log.append(("dev", True, time.monotonic())), start())[1]
            dev.tx_stop = lambda: (log.append(("dev", False, time.monotonic())), stop())[1]
            r.ptt(True)
            # The sequencer's 20 ms is wall-clock time; 0.5 s of unpaced
            # simulation can pass in less than that on a fast machine (an M4
            # Mac: ~10 ms), and the release then came before the device was
            # ever started. Wait for the device to start, then transmit.
            pump(r, 5.0, until=lambda: len(log) >= 2)
            run_sim(r, 0.5)
            r.ptt(False)
            pump(r, 1.0, until=lambda: len(log) >= 4)
            self.assertEqual([(k, v) for k, v, _ in log], [("line", True), ("dev", True), ("dev", False),
                                                           ("line", False)])
        finally:
            close(r)

    def test_no_output_and_a_missing_port(self):
        self.assertTrue(Sequencer(NoOutput()).key_up())
        with self.assertRaisesRegex(SequencerError, "no port is named"):
            SerialOutput("")
        with self.assertRaisesRegex(SequencerError, "Could not open /dev/nonexistent-tty"):
            SerialOutput("/dev/nonexistent-tty")

    def test_serial_line_uses_this_kernels_modem_control_ioctls(self):
        # The request numbers differ between Linux and macOS; Linux's, sent
        # to a Mac's serial driver, fail with ENOTTY at the first key-up. The
        # ioctl itself is stood in for (no serial adapter here, and a pty
        # has no modem lines on either system), so this checks what is asked
        # of the kernel against the running system's own termios values.
        import fcntl
        import struct
        import termios
        from unittest import mock
        with mock.patch.object(fcntl, "ioctl") as ioctl:
            out = SerialOutput(os.devnull, "rts")
            try:
                out.set(True)
                out.set(False)
            finally:
                out.close()
        calls = [(c.args[1], struct.unpack("I", c.args[2])[0]) for c in ioctl.call_args_list]
        both = termios.TIOCM_RTS | termios.TIOCM_DTR
        self.assertEqual(calls, [(termios.TIOCMBIC, both), (termios.TIOCMBIS, termios.TIOCM_RTS),
                                 (termios.TIOCMBIC, termios.TIOCM_RTS), (termios.TIOCMBIC, both)])

    def test_unopenable_output_refuses_transmit_with_the_reason(self):
        r = make_radio(seqOutput="serial", seqPort="/dev/nonexistent-tty")
        try:
            r.set(authorise=True, licenceClass="full")
            r.start()
            with self.assertRaisesRegex(TxRefused, "sequencer"):
                r.ptt(True)
        finally:
            close(r)


if __name__ == "__main__":
    unittest.main()
