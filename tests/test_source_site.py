"""Behaviour tests for publishing the third-party source the Windows
installers owe, and each release's own source: the shared source site's
generator (tools/source-site.py).

Each test runs the real tools against scratch folders: a site, its
archive, and lists naming small stand-in tarballs reached through file://
URLs, so fetching, hash-checking, refusing and archiving are exercised
exactly as against Qt's or SourceForge's servers - with no network and
never touching /srv. The "public" copy a --live check reads is a scratch
folder too, reached the same way.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

# Functions only: a TestCase class imported here would be run twice.
from test_site import REPO_ROOT, _git, commit, local_refs, utc_today

if os.name == "nt":
    raise unittest.SkipTest("release.sh and the sites are built on the Linux host")

SOURCE_SITE_PY = REPO_ROOT / "tools" / "source-site.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_line(upstream: Path, name: str, data: bytes, licence: str, carried: str, covers: str) -> str:
    """One line of a source list, with its upstream copy written."""
    upstream.mkdir(parents=True, exist_ok=True)
    (upstream / name).write_bytes(data)
    return f"{name} | {sha(data)} | {licence} | {carried} | {covers} | {(upstream / name).as_uri()}"


class Scratch(unittest.TestCase):
    """A scratch site, archive and upstream, and the generator run on them."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = self.root / "source-site"
        self.archive = self.root / "source-site-archive"
        self.upstream = self.root / "upstream"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def tool(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SOURCE_SITE_PY), "--site", str(self.site),
                               "--archive", str(self.archive), *args],
                              capture_output=True, text=True, timeout=60)

    def write_list(self, name: str, lines: list[str], notes: str = "") -> Path:
        p = self.root / name
        p.write_text("# a scratch list\n\n" + "\n".join(lines) + "\n" + notes)
        return p

    def removal_list(self, out: str) -> list[str]:
        tail = out.split("remove from the remote source site:\n", 1)[1]
        return [l.strip() for l in tail.splitlines() if l.startswith("  ")]


class WithLists(Scratch):
    """Three stand-in tarballs, one for both apps and one each, in one list."""

    def setUp(self) -> None:
        super().setUp()
        self.both = list_line(self.upstream, "qt-6.0.tar.xz", b"qt source " * 2000, "LGPL-3.0",
                              "NB and HAM 0.1.4 onward", "Qt6Core.dll")
        self.nb_only = list_line(self.upstream, "alpha-1.0.tar.gz", b"alpha source", "GPL-3.0",
                                 "NB 0.1.4 onward", "alpha.exe")
        self.ham_only = list_line(self.upstream, "paramiko-3.5.1.tar.gz", b"paramiko source", "LGPL-2.1",
                                  "HAM 0.1.4 onward (Windows)", "paramiko")
        self.lst = self.write_list("sources.txt", [self.both, self.nb_only, self.ham_only],
                                   "> Each tarball is unmodified.\n>\n> Also inside:\n>   - a runtime\n")

    def publish(self, project: str, word: str, lst: Path | None = None) -> subprocess.CompletedProcess:
        return self.tool("publish", project, str(lst or self.lst), "--carried-by", word,
                         "--title", f"OpenHamShack {word}", "--home", f"https://openhamshack{word.lower()}.example.invalid/")


class SharedSourceSite(WithLists):
    def test_a_tarball_two_projects_list_is_stored_once(self) -> None:
        for project, word in (("openhamshack-nb", "NB"), ("openhamshack-ham", "HAM")):
            res = self.publish(project, word)
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sorted(p.name for p in (self.site / "files").iterdir()),
                         ["alpha-1.0.tar.gz", "paramiko-3.5.1.tar.gz", "qt-6.0.tar.xz"])
        sums = (self.site / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(sums), 3)
        check = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=self.site, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        # Both sections point at the one copy.
        page = (self.site / "index.html").read_text()
        for project in ("openhamshack-nb", "openhamshack-ham"):
            section = page.split(f'id="{project}"')[1].split("</section>")[0]
            self.assertIn('href="files/qt-6.0.tar.xz"', section)

    def test_sections_keep_project_order_whichever_command_wrote_the_page(self) -> None:
        # openhamshack-nb-macos.txt sorts before openhamshack-nb.txt by file name ("-"
        # before "."); the page must not swap them when build runs after publish.
        self.assertEqual(self.publish("openhamshack-nb-macos", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        orders = []
        for res in (None, self.tool("build")):
            page = (self.site / "index.html").read_text()
            orders.append(page.index('id="openhamshack-nb"') < page.index('id="openhamshack-nb-macos"'))
        self.assertEqual(orders, [True, True])

    def test_each_project_gets_only_the_lines_its_installers_carry(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)

        def names(project: str) -> list[str]:
            text = (self.site / "manifests" / f"{project}.txt").read_text()
            return [l.split("|")[0].strip() for l in text.splitlines() if "|" in l and not l.startswith("#")]
        self.assertEqual(names("openhamshack-nb"), ["qt-6.0.tar.xz", "alpha-1.0.tar.gz"])
        self.assertEqual(names("openhamshack-ham"), ["qt-6.0.tar.xz", "paramiko-3.5.1.tar.gz"])
        page = (self.site / "index.html").read_text()
        nb_section = page.split('id="openhamshack-nb"')[1].split("</section>")[0]
        self.assertNotIn("paramiko", nb_section)

    def test_the_index_has_a_section_and_anchor_per_project_with_every_file_described(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        page = (self.site / "index.html").read_text()
        self.assertEqual(re.findall(r'<section class="card" id="([^"]+)"', page), ["openhamshack-ham", "openhamshack-nb"])
        self.assertIn('href="#openhamshack-nb"', page)
        self.assertIn('href="#openhamshack-ham"', page)
        nb = page.split('id="openhamshack-nb"')[1]
        self.assertIn("<h2>OpenHamShack NB</h2>", nb)
        self.assertIn('href="https://openhamshacknb.example.invalid/"', nb)
        self.assertIn('<a class="name" href="files/alpha-1.0.tar.gz">alpha-1.0.tar.gz</a> '
                      '<span class="meta">12 bytes</span><span class="lic">GPL-3.0</span>', nb)
        self.assertIn("Source of alpha.exe", nb)
        self.assertIn("In: NB 0.1.4 onward", nb)
        self.assertIn('<span class="meta">20 kB</span>', nb)     # qt: 20000 bytes
        self.assertIn("<p>Each tarball is unmodified.</p>", nb)
        self.assertIn("<ul><li>a runtime</li></ul>", nb)
        # Mobile-friendly and self-contained: a viewport, and nothing fetched
        # from anywhere but this site and the links people click.
        self.assertIn('name="viewport"', page)
        self.assertIn("prefers-color-scheme", page)
        # The only <link> is the canonical address and the only <script> is
        # structured data: neither fetches anything.
        for tag in re.findall(r'<link\b[^>]*>', page):
            self.assertIn('rel="canonical"', tag)
        for tag in re.findall(r'<script\b[^>]*>', page):
            self.assertEqual(tag, '<script type="application/ld+json">')
        for ref in local_refs(page):
            if not ref.startswith("file:"):         # the stand-in upstream's address
                self.assertTrue((self.site / ref).exists(), f"{ref} is referenced but missing")

    def test_publish_refuses_and_writes_no_manifest_while_a_tarball_cannot_be_had(self) -> None:
        (self.upstream / "alpha-1.0.tar.gz").unlink()
        res = self.publish("openhamshack-nb", "NB")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("alpha-1.0.tar.gz", res.stderr)
        self.assertFalse((self.site / "manifests" / "openhamshack-nb.txt").exists())
        self.assertFalse((self.site / "index.html").exists())
        self.assertFalse(list((self.site / "files").glob("*.part")))

    def test_an_upstream_file_that_changed_is_refused_and_not_kept(self) -> None:
        (self.upstream / "qt-6.0.tar.xz").write_bytes(b"someone replaced the release")
        res = self.publish("openhamshack-nb", "NB")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("expected", res.stderr)
        self.assertFalse((self.site / "files" / "qt-6.0.tar.xz").exists())

    def test_a_damaged_copy_is_fetched_again_and_good_ones_need_no_upstream(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        (self.site / "files" / "alpha-1.0.tar.gz").write_bytes(b"truncated")
        self.assertNotEqual(self.tool("check", "openhamshack-nb").returncode, 0)
        (self.upstream / "qt-6.0.tar.xz").unlink()          # good on the site: not fetched again
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("fetching qt", res.stderr)
        self.assertEqual((self.site / "files" / "alpha-1.0.tar.gz").read_bytes(), b"alpha source")
        self.assertEqual(self.tool("check", "openhamshack-nb").returncode, 0)

    def test_the_same_name_with_two_hashes_is_refused(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        other = self.write_list("datv.txt", [list_line(self.root / "elsewhere", "qt-6.0.tar.xz", b"other bytes",
                                                       "LGPL-3.0", "DATV 1.0", "Qt")])
        res = self.tool("publish", "openhamshack-datv", str(other))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("one name cannot be two files", res.stderr)
        self.assertFalse((self.site / "manifests" / "openhamshack-datv.txt").exists())
        self.assertEqual((self.site / "files" / "qt-6.0.tar.xz").read_bytes(), b"qt source " * 2000)

    def test_a_dropped_tarball_is_archived_not_deleted_once_build_runs(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        # HAM's next installer no longer carries Paramiko, nor Qt - which NB
        # still does.
        newer = self.write_list("newer.txt", [self.nb_only.replace("NB 0.1.4", "NB and HAM 0.1.6")])
        res = self.publish("openhamshack-ham", "HAM", newer)
        self.assertEqual(res.returncode, 0, res.stderr)
        # publish moves nothing: HAM's old installer is still on offer.
        self.assertTrue((self.site / "files" / "paramiko-3.5.1.tar.gz").exists())
        self.assertNotIn("remove from", res.stdout)
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.site / "files" / "paramiko-3.5.1.tar.gz").exists())
        self.assertEqual((self.archive / "files" / "paramiko-3.5.1.tar.gz").read_bytes(), b"paramiko source")
        self.assertTrue((self.site / "files" / "qt-6.0.tar.xz").exists())      # NB's still
        self.assertEqual(self.removal_list(res.stdout), ["files/paramiko-3.5.1.tar.gz"])
        self.assertNotIn("paramiko", (self.site / "SHA256SUMS").read_text())
        self.assertNotIn("paramiko", (self.site / "index.html").read_text())
        # The manifest it replaced is kept, as the record of what the older
        # installer was offered with.
        old = list((self.archive / "manifests").glob("openhamshack-ham.*.txt"))
        self.assertEqual(len(old), 1)
        self.assertIn("paramiko-3.5.1.tar.gz", old[0].read_text())

    def test_nothing_dropped_means_nothing_to_remove(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("nothing to remove from the remote source site", res.stdout)
        self.assertFalse(self.archive.exists())

    def test_the_archive_never_loses_a_different_file_of_the_same_name(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        (self.archive / "files").mkdir(parents=True)
        (self.archive / "files" / "stray-1.0.tar.gz").write_bytes(b"one copy")
        (self.site / "files" / "stray-1.0.tar.gz").write_bytes(b"another copy")
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.archive / "files" / "stray-1.0.tar.gz").read_bytes(), b"one copy")
        kept = (self.archive / "files" / f"stray-1.0.tar.gz.{sha(b'another copy')[:12]}")
        self.assertEqual(kept.read_bytes(), b"another copy")
        self.assertFalse((self.site / "files" / "stray-1.0.tar.gz").exists())

    def test_withdraw_archives_the_manifest_and_what_only_that_project_needed(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        res = self.tool("withdraw", "openhamshack-ham")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.removal_list(res.stdout), ["manifests/openhamshack-ham.txt", "files/paramiko-3.5.1.tar.gz"])
        self.assertFalse((self.site / "manifests" / "openhamshack-ham.txt").exists())
        self.assertTrue((self.site / "files" / "qt-6.0.tar.xz").exists())
        self.assertNotIn('id="openhamshack-ham"', (self.site / "index.html").read_text())

    def test_the_how_to_is_published_beside_the_page(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual((self.site / "HOW-TO-PUBLISH.txt").read_text(),
                         (REPO_ROOT / "docs" / "source-site.md").read_text())

    def test_a_manifest_written_by_hand_is_published_by_build(self) -> None:
        # Another project's way in, per docs/source-site.md: its own file in
        # manifests/, then build.
        (self.site / "manifests").mkdir(parents=True)
        (self.site / "manifests" / "openhamshack-atv.txt").write_text(
            "@title OpenHamShack ATV\n" + list_line(self.upstream, "atvlib-2.tar.gz", b"atv", "GPL-2.0", "ATV 1.0",
                                               "atvlib.dll") + "\n")
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.site / "files" / "atvlib-2.tar.gz").read_bytes(), b"atv")
        self.assertIn('id="openhamshack-atv"', (self.site / "index.html").read_text())

    def test_check_live_needs_the_public_copy_complete(self) -> None:
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        public = self.root / "public"
        public.mkdir()
        url = public.as_uri() + "/"
        res = self.tool("check", "openhamshack-ham", "--live", url)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("manifests/openhamshack-ham.txt is missing", res.stderr)
        # Uploaded, but one file cut short.
        shutil.rmtree(public)
        shutil.copytree(self.site, public)
        (public / "files" / "qt-6.0.tar.xz").write_bytes(b"qt so")
        res = self.tool("check", "openhamshack-ham", "--live", url)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("files/qt-6.0.tar.xz is missing or not its full size", res.stderr)
        shutil.copy2(self.site / "files" / "qt-6.0.tar.xz", public / "files" / "qt-6.0.tar.xz")
        res = self.tool("check", "openhamshack-ham", "--live", url)
        self.assertEqual(res.returncode, 0, res.stderr)


class SitemapAndRobots(WithLists):
    """tools/source-site.py keeps another session's sitemap.xml and
    robots.txt (06/10/2026) current, the same rule tools/site-build.py
    follows (tools/sitemap_sync.py, shared by both): the site's one page,
    index.html, gets its <lastmod> moved to today only when its bytes
    actually changed, and nothing the tool did not write - an unrelated
    entry, robots.txt, the file's very existence - is ever touched."""

    SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               '  <url><loc>https://openhamshack.com/source/</loc><lastmod>2020-01-01</lastmod></url>\n'
               '  <url><loc>https://openhamshack.com/source/about.html</loc><lastmod>2021-06-06</lastmod></url>\n'
               '</urlset>\n')
    ROBOTS = "User-agent: *\nAllow: /\n"

    def setUp(self) -> None:
        super().setUp()
        self.site.mkdir(parents=True)
        (self.site / "sitemap.xml").write_text(self.SITEMAP)
        (self.site / "robots.txt").write_text(self.ROBOTS)

    def sitemap(self) -> str:
        return (self.site / "sitemap.xml").read_text()

    def test_never_created_when_absent(self) -> None:
        shutil.rmtree(self.site)
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertFalse((self.site / "sitemap.xml").exists())
        self.assertFalse((self.site / "robots.txt").exists())

    def test_home_lastmod_moves_to_today_once_the_page_exists(self) -> None:
        # index.html does not exist in this scratch site yet, so publishing
        # into it is as much a change to the page as any later edit.
        res = self.publish("openhamshack-nb", "NB")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"<loc>https://openhamshack.com/source/</loc><lastmod>{utc_today()}</lastmod>",
                      self.sitemap())

    def test_unrelated_entry_is_preserved(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertIn("<loc>https://openhamshack.com/source/about.html</loc><lastmod>2021-06-06</lastmod>",
                      self.sitemap())

    def test_unchanged_page_keeps_its_date(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)   # index.html now exists, dated today
        # Stand in for "this date has been true for years": nothing else
        # about the site changes before the next build, so index.html comes
        # out byte for byte the same and the date must stay put.
        sm_path = self.site / "sitemap.xml"
        sm_path.write_text(sm_path.read_text().replace(utc_today(), "2020-01-01", 1))
        self.assertEqual(self.tool("build").returncode, 0)
        self.assertIn("<lastmod>2020-01-01</lastmod>", sm_path.read_text())

    def test_survives_build_and_withdraw(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        self.assertEqual(self.tool("build").returncode, 0)   # prunes nothing both still name; runs regardless
        self.assertTrue((self.site / "sitemap.xml").exists())
        self.assertEqual((self.site / "robots.txt").read_text(), self.ROBOTS)
        self.assertEqual(self.tool("withdraw", "openhamshack-nb").returncode, 0)   # archives what only NB needed
        self.assertTrue((self.site / "sitemap.xml").exists())
        self.assertEqual((self.site / "robots.txt").read_text(), self.ROBOTS)


class PageMetadataAndServerFiles(WithLists):
    """What search engines read - a title and description naming only the
    programs whose source is actually here, a canonical address, preview
    tags and CollectionPage data - and the server-level files (.htaccess,
    404.html) written on every build and never removed."""

    def build_three(self) -> str:
        """NB and HAM with files, ATV with notes only (its real shape)."""
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        self.assertEqual(self.publish("openhamshack-ham", "HAM").returncode, 0)
        (self.site / "manifests" / "openhamshack-atv.txt").write_text(
            "@title OpenHamShack ATV\n@home https://openhamshackatv.example.invalid/\n\n> Nothing by others.\n")
        ball = self.root / "openhamshack-nb-0.1.6-src.tar.gz"
        ball.write_bytes(b"nb own source")
        res = self.tool("publish-own", "openhamshack-nb", str(ball), "--licence", "GPL-3.0-or-later",
                        "--carried", "NB 0.1.6", "--covers", "OpenHamShack NB 0.1.6 itself")
        self.assertEqual(res.returncode, 0, res.stderr)
        return (self.site / "index.html").read_text()

    def test_title_and_description_name_only_the_programs_with_source_here(self) -> None:
        page = self.build_three()
        self.assertIn('<html lang="en-GB">', page)
        title = re.search(r"<title>(.*?)</title>", page).group(1)
        self.assertIn("NB", title)
        self.assertIn("HAM", title)
        self.assertNotIn("ATV", title)
        desc = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
        self.assertIn("OpenHamShack HAM and OpenHamShack NB", desc)
        self.assertNotIn("ATV", desc)
        self.assertLessEqual(len(desc), 160)

    def test_canonical_preview_tags_and_structured_data(self) -> None:
        import json
        page = self.build_three()
        self.assertIn('<link rel="canonical" href="https://openhamshack.com/source/">', page)
        self.assertIn('<meta property="og:url" content="https://openhamshack.com/source/">', page)
        self.assertIn('<meta name="twitter:card" content="summary">', page)
        [blob] = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        data = json.loads(blob)
        self.assertEqual(data["@type"], "CollectionPage")
        self.assertEqual(data["url"], "https://openhamshack.com/source/")
        # One part per program whose own source is here (only NB's, in this
        # scratch site), tied to the program it builds.
        [part] = data["hasPart"]
        self.assertEqual(part["@type"], "SoftwareSourceCode")
        self.assertEqual(part["url"], "https://openhamshack.com/source/#openhamshack-nb")
        self.assertIn("GPL-3.0-or-later", part["license"])
        self.assertEqual(part["targetProduct"]["name"], "OpenHamShack NB")

    def test_htaccess_and_404_are_written_and_survive_build_prune_and_withdraw(self) -> None:
        self.build_three()
        repo_htaccess = (REPO_ROOT / "packaging" / "source-site" / "htaccess").read_text()
        self.assertEqual((self.site / ".htaccess").read_text(), repo_htaccess)
        page = (self.site / "404.html").read_text()
        self.assertIn('<meta name="robots" content="noindex">', page)
        # Served at any depth, so nothing relative; and the archive is the
        # /source/ folder of openhamshack.com, so every link stays inside it.
        for ref in local_refs(page):
            self.assertTrue(ref.startswith("/source/"), ref)
            self.assertTrue((self.site / ref.removeprefix("/source/")).exists(), ref)
        (self.site / "files" / "stray-0.1.tar.gz").write_bytes(b"no manifest names this")
        self.assertEqual(self.tool("build").returncode, 0)                 # prunes the stray
        self.assertEqual(self.tool("withdraw", "openhamshack-ham").returncode, 0)
        self.assertFalse((self.site / "files" / "stray-0.1.tar.gz").exists())
        self.assertEqual((self.site / ".htaccess").read_text(), repo_htaccess)
        self.assertTrue((self.site / "404.html").is_file())


class OwnSourceTarball(Scratch):
    """tarball: a release commit's whole tree, the same bytes every time."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.root / "repo"
        (self.repo / "app").mkdir(parents=True)
        (self.repo / "app" / "main.py").write_text("print('hello')\n")
        (self.repo / "NOTES.md").write_text("internal: build host 192.0.2.10\n")
        subprocess.run(_git(self.repo)[:3] + ["init", "-q"], check=True)
        commit(self.repo, "Release 0.1.0", allow_empty=False)
        self.old = self.rev("HEAD")
        # export-ignore arrives after the first release, as .gitattributes
        # did in the real repository.
        (self.repo / ".gitattributes").write_text("NOTES.md export-ignore\n")
        (self.repo / "app" / "main.py").write_text("print('hello again')\n")
        commit(self.repo, "Release 0.2.0", allow_empty=False)

    def rev(self, r: str) -> str:
        return subprocess.run(_git(self.repo) + ["rev-parse", r], check=True, capture_output=True,
                              text=True).stdout.strip()

    def tarball(self, rev: str, prefix: str, out: Path) -> Path:
        res = self.tool("tarball", str(self.repo), rev, prefix, "--out", str(out))
        self.assertEqual(res.returncode, 0, res.stderr)
        path = Path(res.stdout.strip())
        self.assertEqual(path, out / f"{prefix}-src.tar.gz")
        return path

    def test_the_same_commit_gives_the_same_bytes(self) -> None:
        a = self.tarball("HEAD", "app-0.2.0", self.root / "one")
        # A different checkout state that must not matter: a file touched
        # since, and an untracked one.
        os.utime(self.repo / "app" / "main.py", (1, 1))
        (self.repo / "scratch.txt").write_text("not committed")
        b = self.tarball("HEAD", "app-0.2.0", self.root / "two")
        self.assertEqual(a.read_bytes(), b.read_bytes())
        # Nothing in it is the clock's: gzip's header time is zero, and
        # every member carries the commit's time.
        self.assertEqual(a.read_bytes()[4:8], b"\0\0\0\0")
        when = int(subprocess.run(_git(self.repo) + ["log", "-1", "--format=%ct"], check=True,
                                  capture_output=True, text=True).stdout)
        with tarfile.open(a) as t:
            self.assertEqual({m.mtime for m in t.getmembers()}, {when})
            names = t.getnames()
            self.assertEqual(t.extractfile("app-0.2.0/app/main.py").read(), b"print('hello again')\n")
        self.assertTrue(all(n == "app-0.2.0" or n.startswith("app-0.2.0/") for n in names), names)
        self.assertNotIn("scratch.txt", " ".join(names))

    def test_export_ignore_applies_to_commits_made_before_it(self) -> None:
        for rev, prefix in (("HEAD", "app-0.2.0"), (self.old, "app-0.1.0")):
            with tarfile.open(self.tarball(rev, prefix, self.root / "out")) as t:
                names = t.getnames()
            self.assertIn(f"{prefix}/app/main.py", names)
            self.assertNotIn(f"{prefix}/NOTES.md", names)

    def test_this_repositorys_attributes_leave_out_the_screenshots_and_notes_only(self) -> None:
        # The real .gitattributes, applied by git archive to a tree laid out
        # as this one is: the guides' screenshots (NB's and HAM's) and
        # HANDOVER.md go; the guides, and the modules that render the
        # screenshots, stay.
        shutil.copy2(REPO_ROOT / ".gitattributes", self.repo / ".gitattributes")
        kept = ["docs/USERGUIDE.md", "docs/ham/USERGUIDE.md", "ohsnb/ui/screenshots.py",
                "ohsradio/ui/screenshots.py", "packaging/copyright"]
        dropped = ["docs/screenshots/main.png", "docs/ham/screenshots/bands.png", "HANDOVER.md"]
        for rel in kept + dropped:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_bytes(b"\x89PNG\r\n" if rel.endswith(".png") else b"x = 1\n")
        commit(self.repo, "Release 0.3.0", allow_empty=False)
        with tarfile.open(self.tarball("HEAD", "app-0.3.0", self.root / "out")) as t:
            names = set(t.getnames())
        for rel in kept:
            self.assertIn(f"app-0.3.0/{rel}", names)
        for rel in dropped:
            self.assertNotIn(f"app-0.3.0/{rel}", names)
        self.assertFalse([n for n in names if "/screenshots/" in n], names)

    def test_refuses_what_is_not_a_commit(self) -> None:
        res = self.tool("tarball", str(self.repo), "no-such-rev", "app-9", "--out", str(self.root / "out"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not a commit", res.stderr)
        self.assertFalse((self.root / "out" / "app-9-src.tar.gz").exists())


class OwnSourceScrubbed(Scratch):
    """tarball with a scrub list: internal names replaced in what is
    published, and never anything that changes how the tree builds or
    runs. The fixture is a small program with its tests, a Rust source and
    a binary, naming a made-up build host and address the way the real
    tree's old commits named real ones."""

    LIST = (
        "# a scratch scrub list\n"
        "builder-7 (account\\n`acct-x`) => the build machine\n"
        " on builder-7 =>  on the build machine\n"
        "10.9.8.7 => 192.0.2.7\n"
        "me@private.invalid =>\n"
        "@forbid (?i)builder-7|acct-x\n"
        "@forbid \\b10\\.9\\.\\d+\\.\\d+\\b\n"
        "> Screenshots are rendered by app.shots.\n")
    MAIN = ('"""The program. Timed on builder-7 at 3 ms."""\n'
            "HOST = 'example'   # measured on builder-7\n\n\n"
            "def answer(address: str) -> str:\n"
            '    """Echoes the address, as discovery reports it (seen on builder-7)."""\n'
            "    return f'{HOST}:{address}'\n")
    TEST = ("import unittest\nimport sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
            "from app.main import answer\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_echo(self):\n"
            "        # The radio on builder-7's LAN answered at 10.9.8.7.\n"
            "        self.assertEqual(answer('10.9.8.7'), 'example:10.9.8.7')\n")

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.root / "repo"
        files = {
            "app/__init__.py": "",
            "app/main.py": self.MAIN,
            "tests/test_main.py": self.TEST,
            "docs/BUILD.md": "Built on the machine builder-7 (account\n`acct-x`), owner me@private.invalid.\n",
            "rust/src/lib.rs": "// fast enough on a laptop\npub fn x() -> u8 { 7 }\n",
            "packaging/source-scrub.txt": self.LIST,
            ".gitattributes": "packaging/source-scrub.txt export-ignore\nNOTES.md export-ignore\n",
            "NOTES.md": "internal\n",
        }
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        (self.repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0 not a host name")
        subprocess.run(_git(self.repo)[:3] + ["init", "-q"], check=True)
        commit(self.repo, "Release 1.0", allow_empty=False)

    def tarball(self, out: str = "out", *extra: str) -> subprocess.CompletedProcess:
        return self.tool("tarball", str(self.repo), "HEAD", "app-1.0", "--out", str(self.root / out), *extra)

    def unpack(self, out: str = "out") -> Path:
        dest = self.root / f"{out}-tree"
        with tarfile.open(self.root / out / "app-1.0-src.tar.gz") as t:
            t.extractall(dest, filter="data")
        return dest / "app-1.0"

    def change_list(self, extra: str) -> None:
        (self.repo / "packaging" / "source-scrub.txt").write_text(self.LIST + extra)

    def test_replacements_are_made_and_recorded_in_source_notes(self) -> None:
        res = self.tarball()
        self.assertEqual(res.returncode, 0, res.stderr)
        with tarfile.open(self.root / "out" / "app-1.0-src.tar.gz") as t:
            names = t.getnames()
        self.assertEqual(names[1], "app-1.0/SOURCE-NOTES.txt")       # beside the top folder, read first
        tree = self.unpack()
        self.assertEqual((tree / "docs" / "BUILD.md").read_text(), "Built on the machine the build machine, owner .\n")
        main = (tree / "app" / "main.py").read_text()
        self.assertIn("Timed on the build machine at 3 ms", main)
        self.assertIn("# measured on the build machine", main)
        self.assertIn("answer('192.0.2.7'), 'example:192.0.2.7'", (tree / "tests" / "test_main.py").read_text())
        self.assertNotIn("source-scrub.txt", " ".join(names))           # the list never travels
        notes = (tree / "SOURCE-NOTES.txt").read_text()
        changed = notes.split("in:\n", 1)[1].split("\n\n", 1)[0].split()
        self.assertEqual(changed, ["app/main.py", "docs/BUILD.md", "tests/test_main.py"])
        left = notes.split("says why):\n", 1)[1].split("\n\n", 1)[0].split()
        self.assertEqual(left, ["NOTES.md", "packaging/", "(1", "file)"])
        self.assertIn("Screenshots are rendered by app.shots.", notes)
        self.assertNotRegex(notes, r"builder-7|acct-x|10\.9\.8\.7|private\.invalid")

    def test_nothing_that_builds_or_runs_is_changed(self) -> None:
        self.assertEqual(self.tarball().returncode, 0)
        tree = self.unpack()
        # The scrubbed tree's tests pass, and the program does exactly what
        # the commit's does.
        run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tree,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        probe = "import app.main; print(app.main.answer('x'), app.main.HOST)"
        for where in (tree, self.repo):
            out = subprocess.run([sys.executable, "-c", probe], cwd=where, capture_output=True, text=True)
            self.assertEqual(out.stdout, "example:x example\n", out.stderr)
        self.assertEqual((tree / "rust" / "src" / "lib.rs").read_bytes(), (self.repo / "rust/src/lib.rs").read_bytes())
        self.assertEqual((tree / "logo.png").read_bytes(), (self.repo / "logo.png").read_bytes())
        # Every member keeps git's mode, owner and the commit's time.
        with tarfile.open(self.root / "out" / "app-1.0-src.tar.gz") as t:
            self.assertEqual(len({(m.mtime, m.uname, m.uid) for m in t.getmembers()}), 1)

    def test_a_replacement_that_would_change_code_is_refused(self) -> None:
        for extra, culprit in (("'example' => 'other'\n", "app/main.py"),       # program code
                               ("a laptop => a desk\n", "rust/src/lib.rs"),        # a Rust comment, even
                               ("not a host => not one\n", "logo.png")):          # inside a binary
            with self.subTest(culprit):
                self.change_list(extra)
                res = self.tarball()
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(culprit, res.stderr)
                self.assertFalse((self.root / "out" / "app-1.0-src.tar.gz").exists())

    def test_what_the_list_forbids_stops_the_tarball(self) -> None:
        (self.repo / "docs" / "MORE.md").write_text("ok\nthen 10.9.1.1 again\n")
        commit(self.repo, "more", allow_empty=False)
        res = self.tarball()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("docs/MORE.md:2: '10.9.1.1'", res.stderr)
        self.assertFalse((self.root / "out" / "app-1.0-src.tar.gz").exists())

    def test_the_list_must_be_left_out_of_what_it_scrubs(self) -> None:
        (self.repo / ".gitattributes").write_text("NOTES.md export-ignore\n")
        res = self.tarball()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("packaging/source-scrub.txt would be in the tarball", res.stderr)

    def test_the_same_commit_and_list_give_the_same_bytes(self) -> None:
        self.assertEqual(self.tarball("one").returncode, 0)
        os.utime(self.repo / "app" / "main.py", (1, 1))
        self.assertEqual(self.tarball("two").returncode, 0)
        a = (self.root / "one" / "app-1.0-src.tar.gz").read_bytes()
        self.assertEqual(a, (self.root / "two" / "app-1.0-src.tar.gz").read_bytes())
        self.assertEqual(a[4:8], b"\0\0\0\0")
        # --no-scrub is git archive's tar exactly: no notes, nothing replaced.
        self.assertEqual(self.tarball("plain", "--no-scrub").returncode, 0)
        with tarfile.open(self.root / "plain" / "app-1.0-src.tar.gz") as t:
            self.assertNotIn("app-1.0/SOURCE-NOTES.txt", t.getnames())
            self.assertIn(b"builder-7", t.extractfile("app-1.0/docs/BUILD.md").read())

    def test_this_repositorys_tree_and_list_make_a_tarball(self) -> None:
        # The real list applied to the real HEAD: an internal name newly
        # written anywhere fails here, not at the next release.
        real = REPO_ROOT / "packaging" / "source-scrub.txt"
        if not real.exists() or not (REPO_ROOT / ".git").exists():
            self.skipTest("not a checkout with its scrub list (a source tarball)")
        res = self.tool("tarball", str(REPO_ROOT), "HEAD", "openhamshack-head", "--out", str(self.root / "real"))
        self.assertEqual(res.returncode, 0, res.stderr)


class OwnSourcePublished(WithLists):
    """publish-own: a project's own release tarballs, kept beside its
    third-party list and never dropped by either."""

    def own(self, version: str, data: bytes | None = None, project: str = "openhamshack-nb",
            word: str = "NB", *extra: str) -> subprocess.CompletedProcess:
        ball = self.root / "builds" / f"{project}-{version}-src.tar.gz"
        ball.parent.mkdir(exist_ok=True)
        ball.write_bytes(data if data is not None else f"{project} {version} source".encode())
        return self.tool("publish-own", project, str(ball), "--licence", "GPL-3.0-or-later",
                         "--carried", f"{word} {version}: every package of it",
                         "--covers", f"OpenHamShack {word} {version} itself, release commit abc{version}",
                         "--title", f"OpenHamShack {word}", "--home", f"https://openhamshack{word.lower()}.example.invalid/",
                         *extra)

    def own_names(self, project: str = "openhamshack-nb") -> list[str]:
        text = (self.site / "manifests" / f"{project}.txt").read_text()
        return [l[len("@own "):].split("|")[0].strip() for l in text.splitlines() if l.startswith("@own ")]

    def test_publishes_into_files_manifest_sums_and_its_own_part_of_the_section(self) -> None:
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        res = self.own("0.1.5")
        self.assertEqual(res.returncode, 0, res.stderr)
        name = "openhamshack-nb-0.1.5-src.tar.gz"
        self.assertEqual((self.site / "files" / name).read_bytes(), b"openhamshack-nb 0.1.5 source")
        self.assertEqual(self.own_names(), [name])
        self.assertIn(f"{sha(b'openhamshack-nb 0.1.5 source')}  files/{name}", (self.site / "SHA256SUMS").read_text())
        check = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=self.site, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        page = (self.site / "index.html").read_text()
        nb = page.split('id="openhamshack-nb"')[1].split("</section>")[0]
        own_at = nb.index("<h3>OpenHamShack NB's own source, per release</h3>")
        third_at = nb.index("<h3>Third-party source in OpenHamShack NB's installers</h3>")
        self.assertLess(own_at, nb.index(f'href="files/{name}"'))
        self.assertLess(nb.index(f'href="files/{name}"'), third_at)      # listed apart from the third-party
        self.assertLess(third_at, nb.index('href="files/alpha-1.0.tar.gz"'))
        self.assertIn("Source of OpenHamShack NB 0.1.5 itself, release commit abc0.1.5", nb)
        self.assertNotIn('href="local"', nb)          # an own tarball has no upstream to name
        self.assertEqual(self.tool("check", "openhamshack-nb").returncode, 0)

    def test_a_project_with_no_manifest_yet_gets_one_with_only_its_own_source(self) -> None:
        res = self.own("1.0", project="openhamshack-datv", word="DATV")
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.site / "index.html").read_text()
        datv = page.split('id="openhamshack-datv"')[1].split("</section>")[0]
        self.assertIn("<h3>OpenHamShack DATV's own source, per release</h3>", datv)
        self.assertNotIn("Third-party", datv)

    def test_every_version_is_kept_through_releases_lists_and_builds(self) -> None:
        for v in ("0.1.0", "0.1.4", "0.1.5"):
            self.assertEqual(self.own(v).returncode, 0)
        # A new installer's third-party list replaces the old one, and build
        # archives what no list names: neither touches the own source.
        self.assertEqual(self.publish("openhamshack-nb", "NB").returncode, 0)
        newer = self.write_list("newer.txt", [self.both])
        self.assertEqual(self.publish("openhamshack-nb", "NB", newer).returncode, 0)
        res = self.tool("build")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.removal_list(res.stdout), ["files/alpha-1.0.tar.gz"])
        expected = [f"openhamshack-nb-{v}-src.tar.gz" for v in ("0.1.5", "0.1.4", "0.1.0")]     # newest first
        self.assertEqual(self.own_names(), expected)
        page = (self.site / "index.html").read_text()
        for name in expected:
            self.assertTrue((self.site / "files" / name).exists(), name)
            self.assertIn(f'href="files/{name}"', page)
        self.assertFalse((self.archive / "files").exists() and
                         any("src.tar.gz" in p.name for p in (self.archive / "files").iterdir()))

    def test_the_same_file_again_changes_nothing_and_other_bytes_are_refused(self) -> None:
        self.assertEqual(self.own("0.1.5").returncode, 0)
        self.assertEqual(self.own("0.1.5").returncode, 0)
        self.assertEqual(self.own_names(), ["openhamshack-nb-0.1.5-src.tar.gz"])
        res = self.own("0.1.5", b"a rebuilt, different tarball")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("never replaced", res.stderr)
        self.assertEqual((self.site / "files" / "openhamshack-nb-0.1.5-src.tar.gz").read_bytes(),
                         b"openhamshack-nb 0.1.5 source")

    def test_a_list_with_own_lines_is_refused_by_publish(self) -> None:
        lst = self.write_list("own.txt", [self.both, "@own " + self.nb_only])
        res = self.publish("openhamshack-nb", "NB", lst)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("publish-own", res.stderr)

    def test_every_manifest_it_replaces_is_kept_even_several_in_one_second(self) -> None:
        for v in ("0.1.0", "0.1.1", "0.1.2"):
            self.assertEqual(self.own(v).returncode, 0)
        kept = sorted((self.archive / "manifests").iterdir())
        self.assertEqual(len(kept), 2, [p.name for p in kept])
        self.assertEqual(len({p.read_text() for p in kept}), 2)

    def test_a_project_with_only_notes_still_shows_them(self) -> None:
        # OpenHamShack ATV's case: its package carries nothing by others, and its
        # manifest is only the notes that say so.
        (self.site / "manifests").mkdir(parents=True)
        (self.site / "manifests" / "openhamshack-atv.txt").write_text(
            "@title OpenHamShack ATV\n\n> Its package carries no third-party code.\n")
        self.assertEqual(self.own("0.1.5").returncode, 0)
        page = (self.site / "index.html").read_text()
        atv = page.split('id="openhamshack-atv"')[1].split("</section>")[0]
        self.assertIn("<p>Its package carries no third-party code.</p>", atv)
        # And says plainly that nothing to download is the design, not a
        # gap: the audit of 06/10/2026 read "0 files, 0 bytes" as unfinished.
        self.assertIn("No files to download here, by design.", atv)
        self.assertIn("OpenHamShack ATV's packages carry no third-party code", atv)
        nav = page.split('href="#openhamshack-atv"')[1].split("</li>")[0]
        self.assertIn("nothing to download: it bundles no third-party code", nav)
        self.assertNotIn("0 files", nav)
        # A project that does have files gets no such note.
        nb = page.split('id="openhamshack-nb"')[1].split("</section>")[0]
        self.assertNotIn("by design", nb)

    def test_a_lost_copy_fails_the_build_and_says_how_to_make_it_again(self) -> None:
        self.assertEqual(self.own("0.1.5").returncode, 0)
        (self.site / "files" / "openhamshack-nb-0.1.5-src.tar.gz").unlink()
        res = self.tool("build")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("from its release commit", res.stderr)
        self.assertEqual(self.own("0.1.5").returncode, 0)      # the same bytes, made again, mend it
        self.assertEqual(self.tool("check", "openhamshack-nb").returncode, 0)

    # --replace-unpublished: the one way a name gets other bytes, and only
    # while the public site shows no trace of it.

    def public_site(self, listing: str | None) -> str:
        """A scratch "public" copy: its SHA256SUMS holds `listing` (none at
        all when None, as an unreachable site)."""
        public = self.root / "public"
        shutil.rmtree(public, ignore_errors=True)
        (public / "files").mkdir(parents=True)
        if listing is not None:
            (public / "SHA256SUMS").write_text(listing)
        return public.as_uri() + "/"

    def test_a_never_uploaded_tarball_is_replaced_in_place_and_the_old_one_archived(self) -> None:
        for v in ("0.1.4", "0.1.5"):
            self.assertEqual(self.own(v).returncode, 0)
        url = self.public_site(f"{sha(b'qt')}  files/qt-6.0.tar.xz\n")        # uploaded: others, not this
        res = self.own("0.1.4", b"made again, smaller", "openhamshack-nb", "NB", "--replace-unpublished", url)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("replacing the never-uploaded", res.stdout)
        name = "openhamshack-nb-0.1.4-src.tar.gz"
        self.assertEqual((self.site / "files" / name).read_bytes(), b"made again, smaller")
        self.assertEqual((self.archive / "files" / name).read_bytes(), b"openhamshack-nb 0.1.4 source")
        self.assertEqual(self.own_names(), ["openhamshack-nb-0.1.5-src.tar.gz", name])    # its place kept
        manifest = (self.site / "manifests" / "openhamshack-nb.txt").read_text()
        self.assertIn(sha(b"made again, smaller"), manifest)
        self.assertNotIn(sha(b"openhamshack-nb 0.1.4 source"), manifest)
        self.assertEqual(self.tool("check", "openhamshack-nb").returncode, 0)

    def test_an_uploaded_or_unknowable_tarball_is_never_replaced(self) -> None:
        self.assertEqual(self.own("0.1.5").returncode, 0)
        name = "openhamshack-nb-0.1.5-src.tar.gz"
        for listing, serve, why in ((f"{sha(b'openhamshack-nb 0.1.5 source')}  files/{name}\n", False, "SHA256SUMS lists"),
                                    (None, False, "cannot be read"),
                                    ("", True, "is served")):        # uploaded, sums not yet
            url = self.public_site(listing)
            if serve:
                (self.root / "public" / "files" / name).write_bytes(b"openhamshack-nb 0.1.5 source")
            res = self.own("0.1.5", b"other bytes", "openhamshack-nb", "NB", "--replace-unpublished", url)
            self.assertNotEqual(res.returncode, 0, why)
            self.assertIn(why, res.stderr)
            self.assertEqual((self.site / "files" / name).read_bytes(), b"openhamshack-nb 0.1.5 source")
        self.assertFalse((self.archive / "files").exists())


if __name__ == "__main__":
    unittest.main()
