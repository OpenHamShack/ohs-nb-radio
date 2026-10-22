"""Antenna labels (ohscore/antennas.py): the single-line stored form that
a Dock360 container setting must survive (one variable per line, so a
label with a line break would corrupt the line after it), round-tripped
through values an operator could plausibly type - a comma, an "=", and
non-ASCII characters - plus what a corrupt or hand-edited setting reads
back as."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import antennas


class RoundTrip(unittest.TestCase):
    def test_empty_round_trips_to_empty(self):
        self.assertEqual(antennas.format_labels({}), "")
        self.assertEqual(antennas.parse_labels(""), {})
        self.assertEqual(antennas.parse_labels(antennas.format_labels({})), {})

    def test_a_label_with_a_comma_and_an_equals_sign_round_trips(self):
        labels = {"Antenna A": "2 m, 70 cm = dual-band vertical"}
        stored = antennas.format_labels(labels)
        self.assertNotIn("\n", stored)
        self.assertEqual(antennas.parse_labels(stored), labels)

    def test_non_ascii_labels_round_trip_and_stay_readable(self):
        labels = {"Antenna A": "80 m dipôle", "Antenna B": "Логпериодика", "Antenna C": "HF — nøyaktig"}
        stored = antennas.format_labels(labels)
        self.assertNotIn("\n", stored)
        # Readable on disk, not escaped to \uXXXX (ensure_ascii=False):
        # a controller's operator or support log can read it directly.
        self.assertIn("Логпериодика", stored)
        self.assertEqual(antennas.parse_labels(stored), labels)

    def test_several_inputs_round_trip(self):
        labels = {"Antenna A": "2 m vertical", "Antenna B": "", "Antenna C": "80 m dipole"}
        stored = antennas.format_labels(labels)
        # An empty label is dropped, not stored as "": clearing one in the
        # table removes it rather than saving an empty string forever.
        self.assertEqual(antennas.parse_labels(stored), {"Antenna A": "2 m vertical", "Antenna C": "80 m dipole"})

    def test_a_label_with_an_embedded_newline_still_stores_as_one_line(self):
        # Typed by mistake (a paste), or from a future multi-line editor:
        # json.dumps escapes it, so the setting - one variable per line -
        # is never corrupted by it.
        labels = {"Antenna A": "80 m\ndipole"}
        stored = antennas.format_labels(labels)
        self.assertNotIn("\n", stored)
        self.assertEqual(antennas.parse_labels(stored), labels)


class Corrupt(unittest.TestCase):
    def test_garbage_reads_back_as_no_labels(self):
        self.assertEqual(antennas.parse_labels("not json at all {{{"), {})

    def test_a_json_list_is_not_a_label_map(self):
        self.assertEqual(antennas.parse_labels('["Antenna A", "Antenna B"]'), {})

    def test_a_non_string_value_is_dropped_not_crashed_on(self):
        self.assertEqual(antennas.parse_labels('{"Antenna A": 1, "Antenna B": "70 cm"}'), {"Antenna B": "70 cm"})

    def test_whitespace_only_is_empty(self):
        self.assertEqual(antennas.parse_labels("   "), {})


class DisplayName(unittest.TestCase):
    def test_unlabelled_shows_the_driver_name_alone(self):
        self.assertEqual(antennas.display_name("Antenna A", {}), "Antenna A")

    def test_labelled_shows_both(self):
        self.assertEqual(antennas.display_name("Antenna C", {"Antenna C": "80 m dipole"}),
                          "Antenna C — 80 m dipole")

    def test_a_label_for_a_different_input_is_not_used(self):
        self.assertEqual(antennas.display_name("Antenna B", {"Antenna C": "80 m dipole"}), "Antenna B")


if __name__ == "__main__":
    unittest.main()
