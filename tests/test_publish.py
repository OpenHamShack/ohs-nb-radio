"""tools/publish.sh, run for real against stubbed ssh/curl/rsync and a
stubbed lab-session helper - never the real hosting-management API, 20i,
or any other live endpoint (the task this was built from: "Do NOT run it
for real"). What is checked:

- argument handling (site mapping, --dry-run, --version, --remove and
  --remove-list, including release.sh's own "remove from the remote
  site:" block pasted straight in);
- step order: the key, then the lab session; backup before any upload;
  the payload before the pages; index.html last of the pages; sig before
  the feed itself; removal after upload; verification last of the real
  work; cleanup (the key, the lab session, the temp dir) always last of
  all, even when a step part way through fails;
- that the script's own stdout/stderr never carries the cookie or CSRF a
  lab session mints, even though the stub log (a test fixture, not
  anything publish.sh prints) does.

Each stub appends its invocation to one shared log file; rsync's stub
additionally reads back whatever --files-from pointed at (a real file for
the backup step, a process-substitution fd for the upload steps - both
readable while the stub is still running) so a test can see exactly which
relative paths one rsync call carried, without publish.sh itself needing
to say so.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "publish.sh"


def _release_host_shell() -> bool:
    """Whether this machine has what publish.sh is written for: the Linux
    release host's bash 4+ (mapfile) and GNU find (-printf). A Mac has bash
    3.2 and BSD find, so the Mac build's run of the suite (07/10/2026) had
    every test here fail on the shell, not on the script; Windows has
    neither at all."""
    try:
        res = subprocess.run(["bash", "-c", "mapfile -t a < /dev/null && find . -maxdepth 0 -printf ''"],
                             capture_output=True, timeout=10, cwd=REPO)
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0

_RSYNC_STUB = """#!/usr/bin/env bash
printf 'rsync %s\\n' "$*" >> "$STUB_LOG"
for a in "$@"; do
    case "$a" in
        --files-from=*)
            f="${a#--files-from=}"
            if [ -r "$f" ]; then
                while IFS= read -r rel; do
                    [ -n "$rel" ] && printf 'rsync-file: %s\\n' "$rel" >> "$STUB_LOG"
                done < "$f"
            fi
            ;;
    esac
done
# The content-compare listing (-rcn --out-format=%n): every local file
# differs, except those named in STUB_UNCHANGED (space-separated) and the
# top-level ones an --exclude=/<name> leaves out, as rsync would.
if [[ "$*" == *"--out-format=%n"* ]]; then
    src="${@: -2:1}"
    excluded=" " listed=""
    for a in "$@"; do
        case "$a" in
            --exclude=/*) excluded+="${a#--exclude=/} " ;;
            --files-from=*) listed="${a#--files-from=}" ;;
        esac
    done
    { if [ -n "$listed" ]; then cat "$listed"; else (cd "$src" && find . -type f -printf '%P\n'); fi; } \
    | while IFS= read -r rel; do
        [[ "$excluded" == *" $rel "* ]] && continue
        [[ " ${STUB_UNCHANGED:-} " == *" $rel "* ]] || printf '%s\n' "$rel"
    done
    exit 0
fi
if [ -n "${RSYNC_FAIL:-}" ] && [[ "$*" == *"$RSYNC_FAIL"* ]]; then
    echo "stub rsync: forced failure for test" >&2
    exit 1
fi
exit 0
"""

_SSH_STUB = """#!/usr/bin/env bash
printf 'ssh %s\\n' "$*" >> "$STUB_LOG"
if [ -n "${SSH_FAIL:-}" ] && [[ "$*" == *"$SSH_FAIL"* ]]; then
    echo "stub ssh: forced failure for test" >&2
    exit 1
fi
exit 0
"""

_CURL_STUB = """#!/usr/bin/env bash
printf 'curl %s\\n' "$*" >> "$STUB_LOG"
if [ -n "${CURL_FAIL:-}" ] && [[ "$*" == *"$CURL_FAIL"* ]]; then
    echo "stub curl: forced failure for test" >&2
    exit 22
fi
method=GET
url=""
prev=""
for a in "$@"; do
    if [ "$prev" = "-X" ]; then method="$a"; fi
    case "$a" in https://*) url="$a" ;; esac
    prev="$a"
done
if [ "$method" = GET ] && [ -n "$url" ]; then
    path="${url#https://}"
    path="${path#*/}"
    path="${path%%\\?*}"
    if [ -n "${PUBLISH_LOCAL_DIR:-}" ] && [ -f "$PUBLISH_LOCAL_DIR/$path" ]; then
        cat "$PUBLISH_LOCAL_DIR/$path"
    fi
fi
exit 0
"""

_LAB_SESSION_STUB = """#!/usr/bin/env bash
printf 'lab_session %s\\n' "$*" >> "$STUB_LOG"
echo "COOKIE=test-cookie-value"
echo "CSRF=test-csrf-value"
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def log_events(log_text: str) -> list[dict]:
    """[{"kind", "line", "files"}, ...], one entry per top-level invocation
    the stubs recorded, in order. "files" is the --files-from list for a
    rsync call that used one, else [].

    Position in this list, not the invocation line's own text, is what a
    test should compare for ordering: rsync's stub logs its real argv,
    which includes a process-substitution path like /dev/fd/63 for
    --files-from - bash is free to reuse that same fd number for a later,
    unrelated call once the first is done with it (ordinary, not a bug),
    so two calls' logged lines can be byte-identical. Comparing their
    *index* here is always correct; comparing the raw text is not."""
    out: list[dict] = []
    cur: dict | None = None
    for line in log_text.splitlines():
        if cur is not None and line.startswith("rsync-file: "):
            cur["files"].append(line[len("rsync-file: "):])
            continue
        cur = None
        for kind in ("lab_session", "rsync", "ssh", "curl"):
            if line.startswith(kind + " ") or line == kind:
                entry = {"kind": kind, "line": line, "files": []}
                out.append(entry)
                if kind == "rsync":
                    cur = entry
                break
    return out


@unittest.skipUnless(_release_host_shell(), "publish.sh runs on the Linux release host (bash 4+, GNU find)")
class PublishScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.log = self.root / "log"
        self.log.write_text("")
        self.local_dir = self.root / "release"
        self.local_dir.mkdir()
        self.backups = self.root / "backups"
        self.lab_helper = self.root / "lab-session.sh"

        _write_executable(self.bindir / "rsync", _RSYNC_STUB)
        _write_executable(self.bindir / "ssh", _SSH_STUB)
        _write_executable(self.bindir / "curl", _CURL_STUB)
        _write_executable(self.lab_helper, _LAB_SESSION_STUB)

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self, **over) -> dict:
        env = dict(os.environ)
        env["PATH"] = f"{self.bindir}:{env['PATH']}"
        env["STUB_LOG"] = str(self.log)
        env["PUBLISH_LOCAL_DIR"] = str(self.local_dir)
        env["PUBLISH_REMOTE_SUBDIR"] = "public_html/test"
        env["PUBLISH_PUBLIC_BASE"] = "https://fake-site.example.invalid"
        env["PUBLISH_STANDING_DIR"] = str(self.root / "no-month-key")
        env["PUBLISH_KEY_WAIT_SECONDS"] = "0"
        env["PUBLISH_REMOTE_HOST"] = "fake-user@fake-host.example.invalid"
        env["PUBLISH_API_BASE"] = "https://fake-hosting-api.example.invalid/api/v1"
        env["PUBLISH_PACKAGE_ID"] = "999999"
        env["PUBLISH_CONFIRM_HEADER"] = "fake-site.example.invalid"
        env["PUBLISH_LAB_SESSION_HELPER"] = str(self.lab_helper)
        env["PUBLISH_CONTROL_A_HOST"] = "fake-control-a"
        env["PUBLISH_BACKUP_ROOT"] = str(self.backups)
        env.update(over)
        return env

    def _run(self, args: list[str], env_over: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env=self._env(**(env_over or {})),
                              capture_output=True, text=True, timeout=30)

    def _log_text(self) -> str:
        return self.log.read_text()

    # ------------------------------------------------------------ arguments
    def test_an_unknown_site_refuses_before_touching_anything(self):
        res = self._run(["bogus"])
        self.assertEqual(res.returncode, 2)
        self.assertIn("nb|ham|source", res.stderr)
        self.assertEqual(self._log_text(), "")  # no key, no lab session, nothing

    def test_a_missing_local_dir_refuses_before_touching_anything(self):
        res = self._run(["source"], {"PUBLISH_LOCAL_DIR": str(self.root / "does-not-exist")})
        self.assertEqual(res.returncode, 1)
        self.assertIn("does not exist", res.stderr)
        self.assertEqual(self._log_text(), "")

    def test_remove_accepts_both_flags_and_trailing_arguments(self):
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source", "--remove", "a.old", "b.old"])
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self._log_text()
        self.assertIn("rm -f -- public_html/test/a.old", text)
        self.assertIn("rm -f -- public_html/test/b.old", text)

    def test_remove_list_accepts_release_shs_own_block_verbatim(self):
        (self.local_dir / "keep.deb").write_text("keep")
        remove_list = self.root / "remove-list.txt"
        # Exactly what release.sh prints (tools/release.sh upload_order()/
        # its "remove from the remote site:" sections): a header line, then
        # two-space-indented paths - nothing else in this file is a path.
        remove_list.write_text(
            "moved off the site into /srv/openhamshack-nb-releases-archive:\n"
            "  openhamshack-nb-0.1.7-setup.exe\n"
            "  openhamshack-nb-0.1.7-setup.exe.sha256\n"
            "remove from the remote site:\n"
            "  openhamshack-nb-0.1.7-setup.exe\n"
            "  openhamshack-nb-0.1.7-setup.exe.sha256\n"
        )
        res = self._run(["source", "--remove-list", str(remove_list)])
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self._log_text()
        self.assertIn("rm -f -- public_html/test/openhamshack-nb-0.1.7-setup.exe", text)
        self.assertIn("rm -f -- public_html/test/openhamshack-nb-0.1.7-setup.exe.sha256", text)
        # The header lines are not paths and must never be "removed".
        self.assertNotIn("remove from the remote site", text)
        self.assertNotIn("moved off the site", text)

    def test_version_names_the_backup_folder(self):
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source", "--version", "9.9.9"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"{self.backups}/source-", res.stdout)
        self.assertIn("-pre-9.9.9", res.stdout)

    def test_files_whose_content_is_unchanged_are_left_alone(self):
        # A release folder keeps every old package; only what differs in
        # content is backed up, uploaded and verified (0.1.9's first real
        # run would otherwise have re-sent every old tarball).
        (self.local_dir / "old.deb").write_text("old, already on the site")
        (self.local_dir / "new.deb").write_text("new")
        res = self._run(["source"], {"STUB_UNCHANGED": "old.deb"})
        self.assertEqual(res.returncode, 0, res.stderr)
        events = log_events(self._log_text())
        moved = [f for e in events if e["kind"] == "rsync" and "--out-format" not in e["line"] for f in e["files"]]
        self.assertIn("new.deb", moved)
        self.assertNotIn("old.deb", moved)
        self.assertFalse(any(e["kind"] == "curl" and "old.deb" in e["line"] for e in events),
                         "an unchanged file is not downloaded again to verify")

    def test_robots_and_sitemap_never_go_up(self):
        # The site is a folder of openhamshack.com: crawlers read only the
        # docroot's robots.txt and sitemap, which are the website's, and the
        # release folder's copies still name the deleted hosts.
        (self.local_dir / "keep.deb").write_text("keep")
        (self.local_dir / "robots.txt").write_text("User-agent: *")
        (self.local_dir / "sitemap.xml").write_text("<urlset/>")
        res = self._run(["source"])
        self.assertEqual(res.returncode, 0, res.stderr)
        events = log_events(self._log_text())
        moved = [f for e in events if e["kind"] == "rsync" and "--out-format" not in e["line"] for f in e["files"]]
        self.assertIn("keep.deb", moved)
        self.assertNotIn("robots.txt", moved)
        self.assertNotIn("sitemap.xml", moved)

    def test_nb_uploads_only_what_its_feed_offers(self):
        # The folder on openhamshack.com offers what the feed names and
        # nothing else: not the old packages, and not the product pages,
        # which name people (the site publishes no personal name).
        import json
        for name in ("openhamshack-nb_0.1.16_all.deb", "openhamshack-nb-0.1.16-setup.exe",
                     "openhamshack-nb_0.1.9_all.deb", "index.html", "guide.html", "shots/a-0123456789ab.jpg",
                     "update.json.sig", ".htaccess"):
            (self.local_dir / name).parent.mkdir(parents=True, exist_ok=True)
            (self.local_dir / name).write_text(name)
        (self.local_dir / "openhamshack-nb_0.1.16_all.deb.sha256").write_text("x")
        (self.local_dir / "update.json").write_text(json.dumps({"files": [
            {"url": "openhamshack-nb_0.1.16_all.deb"}, {"url": "openhamshack-nb-0.1.16-setup.exe"}]}))
        res = self._run(["nb"])
        self.assertEqual(res.returncode, 0, res.stderr)
        events = log_events(self._log_text())
        moved = sorted(f for e in events if e["kind"] == "rsync" and "--out-format" not in e["line"]
                       and "--ignore-missing-args" not in e["line"] for f in e["files"])
        self.assertEqual(moved, [".htaccess", "openhamshack-nb-0.1.16-setup.exe", "openhamshack-nb_0.1.16_all.deb",
                                 "openhamshack-nb_0.1.16_all.deb.sha256"])
        # The feed goes up on its own, last, as for every site.
        feed = [e["line"] for e in events if e["kind"] == "rsync" and "--files-from" not in e["line"]
                and "--out-format" not in e["line"]]
        self.assertTrue(feed[-1].rstrip().endswith("public_html/test/update.json"), feed)

    def test_nb_without_a_readable_feed_uploads_nothing(self):
        (self.local_dir / "openhamshack-nb_0.1.16_all.deb").write_text("deb")
        res = self._run(["nb"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("cannot read", res.stdout + res.stderr)
        self.assertFalse(any(e["kind"] == "rsync" for e in log_events(self._log_text())))

    # ------------------------------------------------------------ month key
    def _month_key(self, expires: int) -> Path:
        d = self.root / "month"
        d.mkdir()
        (d / "id_ed25519").write_text("not a real key")
        (d / "meta").write_text(f"handle=ohs-month-test\nexpires={expires}\n")
        return d

    def test_a_valid_month_key_is_used_with_no_session_and_no_new_key(self):
        import time
        d = self._month_key(int(time.time()) + 7 * 86400)
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source"], {"PUBLISH_STANDING_DIR": str(d)})
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self._log_text()
        self.assertNotIn("lab_session", text)
        self.assertNotIn("ssh/keys", text)       # never added, so never deleted
        self.assertIn(f"-i {d}/id_ed25519", text)
        self.assertTrue((d / "id_ed25519").exists(), "the month key must survive the cleanup")

    def test_a_month_key_about_to_lapse_falls_back_to_a_temporary_one(self):
        import time
        d = self._month_key(int(time.time()) + 600)   # under the hour an upload may need
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source"], {"PUBLISH_STANDING_DIR": str(d)})
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self._log_text()
        self.assertIn("lab_session", text)
        self.assertIn("-X POST", text)
        self.assertIn("-X DELETE", text)
        self.assertNotIn(f"-i {d}/id_ed25519", text)

    def test_a_key_20i_never_accepts_stops_before_any_upload(self):
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source"], {"SSH_FAIL": " true", "PUBLISH_KEY_WAIT_TRIES": "2"})
        self.assertEqual(res.returncode, 1)
        self.assertIn("never accepted", res.stdout + res.stderr)
        text = self._log_text()
        self.assertNotIn("rsync", text)
        self.assertIn("-X DELETE", text)   # the temporary key still goes

    # ------------------------------------------------------------- dry run
    def test_dry_run_lists_but_never_uploads_removes_or_verifies(self):
        (self.local_dir / "keep.deb").write_text("keep")
        res = self._run(["source", "--dry-run", "--remove", "old.deb"])
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self._log_text()
        # Reaching the remote at all still needs the key and the session
        # (module docstring), so these do appear even in a dry run:
        self.assertIn("lab_session", text)
        self.assertIn("-X POST", text)
        self.assertIn("ssh/keys", text)
        # A read-only, content-compared listing, nothing more:
        self.assertIn("-rcn --out-format=%n", text)
        self.assertIn("would change: keep.deb", res.stdout + res.stderr)
        # Never an upload, a removal, or a verify GET:
        self.assertNotIn("rm -f --", text)
        self.assertNotIn(f"https://fake-site.example.invalid", text)
        self.assertIn("would remove: old.deb", res.stdout)
        self.assertIn("dry run only", res.stdout)
        # Cleanup still ran (the key and the lab session are real, even in
        # a dry run, and must not be left behind):
        self.assertIn("-X DELETE", text)
        self.assertIn("fake-control-a", text)

    # --------------------------------------------------------------- order
    def test_a_real_run_follows_the_documented_order(self):
        (self.local_dir / "foo.deb").write_text("deb bytes")
        (self.local_dir / "page.html").write_text("<html>page</html>")
        (self.local_dir / "index.html").write_text("<html>index</html>")
        (self.local_dir / "update.json.sig").write_text("sig bytes")
        (self.local_dir / "update.json").write_text('{"v": 1}')

        res = self._run(["source", "--remove", "old.deb"])
        self.assertEqual(res.returncode, 0, res.stderr)
        events = log_events(self._log_text())
        kinds = [e["kind"] for e in events]

        i_lab = kinds.index("lab_session")
        i_add = next(i for i, e in enumerate(events) if e["kind"] == "curl" and "-X POST" in e["line"])
        self.assertLess(i_lab, i_add, "the lab session must exist before a key is added with it")

        rsyncs = [e for e in events if e["kind"] == "rsync" and "--out-format" not in e["line"]]
        # backup, payload, non-index pages, index.html, sig, json
        self.assertEqual(len(rsyncs), 6, rsyncs)
        backup, payload, pages, index, sig, feed = rsyncs

        self.assertIn("--ignore-missing-args", backup["line"])
        self.assertIn("foo.deb", backup["files"])
        self.assertIn("page.html", backup["files"])
        self.assertIn("old.deb", backup["files"], "the file about to be removed is backed up too")

        self.assertNotIn("--ignore-missing-args", payload["line"])
        self.assertEqual(payload["files"], ["foo.deb"])
        self.assertEqual(pages["files"], ["page.html"])
        self.assertEqual(index["files"], ["index.html"])
        self.assertIn("update.json.sig", sig["line"])
        self.assertIn("update.json", feed["line"])
        self.assertNotIn("update.json.sig", feed["line"])

        i_add_key = events.index(next(e for e in events if e["kind"] == "curl" and "-X POST" in e["line"]))
        i_backup, i_payload, i_pages, i_index, i_sig, i_feed = (events.index(e) for e in rsyncs)
        self.assertLess(i_add_key, i_backup, "the key must be added before anything is read or written")
        self.assertLess(i_backup, i_payload, "backed up before any upload")
        self.assertLess(i_payload, i_pages)
        self.assertLess(i_pages, i_index, "index.html must be synced after the other pages")
        self.assertLess(i_index, i_sig)
        self.assertLess(i_sig, i_feed, "update.json.sig before update.json - the feed always last")

        i_remove = next(i for i, e in enumerate(events)
                        if e["kind"] == "ssh" and "rm -f -- public_html/test/old.deb" in e["line"])
        self.assertLess(i_feed, i_remove, "removal happens only after everything is uploaded")

        verify_calls = [i for i, e in enumerate(events)
                       if e["kind"] == "curl" and "fake-site.example.invalid/foo.deb?v=" in e["line"]]
        self.assertEqual(len(verify_calls), 1)
        self.assertLess(i_remove, verify_calls[0], "removal happens before verification")

        i_del_key = next(i for i, e in enumerate(events) if e["kind"] == "curl" and "-X DELETE" in e["line"])
        i_del_session = next(i for i, e in enumerate(events) if e["kind"] == "ssh" and "fake-control-a" in e["line"])
        self.assertLess(verify_calls[0], i_del_key, "cleanup is last of all")
        self.assertLess(i_del_key, i_del_session)

        self.assertIn("published source", res.stdout)

    def test_verification_matches_what_was_actually_uploaded(self):
        (self.local_dir / "foo.deb").write_bytes(b"\x00binary deb content\x01")
        res = self._run(["source"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("verified", res.stdout)
        self.assertNotIn("FAILED", res.stdout)

    # ------------------------------------------------------- failure/trap
    def test_a_failure_part_way_through_still_cleans_up(self):
        (self.local_dir / "foo.deb").write_text("deb bytes")
        (self.local_dir / "update.json.sig").write_text("sig")
        (self.local_dir / "update.json").write_text("{}")
        res = self._run(["source"], {"RSYNC_FAIL": "update.json.sig"})
        self.assertNotEqual(res.returncode, 0)
        events = log_events(self._log_text())
        # Never reached (the failure was in the rsync call just before):
        self.assertFalse(any(e["kind"] == "rsync" and e["line"].rstrip().endswith("update.json")
                             for e in events), events)
        self.assertFalse(any(e["kind"] == "ssh" and "rm -f --" in e["line"] for e in events))
        # Always reached, even though the run above failed:
        self.assertTrue(any(e["kind"] == "curl" and "-X DELETE" in e["line"] for e in events))
        self.assertTrue(any(e["kind"] == "ssh" and "fake-control-a" in e["line"] for e in events))

    def test_a_failed_lab_session_still_removes_the_temp_dir_and_exits_nonzero(self):
        broken_helper = self.root / "broken-lab-session.sh"
        _write_executable(broken_helper, "#!/usr/bin/env bash\necho not-the-expected-format\n")
        res = self._run(["source"], {"PUBLISH_LAB_SESSION_HELPER": str(broken_helper)})
        self.assertNotEqual(res.returncode, 0)
        # No key was ever added, so cleanup has nothing to delete remotely -
        # and must not try anyway (no handle, no session to name).
        self.assertNotIn("-X DELETE", self._log_text())

    # ------------------------------------------------------------- secrecy
    def test_the_cookie_and_csrf_never_reach_the_scripts_own_output(self):
        (self.local_dir / "foo.deb").write_text("deb bytes")
        res = self._run(["source"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("test-cookie-value", res.stdout)
        self.assertNotIn("test-cookie-value", res.stderr)
        self.assertNotIn("test-csrf-value", res.stdout)
        self.assertNotIn("test-csrf-value", res.stderr)
        # (The stub's own log file is a test fixture, not publish.sh's
        # output, and does carry it - that is how the headers are checked
        # above; this test is about what an operator actually sees.)
        self.assertIn("test-cookie-value", self._log_text())


# ------------------------------------------------------------------ pruning
# The stubs above only log; pruning is about which files exist afterwards,
# so these stand-ins keep a real "site": a folder (FAKE_SITE) that ssh runs
# its command in, rsync copies to and from (the real rsync, with
# "host:path" rewritten to a path under it), and curl serves from by URL,
# 404 for whatever is not there. The month key stands in for the lab
# session, so no API is involved at all.
_SITE_SSH = r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do
    case "$1" in -i|-o) shift 2 ;; -*) shift ;; *) break ;; esac
done
shift   # the host
cd "$FAKE_SITE" && bash -c "$*"
"""

_SITE_RSYNC = r"""#!/usr/bin/env bash
args=()
while [ $# -gt 0 ]; do
    case "$1" in
        -e) shift 2; continue ;;
        *:*) [[ "$1" == --* ]] && args+=("$1") || args+=("$FAKE_SITE/${1#*:}") ;;
        *) args+=("$1") ;;
    esac
    shift
done
exec /usr/bin/rsync "${args[@]}"
"""

_SITE_CURL = r"""#!/usr/bin/env bash
out="" fmt="" url=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out=$2; shift 2; continue ;;
        -w) fmt=$2; shift 2; continue ;;
        https://*) url=$1 ;;
    esac
    shift
done
path=${url#"$FAKE_BASE"/}
path=${path%%\?*}
f="$FAKE_SITE/public_html/test/$path"
if [ -f "$f" ]; then
    if [ -n "$out" ]; then cat "$f" > "$out"; else cat "$f"; fi
    code=200
else
    code=404
fi
[ -n "$fmt" ] && printf '%s' "${fmt//%\{http_code\}/$code}"
[ "$code" = 200 ] || [ -n "$fmt" ] || exit 22
exit 0
"""


@unittest.skipUnless(_release_host_shell() and Path("/usr/bin/rsync").is_file(),
                     "publish.sh runs on the Linux release host (bash 4+, GNU find, rsync)")
class PublishPruneTests(unittest.TestCase):
    """What a release leaves on the site and in the release folder: the
    packages its feed names, and nothing older (19/10/2026: every
    superseded .deb was still served, for ever)."""

    CURRENT = ["openhamshack-nb_0.1.23_amd64.deb", "openhamshack-nb_0.1.23_all.deb",
               "openhamshack-nb-0.1.23-setup.exe", "openhamshack-nb-0.1.23-arm64.dmg"]

    def setUp(self):
        import time
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        _write_executable(self.bindir / "ssh", _SITE_SSH)
        _write_executable(self.bindir / "rsync", _SITE_RSYNC)
        _write_executable(self.bindir / "curl", _SITE_CURL)
        self.site_root = self.root / "site"
        self.site = self.site_root / "public_html" / "test"
        self.site.mkdir(parents=True)
        self.release = self.root / "releases"
        self.release.mkdir()
        self.archive = self.root / "releases-archive"    # release.sh's ${RELEASES}-archive
        month = self.root / "month"
        month.mkdir()
        (month / "id_ed25519").write_text("not a real key")
        (month / "meta").write_text(f"handle=ohs-month-test\nexpires={int(time.time()) + 7 * 86400}\n")
        self.month = month

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, folder: Path, name: str, body: str | None = None) -> None:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(body if body is not None else f"bytes of {name}")

    def release_of_0_1_23(self) -> None:
        """The release folder after release-all's promote: 0.1.23 for every
        platform and its feed, beside the .debs of every older release."""
        import json
        for n in self.CURRENT:
            self.put(self.release, n)
            self.put(self.release, n + ".sha256", f"sum of {n}")
        self.put(self.release, "update.json", json.dumps({"files": [
            {"version": "0.1.23", "url": n} for n in self.CURRENT]}))
        self.put(self.release, "update.json.sig", "sig")
        self.put(self.release, ".htaccess", "types")
        for n in ("openhamshack-nb_0.1.22_amd64.deb", "openhamshack-nb_0.1.22_amd64.deb.sha256",
                  "openhamshack-nb_0.1.5_all.deb"):
            self.put(self.release, n)
        self.put(self.release, "index.html", "a product page")
        self.put(self.release, "source/openhamshack-nb-0.1.5-src.tar.gz")

    def site_before(self) -> None:
        """What /desktop/nb served after NB 0.1.22: its .debs and a hand
        release's, which the release folder never had; and a source
        tarball, which is never a package."""
        for n in ("openhamshack-nb_0.1.22_amd64.deb", "openhamshack-nb_0.1.22_amd64.deb.sha256",
                  "openhamshack-nb_0.1.17_all.deb", "openhamshack-nb_0.1.17_all.deb.sha256",
                  "openhamshack-nb-0.1.22-src.tar.gz"):
            self.put(self.site, n)

    def run_publish(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({
            "PATH": f"{self.bindir}:{env['PATH']}",
            "FAKE_SITE": str(self.site_root), "FAKE_BASE": "https://fake-site.example.invalid",
            "PUBLISH_LOCAL_DIR": str(self.release), "PUBLISH_REMOTE_SUBDIR": "public_html/test",
            "PUBLISH_PUBLIC_BASE": "https://fake-site.example.invalid",
            "PUBLISH_REMOTE_HOST": "fake-user@fake-host.example.invalid",
            "PUBLISH_STANDING_DIR": str(self.month), "PUBLISH_KEY_WAIT_SECONDS": "0",
            "PUBLISH_BACKUP_ROOT": str(self.root / "backups"),
            "PUBLISH_API_BASE": "https://fake-hosting-api.example.invalid/api/v1",
            "PUBLISH_LAB_SESSION_HELPER": str(self.root / "no-helper"),
            "PUBLISH_CONTROL_A_HOST": "fake-control-a",
        })
        return subprocess.run(["bash", str(SCRIPT), "nb", *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def names(self, folder: Path) -> set[str]:
        return {p.name for p in folder.iterdir() if p.is_file()} if folder.is_dir() else set()

    STALE_LOCAL = {"openhamshack-nb_0.1.22_amd64.deb", "openhamshack-nb_0.1.22_amd64.deb.sha256",
                   "openhamshack-nb_0.1.5_all.deb"}
    STALE_SITE = {"openhamshack-nb_0.1.22_amd64.deb", "openhamshack-nb_0.1.22_amd64.deb.sha256",
                  "openhamshack-nb_0.1.17_all.deb", "openhamshack-nb_0.1.17_all.deb.sha256"}

    def test_a_release_archives_then_removes_every_package_its_feed_no_longer_names(self):
        self.release_of_0_1_23()
        self.site_before()
        res = self.run_publish("--version", "0.1.23")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        # Gone from both folders...
        self.assertFalse(self.STALE_SITE & self.names(self.site), self.names(self.site))
        self.assertFalse(self.STALE_LOCAL & self.names(self.release), self.names(self.release))
        # ...and every one in the archive, byte for byte: the release
        # folder's copy where it had one, else the site's.
        self.assertEqual(self.names(self.archive), self.STALE_LOCAL | self.STALE_SITE)
        for n in self.STALE_LOCAL | self.STALE_SITE:
            self.assertEqual((self.archive / n).read_text(), f"bytes of {n}")
        # What the feed offers is on the site and still in the folder.
        offered = set(self.CURRENT) | {n + ".sha256" for n in self.CURRENT} | {"update.json", "update.json.sig"}
        self.assertLessEqual(offered, self.names(self.site))
        self.assertLessEqual(offered, self.names(self.release))
        # Source tarballs, and anything below the top level, are never touched.
        self.assertTrue((self.site / "openhamshack-nb-0.1.22-src.tar.gz").is_file())
        self.assertTrue((self.release / "source" / "openhamshack-nb-0.1.5-src.tar.gz").is_file())
        self.assertIn("every pruned file (4) is a 404", res.stdout)

    def test_files_of_a_version_the_feed_offers_are_kept_though_it_does_not_name_them(self):
        # A platform held back keeps the older version's entry in the feed
        # (NB 0.1.19-0.1.21, Windows only), and a file of this release the
        # feed happens not to name is still this release's.
        import json
        self.release_of_0_1_23()
        doc = json.loads((self.release / "update.json").read_text())
        doc["files"] = [f for f in doc["files"] if not f["url"].endswith(".deb")]
        doc["files"].append({"version": "0.1.22", "url": "openhamshack-nb_0.1.22_amd64.deb"})
        (self.release / "update.json").write_text(json.dumps(doc))
        self.site_before()
        res = self.run_publish("--version", "0.1.23")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for n in ("openhamshack-nb_0.1.23_amd64.deb", "openhamshack-nb_0.1.23_all.deb",
                  "openhamshack-nb_0.1.22_amd64.deb", "openhamshack-nb_0.1.22_amd64.deb.sha256"):
            self.assertTrue((self.release / n).is_file(), n)
        self.assertTrue((self.site / "openhamshack-nb_0.1.22_amd64.deb").is_file())
        self.assertEqual(self.names(self.archive), {"openhamshack-nb_0.1.5_all.deb", "openhamshack-nb_0.1.17_all.deb",
                                                    "openhamshack-nb_0.1.17_all.deb.sha256"})

    def test_prune_only_removes_the_stale_packages_and_leaves_the_live_feed_as_it_was(self):
        self.release_of_0_1_23()
        self.site_before()
        # Already live: the site serves exactly this folder's feed.
        for n in [*self.CURRENT, *(n + ".sha256" for n in self.CURRENT), "update.json", "update.json.sig",
                  ".htaccess"]:
            self.put(self.site, n, (self.release / n).read_text())
        feed = (self.site / "update.json").read_bytes(), (self.site / "update.json.sig").read_bytes()
        res = self.run_publish("--prune-only")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertFalse(self.STALE_SITE & self.names(self.site))
        self.assertEqual(self.names(self.archive), self.STALE_LOCAL | self.STALE_SITE)
        self.assertEqual(((self.site / "update.json").read_bytes(), (self.site / "update.json.sig").read_bytes()),
                         feed)
        self.assertFalse((self.root / "backups").exists(), "nothing uploaded, so nothing to back up")
        self.assertIn("nothing uploaded", res.stdout)

    def test_prune_only_refuses_while_the_site_serves_another_feed(self):
        self.release_of_0_1_23()
        self.site_before()
        self.put(self.site, "update.json", '{"files": []}')
        res = self.run_publish("--prune-only")
        self.assertEqual(res.returncode, 1)
        self.assertIn("differs: update.json", res.stdout)
        self.assertEqual(self.names(self.site) & self.STALE_SITE, self.STALE_SITE)
        self.assertEqual(self.names(self.release) & self.STALE_LOCAL, self.STALE_LOCAL)
        self.assertFalse(self.archive.exists())
        self.assertEqual((self.site / "update.json").read_text(), '{"files": []}')

    def test_a_dry_run_names_what_it_would_prune_and_moves_nothing(self):
        self.release_of_0_1_23()
        self.site_before()
        res = self.run_publish("--dry-run")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("would prune: openhamshack-nb_0.1.17_all.deb (from the site", res.stdout)
        self.assertIn("would prune: openhamshack-nb_0.1.5_all.deb (from the release folder", res.stdout)
        self.assertIn("would prune: openhamshack-nb_0.1.22_amd64.deb (from the release folder and the site",
                      res.stdout)
        self.assertNotIn("src.tar.gz", res.stdout.split("would change")[0])
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.names(self.site) & self.STALE_SITE, self.STALE_SITE)
        self.assertEqual(self.names(self.release) & self.STALE_LOCAL, self.STALE_LOCAL)

    def test_an_archive_holding_a_different_copy_keeps_both_and_fails(self):
        self.release_of_0_1_23()
        self.site_before()
        self.put(self.archive, "openhamshack-nb_0.1.5_all.deb", "some other build of 0.1.5")
        res = self.run_publish("--version", "0.1.23")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("already holds a different openhamshack-nb_0.1.5_all.deb", res.stdout)
        self.assertEqual((self.release / "openhamshack-nb_0.1.5_all.deb").read_text(), "bytes of openhamshack-nb_0.1.5_all.deb")
        self.assertEqual((self.archive / "openhamshack-nb_0.1.5_all.deb").read_text(), "some other build of 0.1.5")
        # The rest were still pruned.
        self.assertFalse(self.STALE_SITE & self.names(self.site))

    def test_a_feed_that_names_no_package_prunes_nothing(self):
        self.release_of_0_1_23()
        (self.release / "update.json").write_text('{"files": []}')
        self.site_before()
        res = self.run_publish("--version", "0.1.23")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("names no package", res.stderr)
        self.assertEqual(self.names(self.site) & self.STALE_SITE, self.STALE_SITE)
        self.assertFalse(self.archive.exists())

if __name__ == "__main__":
    unittest.main()
