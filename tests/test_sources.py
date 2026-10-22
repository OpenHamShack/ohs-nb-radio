"""Behaviour tests for publishing the third-party source the Windows
installers owe, as the release flow does it: the gate in tools/release.sh
--windows, which publishes the app's manifest on the shared source site
before it will publish an installer, --retire-product-source, and the
product page's directions to the source site. The generator itself
(tools/source-site.py) is test_source_site.py's.

Each test runs the real tools in a scratch repository (test_site.make_repo)
whose packaging/windows/sources.txt names small stand-in tarballs reached
through file:// URLs, so fetching, hash-checking and refusing are
exercised exactly as against Qt's or SourceForge's servers - with no
network and never touching /srv. The "public" copy a --live check reads is
a scratch folder too, reached the same way.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

# Functions only: a TestCase class imported here would be run twice.
from test_source_site import list_line, sha
from test_site import (SCRATCH_MAC_SOURCES, SCRATCH_SOURCES, add_macos, built_dmg, commit, head, local_refs,
                       make_ham_repo, make_repo, release_env, run_ham_release, run_ham_site_build, run_release,
                       run_site_build, stub_build_deb, stub_build_deb_both)

if os.name == "nt":
    raise unittest.SkipTest("release.sh and the sites are built on the Linux host")

PUBLIC = "https://openhamshack.com/source/"


class WindowsReleaseNeedsTheSource(unittest.TestCase):
    """release.sh --windows publishes an installer only once its third-party
    source is complete on the shared source site."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"
        self.upstream = self.root / "upstream"
        self.site = self.root / "source-site"            # release_env's
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        incoming = self.root / "from-windows"
        incoming.mkdir()
        self.exe = incoming / "openhamshack-nb-0.4.0-setup.exe"
        self.exe.write_bytes(b"MZ installer")
        (incoming / f"{self.exe.name}.sha256").write_text(f"{sha(self.exe.read_bytes())}  {self.exe.name}\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add_windows(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--windows", str(self.exe)],
                              cwd=self.repo, env=release_env(self.repo, self.releases),
                              capture_output=True, text=True, timeout=60)

    def test_refuses_while_a_source_tarball_cannot_be_had(self) -> None:
        (self.upstream / "beta-2.0.tar.xz").unlink()
        res = self.add_windows()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not publishing", res.stderr)
        self.assertFalse((self.releases / self.exe.name).exists())
        self.assertNotIn("setup.exe", (self.releases / "index.html").read_text())
        # The manifest is there - the release published NB's own source -
        # but none of the installer's third-party list made it in.
        manifest = (self.site / "manifests" / "openhamshack-nb.txt").read_text()
        self.assertIn("@own openhamshack-nb-0.4.0-src.tar.gz", manifest)
        self.assertNotIn("alpha-1.0.tar.gz", manifest)

    def test_refuses_a_tarball_whose_bytes_are_not_the_pinned_ones(self) -> None:
        (self.upstream / "alpha-1.0.tar.gz").write_bytes(b"not the release")
        res = self.add_windows()
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse((self.releases / self.exe.name).exists())

    def test_publishes_the_source_on_the_source_site_and_the_page_links_there(self) -> None:
        res = self.add_windows()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.releases / self.exe.name).exists())
        for name, (data, _lic, _covers) in SCRATCH_SOURCES.items():
            self.assertEqual((self.site / "files" / name).read_bytes(), data)
        manifest = (self.site / "manifests" / "openhamshack-nb.txt").read_text()
        self.assertIn("@title OpenHamShack QO-100 NB", manifest)
        self.assertIn('id="openhamshack-nb"', (self.site / "index.html").read_text())
        # Nothing on the product site itself any more: a link, not a folder.
        self.assertFalse((self.releases / "source").exists())
        page = (self.releases / "index.html").read_text()
        self.assertIn("Source code for the bundled third-party components", page)
        self.assertIn(f'href="{PUBLIC}#openhamshack-nb"', page)
        self.assertIn("GPL and LGPL", page)
        self.assertNotIn('href="source/', page)
        for ref in local_refs(page):
            self.assertTrue((self.releases / ref).exists(), f"{ref} is referenced but missing")

    def test_tarballs_no_longer_listed_leave_the_source_site_with_the_old_installer(self) -> None:
        self.assertEqual(self.add_windows().returncode, 0)
        # The next installer no longer carries beta.
        lst = self.repo / "packaging" / "windows" / "sources.txt"
        lst.write_text("".join(l + "\n" for l in lst.read_text().splitlines() if not l.startswith("beta-")))
        commit(self.repo, "sources: beta is gone", allow_empty=False)
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        new = self.exe.with_name("openhamshack-nb-0.5.0-setup.exe")
        new.write_bytes(b"MZ installer 0.5.0")
        new.with_name(new.name + ".sha256").write_text(f"{sha(new.read_bytes())}  {new.name}\n")
        self.exe = new
        res = self.add_windows()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.site / "files" / "beta-2.0.tar.xz").exists())
        archived = self.root / "source-site-archive" / "files" / "beta-2.0.tar.xz"
        self.assertEqual(archived.read_bytes(), SCRATCH_SOURCES["beta-2.0.tar.xz"][0])
        source_list = res.stdout.split("remove from the remote source site:\n", 1)[1].split("published")[0]
        self.assertEqual([l.strip() for l in source_list.splitlines() if l.startswith("  ")],
                         ["files/beta-2.0.tar.xz"])
        product_list = res.stdout.split("remove from the remote site:\n", 1)[1]
        self.assertEqual(sorted(l.strip() for l in product_list.splitlines() if l.startswith("  ")),
                         ["openhamshack-nb-0.4.0-setup.exe", "openhamshack-nb-0.4.0-setup.exe.sha256"])

    def test_a_refused_publish_leaves_the_published_source_in_place(self) -> None:
        self.assertEqual(self.add_windows().returncode, 0)
        lst = self.repo / "packaging" / "windows" / "sources.txt"
        lst.write_text(lst.read_text().replace("beta-2.0.tar.xz", "beta-2.1.tar.xz"))
        commit(self.repo, "sources: beta 2.1, not fetchable", allow_empty=False)
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        before = (self.site / "manifests" / "openhamshack-nb.txt").read_text()   # with 0.5.0's own source
        new = self.exe.with_name("openhamshack-nb-0.5.0-setup.exe")
        new.write_bytes(b"MZ installer 0.5.0")
        new.with_name(new.name + ".sha256").write_text(f"{sha(new.read_bytes())}  {new.name}\n")
        self.exe = new
        self.assertNotEqual(self.add_windows().returncode, 0)
        self.assertEqual((self.site / "manifests" / "openhamshack-nb.txt").read_text(), before)
        self.assertTrue((self.site / "files" / "beta-2.0.tar.xz").exists())
        self.assertTrue((self.releases / "openhamshack-nb-0.4.0-setup.exe").exists())

    def test_a_source_site_filled_earlier_is_enough_offline(self) -> None:
        self.assertEqual(self.add_windows().returncode, 0)
        for p in self.upstream.iterdir():
            p.unlink()
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        new = self.exe.with_name("openhamshack-nb-0.5.0-setup.exe")
        new.write_bytes(b"MZ installer 0.5.0")
        new.with_name(new.name + ".sha256").write_text(f"{sha(new.read_bytes())}  {new.name}\n")
        self.exe = new
        res = self.add_windows()
        self.assertEqual(res.returncode, 0, res.stderr)


class HamWindowsReleaseNeedsTheSource(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        # A tarball only HAM's installer carries, as Paramiko is.
        lst = self.repo / "packaging" / "windows" / "sources.txt"
        lst.write_text(lst.read_text() + list_line(self.root / "upstream", "hamlib-1.0.tar.gz", b"ham only",
                                                   "LGPL-2.1", "HAM 0.1.0 onward (Windows)", "hamlib.dll") + "\n")
        stub_build_deb_both(self.repo)
        commit(self.repo, "stub build-deb.sh", allow_empty=False)
        self.releases = self.root / "ham-releases"
        self.site = self.root / "source-site"
        self.assertEqual(run_ham_release(self.repo, self.releases, "0.1.0").returncode, 0)
        self.exe = self.root / "openhamshack-radio-0.1.0-setup.exe"
        self.exe.write_bytes(b"MZ ham")
        (self.root / f"{self.exe.name}.sha256").write_text(f"{sha(b'MZ ham')}  {self.exe.name}\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refuses_without_the_source_and_publishes_with_it(self) -> None:
        (self.root / "upstream" / "hamlib-1.0.tar.gz").rename(self.root / "aside")
        res = run_ham_release(self.repo, self.releases, "--windows", str(self.exe))
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse((self.releases / self.exe.name).exists())
        (self.root / "aside").rename(self.root / "upstream" / "hamlib-1.0.tar.gz")
        res = run_ham_release(self.repo, self.releases, "--windows", str(self.exe))
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.releases / "index.html").read_text()
        self.assertIn("simulator-tested only", page)                 # HAM's page
        self.assertIn(f'href="{PUBLIC}#openhamshack-radio"', page)

    def test_hams_manifest_is_hams_and_nbs_is_left_alone(self) -> None:
        res = run_ham_release(self.repo, self.releases, "--windows", str(self.exe))
        self.assertEqual(res.returncode, 0, res.stderr)
        ham = (self.site / "manifests" / "openhamshack-radio.txt").read_text()
        self.assertIn("hamlib-1.0.tar.gz", ham)
        self.assertIn("alpha-1.0.tar.gz", ham)
        self.assertFalse((self.site / "manifests" / "openhamshack-nb.txt").exists())


class MacPreviewNeedsItsSource(unittest.TestCase):
    """release.sh --macos publishes the preview's own source (the commit it
    was built from) and its third-party list, as that commit had it, in a
    section of the source site of its own - and offers no image until both
    are there."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"
        self.upstream = self.root / "upstream"
        self.site = self.root / "source-site"
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        self.built = head(self.repo)
        self.dmg = built_dmg(self.root / "from-mac", "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_its_own_section_with_its_own_source_and_the_macs_list(self) -> None:
        windows_manifest = (self.site / "manifests" / "openhamshack-nb.txt").read_text()
        res = add_macos(self.repo, self.releases, self.dmg, self.built)
        self.assertEqual(res.returncode, 0, res.stderr)
        mac = (self.site / "manifests" / "openhamshack-nb-macos.txt").read_text()
        self.assertIn("@title OpenHamShack QO-100 NB for macOS (preview)", mac)
        own = "openhamshack-nb-0.4.0-mac-preview.1-src.tar.gz"
        self.assertIn(f"@own {own}", mac)
        self.assertIn(self.built, mac)
        self.assertIn("gamma-3.0.tar.gz", mac)
        self.assertIn("alpha-1.0.tar.gz", mac)
        self.assertNotIn("beta-2.0.tar.xz", mac)               # Windows' alone
        # The tarball is the build commit's tree, under the preview's name.
        with tarfile.open(self.site / "files" / own) as t:
            self.assertIn("openhamshack-nb-0.4.0-mac-preview.1/ohsnb/VERSION", t.getnames())
        for name, (data, _lic, _covers) in SCRATCH_MAC_SOURCES.items():
            self.assertEqual((self.site / "files" / name).read_bytes(), data)
        # The Windows installer's section is not touched.
        self.assertEqual((self.site / "manifests" / "openhamshack-nb.txt").read_text(), windows_manifest)
        self.assertIn('id="openhamshack-nb-macos"', (self.site / "index.html").read_text())

    def test_the_list_is_the_build_commits_not_mains(self) -> None:
        # main drops gamma after the build: the image still carries it.
        lst = self.repo / "packaging" / "macos" / "sources.txt"
        lst.write_text("".join(l + "\n" for l in lst.read_text().splitlines() if not l.startswith("gamma-")))
        commit(self.repo, "Mac sources: gamma is gone", allow_empty=False)
        res = add_macos(self.repo, self.releases, self.dmg, self.built)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("gamma-3.0.tar.gz", (self.site / "manifests" / "openhamshack-nb-macos.txt").read_text())

    def test_refuses_while_a_tarball_cannot_be_had(self) -> None:
        (self.upstream / "gamma-3.0.tar.gz").write_bytes(b"not the release")
        res = add_macos(self.repo, self.releases, self.dmg, self.built)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not publishing", res.stderr)
        self.assertFalse((self.releases / self.dmg.name).exists())
        self.assertNotIn(".dmg", (self.releases / "index.html").read_text())

    def test_hams_preview_is_hams(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_ham_repo(root)
            stub_build_deb_both(repo)
            commit(repo, "stub build-deb.sh", allow_empty=False)
            releases = root / "ham-releases"
            self.assertEqual(run_ham_release(repo, releases, "0.1.0").returncode, 0)
            dmg = built_dmg(root / "from-mac", "openhamshack-radio-0.1.0-mac-preview.1-arm64.dmg")
            res = add_macos(repo, releases, dmg, head(repo), "ham")
            self.assertEqual(res.returncode, 0, res.stderr)
            mac = (root / "source-site" / "manifests" / "openhamshack-radio-macos.txt").read_text()
            self.assertIn("@title OpenHamShack Radio for macOS (preview)", mac)
            self.assertIn("@own openhamshack-radio-0.1.0-mac-preview.1-src.tar.gz", mac)
            page = (releases / "index.html").read_text()
            self.assertIn(f'href="{PUBLIC}#openhamshack-radio-macos"', page)
            self.assertIn('"OpenHamShack Radio" was blocked', page)


class RetireProductSource(unittest.TestCase):
    """release.sh --retire-product-source: the product site's old source/
    folder goes to its archive, only once the public source site has it all."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh", allow_empty=False)
        self.releases = self.root / "releases"
        self.site = self.root / "source-site"
        self.public = self.root / "public"
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.root / "openhamshack-nb-0.4.0-setup.exe"
        exe.write_bytes(b"MZ installer")
        (self.root / f"{exe.name}.sha256").write_text(f"{sha(b'MZ installer')}  {exe.name}\n")
        res = subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--windows", str(exe)],
                             cwd=self.repo, env=release_env(self.repo, self.releases),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        # The folder an earlier release.sh left on the product site.
        self.old = self.releases / "source"
        self.old.mkdir()
        for name, (data, _lic, _covers) in SCRATCH_SOURCES.items():
            (self.old / name).write_bytes(data)
        (self.old / "README.txt").write_text("the old readme")
        (self.old / "SHA256SUMS").write_text("the old sums")
        (self.old / "index.html").write_text("the old listing")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def retire(self) -> subprocess.CompletedProcess:
        env = release_env(self.repo, self.releases)
        env["SOURCE_SITE_URL"] = self.public.as_uri() + "/"
        return subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--retire-product-source"],
                              cwd=self.repo, env=env, capture_output=True, text=True, timeout=60)

    def test_refuses_until_the_source_site_is_live(self) -> None:
        self.public.mkdir()
        res = self.retire()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("upload", res.stderr)
        self.assertEqual(sorted(p.name for p in self.old.iterdir()),
                         sorted([*SCRATCH_SOURCES, "README.txt", "SHA256SUMS", "index.html"]))
        self.assertFalse((self.root / "releases-archive").exists())

    def test_once_live_moves_the_folder_to_the_archive_and_leaves_a_pointer(self) -> None:
        shutil.copytree(self.site, self.public)
        res = self.retire()
        self.assertEqual(res.returncode, 0, res.stderr)
        archive = self.root / "releases-archive" / "source"
        for name, (data, _lic, _covers) in SCRATCH_SOURCES.items():
            self.assertEqual((archive / name).read_bytes(), data)
        self.assertEqual((archive / "README.txt").read_text(), "the old readme")
        self.assertEqual([p.name for p in self.old.iterdir()], ["index.html"])
        pointer = (self.old / "index.html").read_text()
        self.assertIn(f'href="{PUBLIC}#openhamshack-nb"', pointer)
        self.assertIn("http-equiv=\"refresh\"", pointer)
        tail = res.stdout.split("remove from the remote site:\n", 1)[1]
        self.assertEqual(sorted(l.strip() for l in tail.splitlines() if l.strip()),
                         sorted(f"source/{n}" for n in [*SCRATCH_SOURCES, "README.txt", "SHA256SUMS"]))
        self.assertIn(f'href="{PUBLIC}#openhamshack-nb"', (self.releases / "index.html").read_text())

    def test_nothing_to_retire_is_not_an_error(self) -> None:
        shutil.rmtree(self.old)
        res = self.retire()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("nothing to retire", res.stdout)


class ProductPageLinksToTheSourceSite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "openhamshack-nb_0.4.0_all.deb").write_bytes(b"nb")
        (self.out / "openhamshack-radio_0.1.0_all.deb").write_bytes(b"ham")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nbs_page_links_to_nbs_section(self) -> None:
        (self.out / "openhamshack-nb-0.4.0-setup.exe").write_bytes(b"MZ")
        self.assertEqual(run_site_build(self.repo, self.out).returncode, 0)
        page = (self.out / "index.html").read_text()
        self.assertIn(f'<a href="{PUBLIC}#openhamshack-nb">{PUBLIC}#openhamshack-nb</a>', page)
        self.assertIn("whose licences require their source", page)
        self.assertFalse((self.out / "source").exists())

    def test_hams_page_links_to_hams_section(self) -> None:
        (self.out / "openhamshack-radio-0.1.0-setup.exe").write_bytes(b"MZ")
        self.assertEqual(run_ham_site_build(self.repo, self.out).returncode, 0)
        page = (self.out / "index.html").read_text()
        self.assertIn(f'href="{PUBLIC}#openhamshack-radio"', page)
        self.assertNotIn("#openhamshack-nb", page)

    def test_no_installer_no_third_party_paragraph_but_the_own_source_is_named(self) -> None:
        self.assertEqual(run_site_build(self.repo, self.out).returncode, 0)
        page = (self.out / "index.html").read_text()
        self.assertNotIn("third-party components", page)
        # A .deb alone is still our GPL program, with ohsdigi compiled in.
        self.assertIn(f'<a href="{PUBLIC}#openhamshack-nb">{PUBLIC}#openhamshack-nb</a>', page)
        self.assertIn("OpenHamShack QO-100 NB is free software under the GNU GPL", page)
        self.assertIn("ohsdigi", page)

    def test_the_own_source_is_named_with_an_installer_too_and_for_ham_as_ham(self) -> None:
        (self.out / "openhamshack-radio-0.1.0-setup.exe").write_bytes(b"MZ")
        self.assertEqual(run_ham_site_build(self.repo, self.out).returncode, 0)
        page = (self.out / "index.html").read_text()
        self.assertIn("OpenHamShack Radio is free software under the GNU GPL", page)
        self.assertIn("third-party components", page)
        self.assertEqual(page.count('id="source"'), 1)


if __name__ == "__main__":
    unittest.main()
