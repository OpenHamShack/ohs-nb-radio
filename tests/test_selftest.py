"""python3 -m ohscore.selftest: the check the store image runs on itself.
It must fail when a decoder the app offers is missing or will not start
(0.1.10-beta.1 shipped FT8 with no decoder and nothing said so), now in
the store form too for Q65 and JS8, and, where ohsdigi is built, prove FT8,
FT4, Q65 and JS8 decode rather than merely import."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import contextlib
import io
import unittest
from unittest import mock

from ohscore import host, modes_glue, selftest
from ohscore.modes import ft8, js8, q65


def run(app="ohsnb", store=False, *patches):
    """(exit status, {mode: row}) for one run of main(), output captured."""
    out = io.StringIO()
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(host, "STORE", store))
        for p in patches:
            st.enter_context(p)
        st.enter_context(contextlib.redirect_stdout(out))
        rc = selftest.main([app, "--json"])
    import json
    doc = json.loads(out.getvalue())
    return rc, {r["mode"]: r for r in doc["rows"]}


def _without(mode, why):
    """A registry lookup in which `mode` is unavailable for `why`."""
    real = modes_glue._entry

    def entry(name, freedv_mode="700d"):
        info, missing = real(name, freedv_mode)
        return (info, why) if name == mode else (info, missing)
    return mock.patch.object(modes_glue, "_entry", entry)


class Selftest(unittest.TestCase):
    def test_a_missing_decoder_the_app_offers_fails_the_check(self):
        rc, rows = run("ohsnb", True, _without("rtty", "no RTTY here"))
        self.assertEqual(rc, 1)
        self.assertFalse(rows["rtty"]["ok"])
        self.assertTrue(rows["rtty"]["required"])
        self.assertEqual(rows["rtty"]["why"], "no RTTY here")

    def test_a_decoder_that_will_not_start_fails_the_check(self):
        real = modes_glue.decoder
        refuse = mock.patch.object(modes_glue, "decoder",
                                   lambda name, emit, **kw: None if name == "psk31" else real(name, emit, **kw))
        rc, rows = run("ohsnb", True, refuse)
        self.assertEqual(rc, 1)
        self.assertIn("did not start", rows["psk31"]["why"])

    def test_q65_is_required_in_the_store_form_now_ohsdigi_decodes_it(self):
        _rc, rows = run("ohsnb", True, _without("q65", "no decoder"))
        self.assertTrue(rows["q65"]["required"])
        self.assertFalse(rows["q65"]["ok"])

    @unittest.skipUnless(q65._OHSDIGI_Q65 is not None, "ohsdigi without Q65 (tools/build-ohsdigi.sh --host --install)")
    def test_q65_decodes_a_period_through_ohsdigi(self):
        self.assertEqual(selftest._decodes_q65(), "")
        rc, rows = run("ohsnb", True, mock.patch.object(q65, "_OHSDIGI_Q65", None))
        self.assertEqual(rc, 1)
        self.assertIn("no Q65 decoder", rows["q65"]["why"])

    def test_js8_is_required_in_the_store_form_now_ohsdigi_decodes_it(self):
        _rc, rows = run("ohsnb", True, _without("js8", "no decoder"))
        self.assertTrue(rows["js8"]["required"])
        self.assertFalse(rows["js8"]["ok"])

    @unittest.skipUnless(js8._OHSDIGI_JS8 is not None, "ohsdigi without JS8 (tools/build-ohsdigi.sh --host --install)")
    def test_js8_decodes_a_period_through_ohsdigi(self):
        self.assertEqual(selftest._decodes_js8(), "")
        rc, rows = run("ohsnb", True, mock.patch.object(js8, "_OHSDIGI_JS8", None))
        self.assertEqual(rc, 1)
        self.assertIn("no JS8 decoder", rows["js8"]["why"])

    def test_without_ohsdigi_ft8_fails_the_store_check(self):
        """The 0.1.10-beta.1 image exactly: no ohsdigi, no jt9."""
        no_ohsdigi = mock.patch.object(ft8, "_OHSDIGI_DEC", None)
        rc, rows = run("ohsnb", True, no_ohsdigi)
        self.assertEqual(rc, 1)
        self.assertFalse(rows["ft8"]["ok"])
        self.assertFalse(rows["ft4"]["ok"])

    def test_radio_offers_js8_but_neither_q65_nor_hsmodem(self):
        _rc, rows = run("ohsradio", True)
        self.assertIn("ft8", rows)
        self.assertIn("js8", rows)
        self.assertNotIn("q65", rows)
        self.assertNotIn("hsmodem", rows)

    @unittest.skipUnless(ft8._OHSDIGI_DEC is not None, "ohsdigi not built (tools/build-ohsdigi.sh --host --install)")
    def test_ft8_and_ft4_decode_a_slot_through_ohsdigi(self):
        for variant in ("ft8", "ft4"):
            self.assertEqual(selftest._decodes_slot(variant), "", variant)


if __name__ == "__main__":
    unittest.main()
