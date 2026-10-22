import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The Watch workspace keeps its share of the height with the Band view
showing (ohsnb/ui/opview.py): the over-the-beacon table at the view's top
is as tall as its rows, up to six and then scrolling, and hidden while
empty. It was six rows tall whatever it held, and that held the wide scope
to 52 % of the body at 1920 x 1080 instead of Watch's 66 % (WP1's note);
nor may a list arriving push the scopes' splitter."""
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase


def events(n, now):
    return [{"id": i, "kind": "overpower", "lo": 10_489_540_600.0 + i * 3_000, "hi": 10_489_542_100.0 + i * 3_000,
             "freq": 10_489_541_300.0 + i * 3_000, "width": 1_500.0, "excessDb": 9.0, "start": now - 40, "end": now,
             "active": True, "leila": False, "call": None} for i in range(n)]


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class WatchShare(WindowCase):
    def test_watch_keeps_two_thirds_with_or_without_the_list(self):
        win, bridge, radio = self.window()
        win.resize(1920, 1080)
        self.run_for(radio, 1.0)
        win.choose_workspace("watch")
        self.run_for(radio, 0.5)
        self.assertEqual(win.views.value, "skim")

        def share():
            s = win.split_main.sizes()
            return s[0] / sum(s)
        self.assertAlmostEqual(share(), 0.66, delta=0.02)
        table = win.op_panel.table
        self.assertFalse(table.isVisible())               # empty: the status line says so
        before = win.split_main.sizes()
        radio._publish("overpower", {"t": time.time(), "events": events(9, time.time())})
        self.assertTrue(self.run_for(radio, until=lambda: len(win.op_store.events) == 9, timeout=10))
        self.run_for(radio, 0.3)
        self.assertTrue(table.isVisible())
        self.assertEqual(table.rowCount(), 9)
        self.assertLess(table.height(), table.verticalHeader().defaultSectionSize() * 7)   # it scrolls
        self.assertEqual(win.split_main.sizes(), before)   # the scopes did not move
        # Two rows: no taller than they need.
        radio._publish("overpower", {"t": time.time(), "events": events(2, time.time())})
        self.assertTrue(self.run_for(radio, until=lambda: len(win.op_store.events) == 2, timeout=10))
        row = table.verticalHeader().defaultSectionSize()
        self.assertLessEqual(table.height(), table.horizontalHeader().height() + 2 * row + 6)


if __name__ == "__main__":
    unittest.main()
