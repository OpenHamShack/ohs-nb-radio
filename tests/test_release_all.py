"""tools/release-all.sh, the one-command NB/Radio release, and the parts of
it that can run without the build machines: release.sh's new steps
(--commit-only, a suite proved by the caller, RELEASE_NO_FEED,
--macos-release), feed.py writing a feed from the live one, and the
orchestrator itself - argument handling, the removal report and its
"yes", the gate that stops publishing when a platform fails, and the one
notification - with the platform drivers replaced by stand-ins.

Everything runs in scratch repositories (test_site.make_repo) with a
scratch "hub" beside them; nothing reaches a real host, folder or key.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ohscore import update
from test_site import (_git, commit, head, make_ham_repo, release_env, scratch_key, stub_build_deb_both,
                       touch_commit)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(_git(repo) + list(args), capture_output=True, text=True, check=True).stdout.strip()


def release_sh(repo: Path, releases: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    e = release_env(repo, releases)
    e.update(env)
    return subprocess.run(["bash", str(repo / "tools" / "release.sh"), *args], cwd=repo, env=e,
                          capture_output=True, text=True, timeout=180)


class Scratch(unittest.TestCase):
    """A scratch repository of both apps with a passing suite, its last
    releases NB 0.1.0 and HAM 0.1.0, and a stand-in build-deb.sh."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        stub_build_deb_both(self.repo)
        commit(self.repo, "stub build-deb.sh", allow_empty=False)
        commit(self.repo, "Release 0.1.0")
        commit(self.repo, "Release HAM 0.1.0")
        self.releases = self.root / "releases"

    def tearDown(self) -> None:
        self.tmp.cleanup()


class ReleaseShForReleaseAll(Scratch):
    def test_commit_only_makes_the_release_commit_and_the_build_then_uses_it(self) -> None:
        # No release folder, no key: --commit-only needs neither.
        res = release_sh(self.repo, self.root / "nowhere" / "releases", "0.2.0", "--commit-only",
                         OHS_RELEASE_KEY=str(self.root / "no-key"), OPENHAMSHACK_RELEASE_KEY=str(self.root / "no-key"))
        self.assertEqual(res.returncode, 0, res.stderr)
        made = head(self.repo)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Release 0.2.0")
        self.assertEqual((self.repo / "ohsnb" / "VERSION").read_text().strip(), "0.2.0")
        self.assertFalse((self.root / "nowhere").exists())
        res = release_sh(self.repo, self.releases, "nb", "0.2.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("already \"Release 0.2.0\"", res.stdout)
        self.assertEqual(head(self.repo), made)                       # no second commit
        self.assertTrue((self.releases / "openhamshack-nb_0.2.0_amd64.deb").is_file())

    def test_a_suite_proved_on_this_tree_is_not_run_again_but_one_proved_on_another_is(self) -> None:
        (self.repo / "tests" / "test_red.py").write_text(
            "import unittest\nclass Red(unittest.TestCase):\n    def test_red(self):\n        self.fail('red')\n")
        commit(self.repo, "a red test", allow_empty=False)
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        res = release_sh(self.repo, self.releases, "0.2.0", "--commit-only")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("tests fail", res.stderr)
        res = release_sh(self.repo, self.releases, "0.2.0", "--commit-only", RELEASE_SUITE_PROVED=tree)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not run again", res.stdout)
        # Radio's commit on top differs from the proved tree in ohsnb/VERSION
        # only: still proved. A tree that differs in code is not.
        res = release_sh(self.repo, self.releases, "ham", "0.2.0", "--commit-only", RELEASE_SUITE_PROVED=tree)
        self.assertEqual(res.returncode, 0, res.stderr)
        touch_commit(self.repo, "ohscore/changed.py", "code after the suite ran")
        res = release_sh(self.repo, self.releases, "0.3.0", "--commit-only", RELEASE_SUITE_PROVED=tree)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ohscore/changed.py", res.stderr)
        self.assertIn("tests fail", res.stderr)

    def test_no_feed_leaves_update_json_alone(self) -> None:
        res = release_sh(self.repo, self.releases, "0.2.0", RELEASE_NO_FEED="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.releases / "openhamshack-nb_0.2.0_all.deb").is_file())
        self.assertFalse((self.releases / "update.json").exists())

    def dmg(self, name: str) -> Path:
        d = self.root / "from-mac"
        d.mkdir(exist_ok=True)
        (d / name).write_bytes(f"koly {name}".encode())
        (d / f"{name}.sha256").write_text(f"{hashlib.sha256((d / name).read_bytes()).hexdigest()}  {name}\n")
        return d / name

    def test_macos_release_puts_a_release_image_in_the_feed_and_archives_the_older(self) -> None:
        self.assertEqual(release_sh(self.repo, self.releases, "0.2.0").returncode, 0)
        rc = head(self.repo)
        old = self.dmg("openhamshack-nb-0.1.0-mac-preview.1-arm64.dmg")
        shutil.copy2(old, self.releases)
        shutil.copy2(f"{old}.sha256", self.releases)
        wrong = self.dmg("openhamshack-nb-0.1.9-arm64.dmg")
        res = release_sh(self.repo, self.releases, "--macos-release", str(wrong), "--commit", rc)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("is not openhamshack-nb-0.2.0-arm64.dmg", res.stderr)
        res = release_sh(self.repo, self.releases, "--macos-release", str(self.dmg("openhamshack-nb-0.2.0-arm64.dmg")),
                         "--commit", git(self.repo, "rev-parse", "HEAD~1"))
        self.assertNotEqual(res.returncode, 0)                       # not the release commit
        res = release_sh(self.repo, self.releases, "--macos-release",
                         str(self.dmg("openhamshack-nb-0.2.0-arm64.dmg")), "--commit", rc)
        self.assertEqual(res.returncode, 0, res.stderr)
        feed = json.loads((self.releases / "update.json").read_text())
        mac = [e for e in feed["files"] if e["platform"] == "macos"]
        self.assertEqual([(e["version"], e["url"]) for e in mac], [("0.2.0", "openhamshack-nb-0.2.0-arm64.dmg")])
        self.assertFalse((self.releases / old.name).exists())
        self.assertIn(f"remove from the remote site:\n  {old.name}\n", res.stdout)
        manifests = list((self.root / "source-site").rglob("*macos*"))
        self.assertTrue(manifests, "no macOS source project on the source site")


def load_feed_tool(repo: Path):
    spec = importlib.util.spec_from_file_location("update_feed", repo / "tools" / "update-feed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FeedFromTheLiveFeed(Scratch):
    """feed.py: the folder's feed may be stale; the live one decides."""

    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(release_sh(self.repo, self.releases, "0.2.0").returncode, 0)
        self.live = self.root / "live"
        self.live.mkdir()
        # Live has a Windows installer the release folder's feed never
        # named (it was put back by hand), and was published later.
        exe = "openhamshack-nb-0.2.0-setup.exe"
        (self.releases / exe).write_bytes(b"MZ 0.2.0")
        (self.releases / f"{exe}.sha256").write_text(f"{hashlib.sha256(b'MZ 0.2.0').hexdigest()}  {exe}\n")
        self.stale = (self.releases / "update.json").read_bytes()
        self.sign_live(self.with_windows(json.loads(self.stale), exe), hours=2)

    def with_windows(self, doc: dict, exe: str) -> dict:
        data = (self.releases / exe).read_bytes()
        doc["files"].append({"platform": "windows", "arch": "amd64", "kind": update.KINDS["windows"], "version": "0.2.0",
                             "url": exe, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "date": "2026-10-01", "notes": ""})
        return doc

    def sign_live(self, doc: dict, hours: int) -> None:
        stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(hours=hours)
        doc["published"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = (json.dumps(doc, indent=2) + "\n").encode()
        tool = load_feed_tool(self.repo)
        (self.live / "update.json").write_bytes(data)
        (self.live / "update.json.sig").write_bytes(tool.load_key(scratch_key(self.root)).sign(data))
        self.live_doc = doc

    def feed(self, version: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.repo / "tools" / "release-all" / "feed.py"), "--app", "nb",
                               "--version", version, "--releases", str(self.releases),
                               "--live-url", (self.live / "update.json").as_uri(), "--out", str(self.root / "out"),
                               *extra], env=release_env(self.repo, self.releases),
                              capture_output=True, text=True, timeout=120)

    def test_a_linux_release_keeps_the_live_windows_entry_and_publishes_after_the_live_feed(self) -> None:
        self.assertEqual(release_sh(self.repo, self.releases, "0.2.1", RELEASE_NO_FEED="1").returncode, 0)
        self.assertEqual((self.releases / "update.json").read_bytes(), self.stale)   # still the stale one
        res = self.feed("0.2.1", "--platforms", "linux")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("not the live feed; writing from the live one", res.stdout)
        new = json.loads((self.releases / "update.json").read_text())
        self.assertGreater(new["published"], self.live_doc["published"])          # the live one is 2 h ahead
        slots = {(e["platform"], e["arch"]): e["version"] for e in new["files"]}
        self.assertEqual(slots, {("linux", "amd64"): "0.2.1", ("linux", "arm64"): "0.2.1", ("linux", "all"): "0.2.1",
                                 ("windows", "amd64"): "0.2.0"})

    def test_it_refuses_a_feed_that_would_lose_a_platform_the_live_one_offers(self) -> None:
        self.assertEqual(release_sh(self.repo, self.releases, "0.2.1", RELEASE_NO_FEED="1").returncode, 0)
        (self.releases / "openhamshack-nb-0.2.0-setup.exe").unlink()     # the installer live names is gone
        res = self.feed("0.2.1", "--platforms", "linux")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("windows/amd64 is not left as the live feed has it", res.stderr)

    def test_a_rehearsal_signs_a_copy_with_a_throwaway_key_and_takes_a_label(self) -> None:
        self.assertEqual(release_sh(self.repo, self.releases, "0.2.1+rc0", RELEASE_NO_FEED="1").returncode, 0)
        before = (self.releases / "update.json").read_bytes()
        res = self.feed("0.2.1+rc0", "--platforms", "linux,windows", "--rehearsal")
        # Windows was "released" but no 0.2.1 installer exists: refused.
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("windows/amd64 offers nothing, not 0.2.1", res.stderr)
        res = self.feed("0.2.1+rc0", "--platforms", "linux", "--rehearsal")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual((self.releases / "update.json").read_bytes(), before)    # the folder untouched
        new = json.loads((self.root / "out" / "update.json").read_text())
        self.assertNotEqual(new["key"], self.live_doc.get("key") or json.loads(before)["key"])
        self.assertEqual({e["version"] for e in new["files"] if e["platform"] == "linux"}, {"0.2.1"})


STUB_DRIVER = r"""#!/bin/bash
# A stand-in for one of release-all.sh's stage drivers.
name=$(basename "$0" .sh)
echo "$name $(grep -E '^(DRY|PLATFORMS)=' "$1/run.env" | tr '\n' ' ')" >> "$FAKE_CALLS"
echo "== step $name: first"
if [[ ${FAKE_PUSH_MAIN:-} == "$name" ]]; then
    d=$(mktemp -d); git clone -q -b main "$FAKE_HUB" "$d/c"
    git -C "$d/c" -c user.name=o -c user.email=o@example.invalid commit -q --allow-empty -m "another session"
    git -C "$d/c" push -q origin HEAD:main
fi
if [[ ${FAKE_FAIL:-} == "$name" ]]; then echo "== step $name: notarise"; echo "Apple said no" >&2; exit 1; fi
echo "$name: PASS"
"""


class ReleaseAll(Scratch):
    def setUp(self) -> None:
        super().setUp()
        for a, v in (("nb", "0.1.1"), ("ham", "0.1.1")):
            touch_commit(self.repo, f"docs/release-notes/{a}-{v}.txt", f"{a} {v} notes")
        self.hub = self.root / "hub.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.hub)], check=True)
        git(self.repo, "remote", "add", "hub", str(self.hub))
        git(self.repo, "push", "-q", "hub", "HEAD:refs/heads/main")
        git(self.repo, "fetch", "-q", "hub")
        self.drivers = self.root / "drivers"
        self.drivers.mkdir()
        for d in ("linux", "windows", "macos", "promote", "site"):
            (self.drivers / f"{d}.sh").write_text(STUB_DRIVER)
            (self.drivers / f"{d}.sh").chmod(0o755)
        self.calls = self.root / "calls"
        self.notes = self.root / "notifications"
        (self.root / "notify").write_text(f'#!/bin/bash\necho "$*" >> {self.notes}\n')
        (self.root / "notify").chmod(0o755)
        self.conf = self.root / "nb-release.conf"
        self.conf.write_text(f"NOTIFY={self.root / 'notify'}\nRELEASE_HOST=release-host\n")

    def run_all(self, *args: str, stdin: str = "", **env: str) -> subprocess.CompletedProcess:
        e = release_env(self.repo, self.releases)
        e.update(RA_CONF=str(self.conf), RA_TOOLS=str(self.drivers), RA_ROOT=str(self.root / "runs"),
                 RA_TREE=str(self.root / "tree"), SUITE_TMP_ROOT=str(self.root / "suite-tmp"),
                 FAKE_CALLS=str(self.calls), FAKE_HUB=str(self.hub), **env)
        return subprocess.run(["bash", str(self.repo / "tools" / "release-all.sh"), *args], cwd=self.repo, env=e,
                              input=stdin, capture_output=True, text=True, timeout=300)

    def called(self) -> list[str]:
        return [ln.split()[0] for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def notifications(self) -> list[str]:
        return self.notes.read_text().splitlines() if self.notes.exists() else []

    def hub_main(self) -> str:
        return subprocess.run(["git", "-C", str(self.hub), "rev-parse", "main"], capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_arguments(self) -> None:
        for args, said in ((("xb=0.1.1",), "unknown argument"),
                           (("nb=0.1.1-rc0", "--dry-run"), "is written 0.1.1+rc0"),
                           (("nb=0.1.1+rc0",), "only a --dry-run may use a +label"),
                           (("nb=0.1.1", "--platforms", "linux,bsd"), "bsd is not"),
                           (("nb=0.1.1", "nb=0.1.2"), "named twice"),
                           (("nb", "ham"), "no version"),
                           (("nb=0.1.1", "--base", "feature/x"), "from hub/main only")):
            res = self.run_all(*args)
            self.assertEqual(res.returncode, 2, (args, res.stderr))
            self.assertIn(said, res.stderr, args)
        self.assertEqual(self.called(), [])
        self.assertEqual(self.notifications(), [])

    def test_it_lists_what_the_release_removes_and_stops_without_a_yes(self) -> None:
        git(self.repo, "rm", "-q", "tests/test_ok.py")
        (self.repo / "tests").mkdir(exist_ok=True)
        (self.repo / "tests" / "test_kept.py").write_text("import unittest\n")
        commit(self.repo, "drop a test", allow_empty=False)
        git(self.repo, "push", "-q", "hub", "HEAD:main")
        res = self.run_all("nb", "ham", "--version", "0.1.1", stdin="no\n")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("QO-100-NB 0.1.1 against 0.1.0", res.stdout)
        self.assertIn("Radio 0.1.1 against 0.1.0", res.stdout)
        self.assertIn("DELETED  tests/test_ok.py", res.stdout)
        self.assertIn("Type yes", res.stdout)
        self.assertEqual(self.called(), [])
        self.assertEqual(self.notifications(), [])                    # whoever said no is there

    def test_a_version_that_is_not_newer_is_refused(self) -> None:
        res = self.run_all("nb=0.1.0", "--yes")
        self.assertEqual(res.returncode, 1)
        self.assertIn("is not newer than its last release, 0.1.0", res.stderr)
        self.assertEqual(self.called(), [])

    def test_a_failed_platform_publishes_nothing_and_says_which_step(self) -> None:
        before = self.hub_main()
        res = self.run_all("nb=0.1.1", "ham=0.1.1", "--yes", FAKE_FAIL="macos")
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertEqual(sorted(self.called()), ["linux", "macos", "windows"])   # promote and site never ran
        self.assertEqual(self.hub_main(), before)
        notes = self.notifications()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("FAILED at build: macos (macos: notarise)", notes[0])
        run = next((self.root / "runs").glob("*nb-0.1.1_ham-0.1.1"))
        self.assertTrue((run / "macos.status").read_text().startswith("FAIL"))
        self.assertTrue((run / "macos.end").is_file())               # its own time, not the slowest's
        self.assertTrue((run / "windows.status").read_text().startswith("PASS"))

    def test_a_dry_run_rehearses_everything_and_leaves_the_hub_alone(self) -> None:
        before = self.hub_main()
        res = self.run_all("nb=0.1.1+rc0", "ham=0.1.1+rc0", "--dry-run", "--yes", "--platforms", "windows,linux")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        calls = self.called()
        self.assertEqual((sorted(calls[:2]), calls[2:]), (["linux", "windows"], ["promote", "site"]))
        self.assertTrue(all("DRY=1" in ln for ln in self.calls.read_text().splitlines()))
        self.assertEqual(self.hub_main(), before)
        tree = self.root / "tree"
        self.assertEqual(git(tree, "log", "-2", "--format=%s").splitlines(),
                         ["Release HAM 0.1.1+rc0", "Release 0.1.1+rc0"])
        env = next((self.root / "runs").glob("*-dry")) / "run.env"
        self.assertIn(f"COMMIT_nb={git(tree, 'rev-parse', 'HEAD~1')}", env.read_text())
        notes = self.notifications()
        self.assertEqual(len(notes), 1)
        self.assertIn("dry run PASSED, nothing published", notes[0])
        self.assertIn("timings (seconds):", res.stdout)

    def test_a_real_run_fast_forwards_main_first_and_stops_if_main_moved(self) -> None:
        res = self.run_all("nb=0.1.1", "--yes", FAKE_PUSH_MAIN="windows")
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertNotIn("promote", self.called())
        self.assertIn("hub/main moved since preflight", self.notifications()[0])
        git(self.repo, "fetch", "-q", "hub")
        git(self.repo, "reset", "-q", "--hard", "hub/main")
        self.calls.unlink()
        self.notes.unlink()
        res = self.run_all("nb=0.1.1", "--yes")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        calls = self.called()
        self.assertEqual((sorted(calls[:3]), calls[3:]), (["linux", "macos", "windows"], ["promote", "site"]))
        self.assertEqual(self.hub_main(), git(self.root / "tree", "rev-parse", "HEAD"))
        self.assertIn("PUBLISHED", self.notifications()[0])


if __name__ == "__main__":
    unittest.main()
