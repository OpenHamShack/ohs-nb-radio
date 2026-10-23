"""S-meter calibration's engine-side math (ohscore/smeter_cal.py): the
device/band/antenna key, the dB-for-dB gain correction, the SDRplay RSP's
LNA state as a second gain stage that is not corrected the same way, the
AGC refusal, S-unit text either side of 30 MHz, the stored table's one
line of JSON, and the API's dbm/dbfs validation. ohscore/ui/smeter.py
imports this module rather than keeping its own copy (tests/test_smeter.py
covers the desktop widget and the NB-side preference path); this file is
the headless math alone, nothing PyQt."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import smeter_cal as sc


def rspdx(**over) -> dict:
    """Remote's worked example: an SDRplay RSPdx, serial 191101D142,
    Antenna A, 2 m FM, manual rxGain 40, sdrplayLna 4."""
    st = {"device": "sdrplay", "sdrSerial": "191101D142", "soapyAntenna": "Antenna A", "band": "2m",
          "vfo": 145_650_000.0, "rxGainMode": "manual", "rxGain": 40.0, "sdrplayLna": 4}
    st.update(over)
    return st


class DeviceAndCalKey(unittest.TestCase):
    def test_the_antenna_input_is_part_of_the_key(self):
        a = sc.device_key(rspdx(soapyAntenna="Antenna A"))
        b = sc.device_key(rspdx(soapyAntenna="Antenna B"))
        self.assertNotEqual(a, b)
        self.assertIn("Antenna A", a)

    def test_a_single_input_device_has_no_antenna_in_its_key(self):
        st = {"device": "pluto", "plutoUri": "ip:192.168.2.1"}
        self.assertNotIn("@", sc.device_key(st))

    def test_cal_key_adds_the_band_and_is_none_between_bands(self):
        st = rspdx()
        self.assertEqual(sc.cal_key(st), sc.device_key(st) + "|2m")
        self.assertIsNone(sc.cal_key({**st, "band": ""}))

    def test_an_app_with_no_band_status_at_all_is_not_per_band(self):
        st = {"device": "pluto", "plutoUri": "ip:192.168.2.1"}  # NB: no "band" key
        self.assertEqual(sc.cal_key(st), sc.device_key(st))


class KnownGain(unittest.TestCase):
    def test_manual_reports_rxgain_agc_reports_none(self):
        self.assertEqual(sc.known_gain(rspdx(rxGainMode="manual", rxGain=40.0)), 40.0)
        self.assertIsNone(sc.known_gain(rspdx(rxGainMode="slow_attack")))

    def test_hl2_and_sim_always_know_theirs(self):
        self.assertEqual(sc.known_gain({"device": "hl2", "hl2Lna": 12.0}), 12.0)
        self.assertEqual(sc.known_gain({"device": "sim"}), 40.0)


class WorkedExample(unittest.TestCase):
    """Remote's measurement on ohs-box, 23/10/2026: an RSPdx ident at
    -42.6 dBFS calibrated to -93 dBm (S9, VHF)."""

    def setUp(self):
        self.st = rspdx()
        self.table = sc.calibrate({}, self.st, -42.6, -93.0)

    def test_the_offset_is_minus_50_4_db(self):
        self.assertAlmostEqual(self.table[sc.cal_key(self.st)]["offset"], -50.4, places=6)

    def test_the_ident_itself_reads_s9(self):
        cal = sc.effective(self.table, self.st)
        self.assertTrue(cal.ok, cal.why)
        dbm = -42.6 + cal.offset
        self.assertAlmostEqual(dbm, -93.0, places=6)
        self.assertEqual(sc.s_text(dbm, sc.s9_dbm(self.st["vfo"])), "S9")

    def test_the_noise_floor_reads_s4(self):
        cal = sc.effective(self.table, self.st)
        dbm = -74.4 + cal.offset
        self.assertAlmostEqual(dbm, -124.8, places=6)
        self.assertEqual(sc.s_text(dbm, sc.s9_dbm(self.st["vfo"])), "S4")

    def test_a_later_manual_gain_change_is_corrected_db_for_db(self):
        at_30 = sc.effective(self.table, {**self.st, "rxGain": 30.0})
        at_50 = sc.effective(self.table, {**self.st, "rxGain": 50.0})
        self.assertAlmostEqual(at_30.offset, -40.4, places=6)
        self.assertAlmostEqual(at_50.offset, -60.4, places=6)

    def test_the_lna_state_moving_means_not_calibrated(self):
        cal = sc.effective(self.table, {**self.st, "sdrplayLna": 7})
        self.assertFalse(cal.ok)
        self.assertEqual(cal.why_code, "extra_changed")

    def test_agc_means_not_calibrated(self):
        cal = sc.effective(self.table, {**self.st, "rxGainMode": "slow_attack"})
        self.assertFalse(cal.ok)
        self.assertEqual(cal.why_code, "agc")

    def test_between_bands_means_not_calibrated(self):
        cal = sc.effective(self.table, {**self.st, "band": ""})
        self.assertFalse(cal.ok)
        self.assertEqual(cal.why_code, "between_bands")

    def test_no_calibration_yet_for_a_different_antenna(self):
        cal = sc.effective(self.table, {**self.st, "soapyAntenna": "Antenna B"})
        self.assertFalse(cal.ok)
        self.assertEqual(cal.why_code, "no_calibration")

    def test_round_trips_through_one_line_of_json_with_the_extra_stage(self):
        raw = sc.format_cal(self.table)
        self.assertNotIn("\n", raw)
        back = sc.parse_cal(raw)
        self.assertEqual(back, self.table)
        self.assertEqual(back[sc.cal_key(self.st)]["extraName"], "sdrplayLna")
        self.assertEqual(back[sc.cal_key(self.st)]["extraValue"], 4.0)

    def test_forget_clears_this_bands_entry_only(self):
        other = sc.calibrate(self.table, {**self.st, "band": "70cm"}, -50.0, -90.0)
        after = sc.forget(other, self.st)
        self.assertNotIn(sc.cal_key(self.st), after)
        self.assertIn(sc.cal_key({**self.st, "band": "70cm"}), after)


class Refusals(unittest.TestCase):
    def test_agc_refuses_with_a_sentence(self):
        with self.assertRaises(ValueError):
            sc.calibrate({}, rspdx(rxGainMode="slow_attack"), -42.6, -93.0)

    def test_between_bands_refuses(self):
        with self.assertRaises(ValueError):
            sc.calibrate({}, rspdx(band=""), -42.6, -93.0)

    def test_no_reading_refuses(self):
        with self.assertRaises(ValueError):
            sc.calibrate({}, rspdx(), None, -93.0)
        with self.assertRaises(ValueError):
            sc.calibrate({}, rspdx(), -199.5, -93.0)

    def test_near_clipping_refuses(self):
        with self.assertRaises(ValueError):
            sc.calibrate({}, rspdx(), -1.0, -93.0)


class SUnitEitherSideOf30MHz(unittest.TestCase):
    def test_s9_below_and_above_30_mhz(self):
        self.assertEqual(sc.s9_dbm(14e6), -73.0)
        self.assertEqual(sc.s9_dbm(144e6), -93.0)

    def test_s9_plus_12(self):
        s9 = sc.s9_dbm(145.65e6)
        self.assertEqual(sc.s_text(s9 + 12.0, s9), "S9+12")

    def test_s3_well_under_s9(self):
        s9 = sc.s9_dbm(14e6)
        self.assertEqual(sc.s_text(s9 - 6 * 6.0, s9), "S3")

    def test_exactly_s9(self):
        s9 = sc.s9_dbm(14e6)
        self.assertEqual(sc.s_text(s9, s9), "S9")


class Validation(unittest.TestCase):
    def test_dbm_accepts_a_plausible_number(self):
        self.assertEqual(sc.validate_dbm(-93), -93.0)
        self.assertEqual(sc.validate_dbm("-93.5"), -93.5)

    def test_dbm_refuses_nan_inf_and_out_of_range(self):
        for bad in (float("nan"), float("inf"), -1000.0, 1000.0, "banana", None):
            with self.assertRaises(ValueError):
                sc.validate_dbm(bad)

    def test_dbfs_accepts_a_number_with_no_range_check(self):
        self.assertEqual(sc.validate_dbfs(-199.9), -199.9)

    def test_dbfs_refuses_non_finite_and_non_numeric(self):
        for bad in (float("nan"), float("inf"), "banana", None):
            with self.assertRaises(ValueError):
                sc.validate_dbfs(bad)


class CleanCal(unittest.TestCase):
    def test_a_hand_edited_or_corrupt_setting_loses_its_calibrations_not_the_meter(self):
        self.assertEqual(sc.parse_cal("not json"), {})
        self.assertEqual(sc.parse_cal("[]"), {})
        self.assertEqual(sc.clean_cal({"k": {"offset": "nan", "gain": 1.0}}), {})
        self.assertEqual(sc.clean_cal({"k": {"offset": 1.0}}), {})          # no gain
        self.assertEqual(sc.clean_cal(None), {})

    def test_an_out_of_range_offset_is_dropped(self):
        self.assertEqual(sc.clean_cal({"k": {"offset": 9999.0, "gain": 1.0}}), {})

    def test_clean_cal_accepts_a_dict_or_its_own_json_string(self):
        d = {"k": {"offset": -1.0, "gain": 40.0, "when": "2026-10-23"}}
        self.assertEqual(sc.clean_cal(d), sc.clean_cal(sc.format_cal(d)))


class AverageDbfs(unittest.TestCase):
    def test_empty_history_is_none(self):
        self.assertIsNone(sc.average_dbfs([]))

    def test_power_mean_of_a_steady_level_is_itself(self):
        avg, spread = sc.average_dbfs([-80.0] * 10)
        self.assertAlmostEqual(avg, -80.0, places=6)
        self.assertEqual(spread, 0.0)

    def test_spread_is_half_the_range(self):
        _avg, spread = sc.average_dbfs([-80.0, -70.0])
        self.assertAlmostEqual(spread, 5.0, places=6)


if __name__ == "__main__":
    unittest.main()
