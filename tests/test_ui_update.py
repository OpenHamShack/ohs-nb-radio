"""Self-update in the window (ohscore/ui/update.py), against a real window
and Radio on Qt's offscreen platform and a release folder signed by
tools/update-feed.py with a test key, served over local HTTP: the banner,
Help › Check for updates…, when checks happen, and Install and restart
through to the command - which a stand-in records instead of running.
Nothing here reaches the real site, and nothing is installed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_ui_window import HAVE_QT, WindowCase
# Functions only: a TestCase class imported here would be run twice.
from test_update import HAVE_CRYPTO, Served, closed_port_url, key_file, new_key, write_release

GOOD_SIGNER = ("Valid", "CN=360 Technology, O=360 Technology, L=Example, C=GB")


@unittest.skipUnless(HAVE_QT and HAVE_CRYPTO, "PyQt6 or python3-cryptography is not installed")
class UpdateInTheWindow(WindowCase):
    def setUp(self):
        super().setUp()
        self.rtmp = tempfile.TemporaryDirectory()
        root = Path(self.rtmp.name)
        self.k, self.keys = new_key()
        self.keyfile = key_file(self.k, root / "key" / "ed25519.key")
        self.rel = root / "rel"
        self.deb = b"a new openhamshack-nb " * 2000
        self.exe = b"MZ a new installer " * 2000
        res = write_release(self.rel, self.keyfile, "0.2.0",
                            {"openhamshack-nb_0.2.0_amd64.deb": self.deb, "openhamshack-nb_0.2.0_all.deb": self.deb + b"!",
                             "openhamshack-nb-0.2.0-setup.exe": self.exe}, "--notes-url", "index.html#notes")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.server = Served(self.rel)
        self.ran: list[list[str]] = []
        self.after_exit: list[list[str]] = []
        self.rc = 0

    def tearDown(self):
        self.server.close()
        self.rtmp.cleanup()
        super().tearDown()

    def updater(self, win, **kw):
        """The window's controller, pointed at the test feed, with the
        installer run and the after-exit start recorded, not done."""
        from ohscore import update
        from ohscore.ui.update import UpdateController
        args = dict(feed_url=self.server.url + "update.json", keys=self.keys, plat="linux", arch="amd64",
                    kind="deb", version="0.1.8", pkexec="/usr/bin/pkexec",
                    runner=lambda argv: (self.ran.append(argv), (self.rc, ""))[1],
                    at_exit=self.after_exit.append, authenticode=lambda p: GOOD_SIGNER)
        args.update(kw)
        win.updates = UpdateController(win, **args)
        # Each test its own record of the newest manifest seen. The window's
        # is update-seen.json beside the config, which scratch_home shares
        # with every test in the run, while every test signs a feed of its
        # own: one that re-signs within a second moves its stamp a second
        # ahead (update-feed.py), and the next test's fresh feed, stamped
        # with the real time, was then refused as a replay. On the Mac mini,
        # fast enough to fit both into a second, test_a_new_version_shows_
        # the_banner failed so in the build's full suite (17/10/2026,
        # "refused" != "available") and passed alone.
        win.updates.seen = update.Seen(Path(self.rtmp.name) / "update-seen.json")
        win.updates.attach(win.update_banner)
        return win.updates

    def wait(self, cond, timeout=20.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def checked(self, c, manual=False):
        self.assertTrue(c.check(manual=manual))
        self.assertTrue(self.wait(lambda: not c.checking))
        return c.result

    def busy(self, radio, **what):
        real = radio.state
        return mock.patch.object(radio, "state", lambda: {**real(), **what})

    # ------------------------------------------------------------ the banner
    def test_a_new_version_shows_the_banner(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.assertFalse(win.update_banner.isVisible())
        self.assertEqual(self.checked(c).status, "available")
        s = c.banner_state()
        self.assertEqual(s["text"], "OpenHamShack QO-100 NB 0.2.0 is available")
        self.assertEqual(s["primary"], "Install and restart")
        self.assertTrue(s["notes"])
        self.assertTrue(win.update_banner.isVisible())
        self.assertEqual(win.update_banner.label.text(), "OpenHamShack QO-100 NB 0.2.0 is available")
        self.assertTrue(win.update_banner.btn_later.isVisible())
        self.assertTrue(win.update_banner.btn_notes.isVisible())

    def test_later_hides_it_until_a_check_by_hand(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.checked(c)
        win.update_banner.btn_later.clicked.emit()
        self.assertFalse(win.update_banner.isVisible())
        self.checked(c)                                   # the daily check: still hidden
        self.assertFalse(win.update_banner.isVisible())
        self.checked(c, manual=True)                      # asked for: shown again
        self.assertTrue(win.update_banner.isVisible())

    def test_whats_new_opens_the_sites_release_notes(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        opened = []
        c.open_url = opened.append
        self.checked(c)
        win.update_banner.btn_notes.clicked.emit()
        self.assertEqual(opened, [self.server.url + "index.html#notes"])

    def test_the_banner_survives_a_theme_change(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.checked(c)
        win.set_theme("light")
        self.assertTrue(self.wait(lambda: win.update_banner.isVisible()))
        self.assertEqual(win.update_banner.label.text(), "OpenHamShack QO-100 NB 0.2.0 is available")

    # ------------------------------------------------------------ failures stay quiet
    def test_offline_shows_nothing_but_help_says_why(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win, feed_url=closed_port_url())
        self.assertEqual(self.checked(c).status, "offline")
        self.assertFalse(win.update_banner.isVisible())
        from ohscore.ui.status import Toast
        self.assertEqual(win.toasts.findChildren(Toast), [])         # no toast either
        self.assertIn("Could not check", c.status_text())
        self.assertIn("could not be reached", c.status_text())

    def test_a_tampered_feed_offers_nothing_and_help_says_it_was_refused(self):
        win, _bridge, _radio = self.window()
        data = (self.rel / "update.json").read_bytes()
        (self.rel / "update.json").write_bytes(data.replace(b"0.2.0_amd64", b"0.2.0_arm64"))
        c = self.updater(win)
        self.assertEqual(self.checked(c).status, "refused")
        self.assertFalse(win.update_banner.isVisible())
        self.assertIn("refused, because it could not be proved genuine", c.status_text())

    def test_help_check_for_updates_checks_and_reports(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        act = next(a for m in win.menuBar().actions() if m.text() == "&Help" for a in m.menu().actions()
                   if a.text() == "Check for updates…")
        act.trigger()
        self.assertIsNotNone(c.dialog)
        self.assertTrue(self.wait(lambda: not c.checking))
        self.assertIn("OpenHamShack QO-100 NB 0.2.0 is available", c.dialog.status.text())
        self.assertIn("Test notes", c.dialog.status.text())
        self.assertTrue(c.dialog.btn_install.isVisible())
        c.dialog.close()

    # ------------------------------------------------------------ when
    def test_the_schedule_checks_once_then_daily_and_never_with_the_setting_off(self):
        win, bridge, radio = self.window()
        now = [1_000_000.0]
        c = self.updater(win, clock=lambda: now[0])
        c.tick()
        self.assertTrue(self.wait(lambda: not c.checking))
        self.assertEqual(len(self.server.requests), 2)      # the manifest and its signature
        c.tick()
        now[0] += 3600
        c.tick()
        self.assertEqual(len(self.server.requests), 2)
        now[0] += 24 * 3600
        bridge.set(checkUpdates=False)
        self.assertTrue(self.wait(lambda: bridge.st.get("checkUpdates") is False))
        c.tick()
        self.assertFalse(c.checking)
        self.assertEqual(len(self.server.requests), 2)
        bridge.set(checkUpdates=True)
        self.assertTrue(self.wait(lambda: bridge.st.get("checkUpdates") is True))
        c.tick()
        self.assertTrue(self.wait(lambda: not c.checking))
        self.assertEqual(len(self.server.requests), 4)

    def test_no_automatic_check_while_transmitting_or_recording(self):
        win, _bridge, radio = self.window()
        c = self.updater(win)
        for what in ({"keyed": True}, {"recording": True}):
            with self.busy(radio, **what):
                c.tick()
            self.assertFalse(c.checking)
            self.assertEqual(self.server.requests, [])
        c.tick()                                            # the over ended: now it is done
        self.assertTrue(self.wait(lambda: not c.checking))
        self.assertEqual(len(self.server.requests), 2)

    def test_a_copy_run_from_source_never_checks_by_itself(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win, kind="")
        c.start()
        self.assertIsNone(c.timer)
        # The window a test or a tool builds has not been started either.
        self.assertIsNone(self.window()[0].updates.timer)

    # ------------------------------------------------------------ installing (Linux)
    def test_install_downloads_proves_and_runs_pkexec_apt_then_offers_a_restart(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.checked(c)
        win.update_banner.btn_primary.clicked.emit()
        self.assertTrue(self.wait(lambda: c.phase == "installed"))
        path = Path(self.ran[0][-1])
        self.assertEqual(self.ran, [["/usr/bin/pkexec", "apt-get", "install", "-y", str(path)]])
        self.assertEqual(path.read_bytes(), self.deb)       # the amd64 package, proved
        self.assertEqual(c.banner_state()["primary"], "Restart now")
        self.assertIn("is installed", win.update_banner.label.text())
        with mock.patch("ohscore.update.relaunch_command", lambda pkg: [f"/usr/bin/{pkg}"]):
            win.update_banner.btn_primary.clicked.emit()
        self.assertEqual(self.after_exit, [["/usr/bin/openhamshack-nb"]])
        self.assertFalse(win.isVisible())                   # closed the normal way: unkeyed, saved

    def test_never_installs_or_restarts_while_transmitting_or_recording(self):
        win, _bridge, radio = self.window()
        c = self.updater(win)
        self.checked(c)
        for what, word in (({"keyed": True}, "transmitting"), ({"recording": True}, "recording")):
            with self.busy(radio, **what):
                c._render()
                self.assertIn(f"Not while {word}", c.banner_state()["blocked"])
                self.assertFalse(win.update_banner.btn_primary.isEnabled())
                c.install()
                self.assertEqual(c.phase, "offer")
        self.assertEqual(self.ran, [])
        # A download that finishes mid-over waits for another click.
        c.install()
        with self.busy(radio, keyed=True):
            self.assertTrue(self.wait(lambda: c.phase == "ready"))
            self.app.processEvents()
            self.assertEqual(self.ran, [])
            self.assertIn("when you have finished transmitting", c.banner_state()["text"])
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "installed"))
        with self.busy(radio, keyed=True):
            c.restart()
        self.assertEqual(self.after_exit, [])
        self.assertTrue(win.isVisible())

    def test_without_pkexec_the_banner_gives_the_command(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win, pkexec="")
        self.checked(c)
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "failed"))
        self.assertEqual(self.ran, [])
        self.assertRegex(win.update_banner.label.text(), r"sudo apt-get install -y \S*openhamshack-nb_0\.2\.0_amd64\.deb")

    def test_a_cancelled_password_prompt_installs_nothing_and_can_be_tried_again(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.checked(c)
        self.rc = 126
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "ready" and self.ran))
        self.assertIn("password prompt was closed", c.banner_state()["text"])
        self.rc = 0
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "installed"))
        self.assertEqual(len(self.ran), 2)

    def test_a_download_that_is_not_the_signed_file_is_never_installed(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win)
        self.checked(c)
        (self.rel / "openhamshack-nb_0.2.0_amd64.deb").write_bytes(self.deb[:-1] + b"?")
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "failed"))
        self.assertIn("does not match the signed manifest", c.message)
        self.assertEqual(self.ran, [])

    # ------------------------------------------------------------ installing (Windows)
    def test_windows_checks_the_signer_then_runs_the_installer_after_exit(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win, plat="windows", kind="exe")
        self.checked(c)
        c.install()
        self.assertTrue(self.wait(lambda: bool(self.after_exit)))
        argv = self.after_exit[0]
        self.assertEqual(Path(argv[0]).read_bytes(), self.exe)
        self.assertEqual(argv[1:], ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/MERGETASKS=!plutodrivers",
                                    "/RELAUNCH=1"])
        self.assertEqual(self.ran, [])                     # nothing run while this process lives
        self.assertFalse(win.isVisible())

    def test_windows_refuses_an_installer_signed_by_anyone_else(self):
        win, _bridge, _radio = self.window()
        c = self.updater(win, plat="windows", kind="exe", authenticode=lambda p: ("Valid", "CN=Mallory, O=Mallory"))
        self.checked(c)
        c.install()
        self.assertTrue(self.wait(lambda: c.phase == "failed"))
        self.assertIn("not 360 Technology", c.message)
        self.assertEqual(self.after_exit, [])
        self.assertTrue(win.isVisible())

    # ------------------------------------------------------------ a Mac: downloaded, proved, opened
    def test_a_mac_downloads_proves_and_opens_the_dmg_and_installs_nothing_itself(self):
        dmg = b"a new openhamshack-nb disk image " * 2000
        res = write_release(self.rel, self.keyfile, "0.2.0", {"openhamshack-nb-0.2.0-arm64.dmg": dmg})
        self.assertEqual(res.returncode, 0, res.stderr)
        win, _bridge, _radio = self.window()
        c = self.updater(win, plat="macos", arch="arm64", kind="dmg")
        self.checked(c)
        self.assertEqual(c.banner_state()["primary"], "Download")     # never "Install and restart"
        c._primary()
        self.assertTrue(self.wait(lambda: c.phase == "opened"))
        self.assertEqual(len(self.ran), 1)
        opener, path = self.ran[0]
        self.assertEqual(opener, "/usr/bin/open")
        self.assertEqual(Path(path).read_bytes(), dmg)
        self.assertEqual(self.after_exit, [])                  # nothing replaced, nothing restarted
        self.assertTrue(win.isVisible())
        s = c.banner_state()
        self.assertIn("drag the new one onto Applications", s["text"])
        c._primary()                                           # its Finder window was closed: again
        self.assertEqual(len(self.ran), 2)


if __name__ == "__main__":
    unittest.main()
