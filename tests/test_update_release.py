"""The update feed as tools/release.sh publishes it: signed after the .debs,
signed again when --windows adds the installer, never without a key the
apps trust, and always last in the upload.

Each test runs the real release.sh in a scratch repository
(test_site.make_repo), whose copy of ohscore/update.py trusts a release key
made for it by tools/update-feed.py keygen - as the release host's will.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Functions only: a TestCase class imported here would be run twice.
from test_site import (_git, commit, make_ham_repo, make_repo, release_env, run_ham_release, run_release,
                       scratch_key, stub_build_deb, stub_build_deb_both)


def feed(folder: Path) -> dict:
    return json.loads((folder / "update.json").read_text())


class ReleaseSignsTheFeed(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"
        self.incoming = self.root / "from-windows"
        self.incoming.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def verify(self) -> subprocess.CompletedProcess:
        """The folder checked as a client would, against the keys the
        scratch copy of ohscore trusts."""
        return subprocess.run([sys.executable, str(self.repo / "tools" / "update-feed.py"), "verify",
                               "--releases", str(self.releases)], env=release_env(self.repo, self.releases),
                              capture_output=True, text=True, timeout=60)

    def add_windows(self, ver: str) -> subprocess.CompletedProcess:
        exe = self.incoming / f"openhamshack-nb-{ver}-setup.exe"
        exe.write_bytes(f"MZ installer {ver}".encode())
        (self.incoming / f"{exe.name}.sha256").write_text(f"{hashlib.sha256(exe.read_bytes()).hexdigest()}  {exe.name}\n")
        return subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--windows", str(exe)], cwd=self.repo,
                              env=release_env(self.repo, self.releases), capture_output=True, text=True, timeout=120)

    def test_a_release_publishes_a_signed_feed_of_its_debs_and_says_to_upload_it_last(self) -> None:
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertEqual(res.returncode, 0, res.stderr)
        m = feed(self.releases)
        self.assertEqual(m["app"], "openhamshack-nb")
        self.assertEqual(sorted((f["arch"], f["url"]) for f in m["files"]),
                         [(a, f"openhamshack-nb_0.4.0_{a}.deb") for a in ("all", "amd64", "arm64")])
        for f in m["files"]:
            self.assertEqual(f["sha256"], hashlib.sha256((self.releases / f["url"]).read_bytes()).hexdigest())
        self.assertEqual(len((self.releases / "update.json.sig").read_bytes()), 64)
        # No "What's new" link: the folder it is served from has no pages.
        self.assertNotIn("notesUrl", m)
        check = self.verify()
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("update.json.sig and update.json - the feed always last", res.stdout)

    def test_windows_is_added_and_signed_again_and_kept_until_the_next_installer(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        first = feed(self.releases)["published"]
        res = self.add_windows("0.4.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        m = feed(self.releases)
        self.assertGreater(m["published"], first)
        win = [f for f in m["files"] if f["platform"] == "windows"]
        self.assertEqual([(f["version"], f["url"], f["kind"]) for f in win],
                         [("0.4.0", "openhamshack-nb-0.4.0-setup.exe", "exe")])
        self.assertEqual(self.verify().returncode, 0)
        # The next version's .debs go out a day before its installer:
        # Windows is still offered the installer that is on the site.
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        m = feed(self.releases)
        self.assertEqual({(f["platform"], f["version"]) for f in m["files"]},
                         {("linux", "0.5.0"), ("windows", "0.4.0")})
        self.assertEqual(self.verify().returncode, 0)
        # Its own installer replaces it, and the old one leaves the site and the feed together.
        res = self.add_windows("0.5.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        m = feed(self.releases)
        self.assertEqual({(f["platform"], f["version"]) for f in m["files"]},
                         {("linux", "0.5.0"), ("windows", "0.5.0")})
        self.assertFalse((self.releases / "openhamshack-nb-0.4.0-setup.exe").exists())
        self.assertEqual(self.verify().returncode, 0)

    def test_a_release_carries_on_from_an_earlier_one(self) -> None:
        # The release folder as an earlier release left it: openhamshack-nb
        # files, and a feed naming openhamshack-nb, which every copy reads.
        env = release_env(self.repo, self.releases)
        self.releases.mkdir()
        for name, data in (("openhamshack-nb_0.3.0_all.deb", b"old deb"), ("openhamshack-nb-0.3.0-setup.exe", b"MZ old")):
            (self.releases / name).write_bytes(data)
            (self.releases / f"{name}.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        subprocess.run([sys.executable, str(self.repo / "tools" / "update-feed.py"), "write", "--releases",
                        str(self.releases), "--version", "0.3.0"], env=env, check=True, capture_output=True)
        # The next release's .debs are openhamshack-nb's; Windows keeps the
        # old installer until its own arrives.
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertEqual(res.returncode, 0, res.stderr)
        m = feed(self.releases)
        self.assertEqual(m["app"], "openhamshack-nb")
        self.assertEqual({(f["platform"], f["url"]) for f in m["files"] if f["arch"] in ("all", "amd64")},
                         {("linux", "openhamshack-nb_0.4.0_all.deb"), ("linux", "openhamshack-nb_0.4.0_amd64.deb"),
                          ("windows", "openhamshack-nb-0.3.0-setup.exe")})
        # An older installed copy, checking the feed under this app's one
        # name, is offered the new package.
        from cryptography.hazmat.primitives import serialization
        from ohscore import update
        pub = serialization.load_pem_private_key(scratch_key(self.root).read_bytes(), None).public_key()
        keys = [("scratch", pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())]
        data, sig = (self.releases / "update.json").read_bytes(), (self.releases / "update.json.sig").read_bytes()
        old = update.read_manifest(data, sig, "openhamshack-nb", keys)
        offer = update.choose(old, "linux", "amd64", "0.3.0")
        self.assertEqual(offer.entry.url, "openhamshack-nb_0.4.0_amd64.deb")
        # The new installer retires the old one.
        res = self.add_windows("0.4.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([f["url"] for f in feed(self.releases)["files"] if f["platform"] == "windows"],
                         ["openhamshack-nb-0.4.0-setup.exe"])
        self.assertFalse((self.releases / "openhamshack-nb-0.3.0-setup.exe").exists())
        self.assertIn("openhamshack-nb-0.3.0-setup.exe", res.stdout)          # listed for removal from the site
        self.assertTrue((self.releases / "openhamshack-nb_0.3.0_all.deb").exists())   # older .debs stay
        self.assertEqual(self.verify().returncode, 0)

    def test_no_trusted_key_means_no_release_at_all(self) -> None:
        # The key is made and listed, then lost: release.sh stops before
        # the release commit, with nothing built or published.
        scratch_key(self.root).unlink()
        head = subprocess.run(_git(self.repo) + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("no release key", res.stderr)
        self.assertEqual(subprocess.run(_git(self.repo) + ["rev-parse", "HEAD"], capture_output=True,
                                        text=True).stdout, head)
        self.assertFalse(self.releases.exists() and any(self.releases.glob("*.deb")))

    def test_a_key_the_apps_do_not_list_is_refused_the_same_way(self) -> None:
        other = self.root / "other-key" / "ed25519.key"
        subprocess.run([sys.executable, str(self.repo / "tools" / "update-feed.py"), "keygen", "--key", str(other)],
                       check=True, capture_output=True)
        scratch_key(self.root).unlink()
        scratch_key(self.root).write_bytes(other.read_bytes())
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("is not in RELEASE_KEYS", res.stderr)
        self.assertFalse(self.releases.exists() and any(self.releases.glob("*.deb")))


class HamFeed(unittest.TestCase):
    def test_hams_feed_is_hams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_ham_repo(root)
            stub_build_deb_both(repo)
            commit(repo, "stub build-deb.sh", allow_empty=False)
            releases = root / "ham-releases"
            res = run_ham_release(repo, releases, "0.2.0")
            self.assertEqual(res.returncode, 0, res.stderr)
            m = feed(releases)
            self.assertEqual(m["app"], "openhamshack-radio")
            self.assertTrue(all(f["url"].startswith("openhamshack-radio_0.2.0_") for f in m["files"]))


if __name__ == "__main__":
    unittest.main()
