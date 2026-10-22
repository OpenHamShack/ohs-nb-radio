"""Behaviour tests for the public site and its release tooling.

    python3 -m unittest discover -s tests

Everything here runs the real tools/site-build.py and tools/release.sh
against a scratch repository and a scratch release folder built for the
test - never this repository's own git history, and never
/srv/openhamshack-nb-releases. No assertion reads this repo's own source text;
each one is about what the built page, or the published folder, actually
contains after the tool ran.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import datetime
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

# release.sh is bash and publishes into a folder on the release host; the site is built
# there too. Under Windows Python (the Windows build runs this suite) there
# is no bash, sha256sum or dpkg-deb to drive, so these are skipped there.
if os.name == "nt":
    raise unittest.SkipTest("release.sh and the site are built on the Linux host")

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_BUILD = REPO_ROOT / "tools" / "site-build.py"
RELEASE_SH = REPO_ROOT / "tools" / "release.sh"

# A 1x1 PNG, hand-encoded, used only if Pillow is not installed - the same
# situation site-build.py itself falls back for.
_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000"
    "0090776153000000017352474200aece1ce90000000467414d410000"
    "b18f0bfc6105000000097048597300000ec300000ec301c76fa864000000"
    "0c4944415408d763f8cfc0000003010100185dd3f80000000049454e44"
    "ae426082")

spec = importlib.util.spec_from_file_location("site_build", SITE_BUILD)
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def _write_png(path: Path, size: tuple[int, int] = (120, 80)) -> None:
    if Image is not None:
        Image.new("RGB", size, (40, 60, 80)).save(path)
    else:
        path.write_bytes(_MIN_PNG)


def _git(repo: Path) -> list[str]:
    return ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def commit(repo: Path, message: str, *, allow_empty: bool = True) -> None:
    subprocess.run(_git(repo) + ["add", "-A"], check=True, capture_output=True)
    args = _git(repo) + ["commit", "-q", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    subprocess.run(args, check=True, capture_output=True, text=True)


def touch_commit(repo: Path, rel: str, message: str) -> None:
    """A commit that changes `rel`: release notes list a commit only for
    the files it touches, so an empty commit is in neither app's notes."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(message + "\n")
    commit(repo, message, allow_empty=False)


# Stand-ins for the third-party source tarballs release.sh --windows must
# have on the source site before it publishes an installer: two small files
# in a scratch "upstream" folder, reached through file:// URLs, so the real
# tools/source-site.py downloads and hash-checks them exactly as it does
# from Qt's or SourceForge's servers - without the network, and without
# the real list's 200 MB.
SCRATCH_SOURCES = {"alpha-1.0.tar.gz": (b"alpha source bytes", "GPL-3.0", "alpha.exe"),
                   "beta-2.0.tar.xz": (b"beta source bytes " * 3000, "LGPL-2.1-or-later", "beta.dll")}


def scratch_sources(root: Path, repo: Path) -> Path:
    """Write the upstream copies and the scratch repo's own
    packaging/windows/sources.txt naming them; returns the upstream folder
    (a test removes or changes a file there to see a fetch fail)."""
    upstream = root / "upstream"
    upstream.mkdir(exist_ok=True)
    lines = ["# scratch list for the tests", ""]
    for name, (data, licence, covers) in SCRATCH_SOURCES.items():
        (upstream / name).write_bytes(data)
        lines.append(f"{name} | {hashlib.sha256(data).hexdigest()} | {licence} | NB and HAM 0.1.4 onward | "
                     f"{covers} | {(upstream / name).as_uri()}")
    lines.append("> A closing note for README.txt.")
    (repo / "packaging" / "windows").mkdir(parents=True, exist_ok=True)
    (repo / "packaging" / "windows" / "sources.txt").write_text("\n".join(lines) + "\n")
    # The Mac's list (release.sh --macos): alpha shared with Windows, as the
    # real lists share libiio and codec2, and gamma the Mac's alone.
    mac = ["# scratch Mac list for the tests", ""]
    for name, (data, licence, covers) in {**{"alpha-1.0.tar.gz": SCRATCH_SOURCES["alpha-1.0.tar.gz"]},
                                          **SCRATCH_MAC_SOURCES}.items():
        (upstream / name).write_bytes(data)
        mac.append(f"{name} | {hashlib.sha256(data).hexdigest()} | {licence} | NB and HAM for macOS | "
                   f"{covers} | {(upstream / name).as_uri()}")
    (repo / "packaging" / "macos").mkdir(parents=True, exist_ok=True)
    (repo / "packaging" / "macos" / "sources.txt").write_text("\n".join(mac) + "\n")
    return upstream


SCRATCH_MAC_SOURCES = {"gamma-3.0.tar.gz": (b"gamma source bytes", "LGPL-2.1", "libgamma.dylib")}


# A stand-in for `osslsigncode verify`, which release.sh --windows runs on
# every installer (OSSLSIGNCODE names it). The installers here are a few
# bytes, not PE files, so the "signature" is a word in them: a file
# saying "unsigned" has none, "other-signer" is signed by someone else,
# "no-timestamp" has no countersignature; anything else verifies as 360
# Technology's, timestamped. The output has the lines release.sh reads, in
# osslsigncode 2.9's layout. Real osslsigncode is run on a real unsigned
# file in WindowsInstaller below.
FAKE_OSSLSIGNCODE = r"""#!/bin/bash
in=""
while (($#)); do [[ $1 == -in ]] && in=$2; shift; done
if grep -q unsigned "$in"; then echo "No signature found"; exit 1; fi
signer="/C=GB/ST=East Ayrshire/L=Kilmarnock/O=360 Technology/CN=360 Technology"
if grep -q other-signer "$in"; then signer="/C=US/O=Someone Else/CN=Someone Else"; fi
echo "Signer's certificate:"
printf '\tSigner #0:\n\t\tSubject: %s\n' "$signer"
if ! grep -q no-timestamp "$in"; then
    printf '\tTimestamp time: Oct  6 11:07:07 2026 GMT\n'
    echo "Timestamp Server Signature verification: ok"
fi
echo "Signature verification: ok"
echo "Succeeded"
"""


def make_repo(root: Path) -> Path:
    """A standalone copy of this project's site tooling - tools/, site/, a
    handful of synthetic screenshots, a minimal ohsnb/VERSION and a trivial
    test suite - as its own git repository unrelated to the real one.
    Everything release.sh and site-build.py read or write lives inside it,
    so running them for real here never touches the real repository or
    /srv/openhamshack-nb-releases."""
    repo = root / "repo"
    shutil.copytree(REPO_ROOT / "tools", repo / "tools")
    shutil.copytree(REPO_ROOT / "site", repo / "site")
    (repo / "docs" / "screenshots").mkdir(parents=True)
    for name, _caption in site.SHOTS[:3]:
        _write_png(repo / "docs" / "screenshots" / name)
    (repo / "ohsnb").mkdir()
    (repo / "ohsnb" / "VERSION").write_text("0.1.0\n")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_ok.py").write_text(
        "import unittest\n\n\nclass Ok(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
    scratch_sources(root, repo)
    pem = "microsoft-identity-verification-root-2020.pem"
    shutil.copy(REPO_ROOT / "packaging" / "windows" / pem, repo / "packaging" / "windows" / pem)
    (repo / "fake-osslsigncode").write_text(FAKE_OSSLSIGNCODE)
    (repo / "fake-osslsigncode").chmod(0o755)
    trust_scratch_release_key(root, repo)
    subprocess.run(_git(repo)[:3] + ["init", "-q"], check=True)
    commit(repo, "scratch base", allow_empty=False)
    return repo


def scratch_key(root: Path) -> Path:
    """Where a scratch repository's release key lives (release_env points
    $OPENHAMSHACK_RELEASE_KEY at it): beside the repository, as the real one
    lives outside the real repository."""
    return root / "release-key" / "ed25519.key"


def trust_scratch_release_key(root: Path, repo: Path) -> None:
    """Give the scratch repository what release.sh's update feed needs:
    ohscore/update.py (update-feed.py imports it), a release key made by
    update-feed.py keygen itself, and that key listed in the copy's
    RELEASE_KEYS - the line keygen prints is the line pasted in, as on
    the release host. The real repository's ohscore/update.py is untouched."""
    (repo / "ohscore").mkdir(exist_ok=True)
    for name in ("__init__.py", "update.py"):
        shutil.copy(REPO_ROOT / "ohscore" / name, repo / "ohscore" / name)
    # update.py's refusals are gettext sentences (ohscore/i18n/text.py), so
    # its import needs ohscore.i18n's two modules beside it.
    (repo / "ohscore" / "i18n").mkdir(exist_ok=True)
    for name in ("__init__.py", "text.py"):
        shutil.copy(REPO_ROOT / "ohscore" / "i18n" / name, repo / "ohscore" / "i18n" / name)
    res = subprocess.run([sys.executable, str(repo / "tools" / "update-feed.py"), "keygen", "--key",
                          str(scratch_key(root))], capture_output=True, text=True, check=True, timeout=60)
    line = next(ln.strip() for ln in res.stdout.splitlines() if ln.strip().startswith('("'))
    src = repo / "ohscore" / "update.py"
    text = src.read_text()
    # The scratch key is added beside whatever the real file lists (empty
    # before the first key was made, the real key since), so the copy
    # trusts it either way.
    head = "RELEASE_KEYS: tuple[tuple[str, str], ...] = ("
    assert head in text, "ohscore/update.py's RELEASE_KEYS line changed; update trust_scratch_release_key"
    src.write_text(text.replace(head + ")", head + line + ")", 1) if head + ")" in text
                   else text.replace(head, head + "\n    " + line, 1))


def stub_build_deb(repo: Path) -> None:
    """Replace the real tools/build-deb.sh with one that just writes a
    placeholder .deb under the expected name. release.sh's own gating,
    commit and site-build steps are what these tests check; whether
    build-deb.sh assembles a correct package is tools/test_packaging.py's
    job, not this file's, and a real build needs a full ohsnb/ and
    packaging/ tree that release.sh's behaviour does not."""
    script = repo / "tools" / "build-deb.sh"
    script.write_text('#!/bin/bash\nset -euo pipefail\narch=all\n'
                      'if [ "${1:-}" = --arch ]; then arch=$2; shift 2; fi\n'
                      'ver="${1:-$(tr -d " \\t\\r\\n" < ohsnb/VERSION)}"\n'
                      'echo "dummy $arch deb for $ver" > "openhamshack-nb_${ver}_${arch}.deb"\n')
    script.chmod(0o755)
    stub_build_ohsdigi(repo)


def stub_build_ohsdigi(repo: Path) -> None:
    """tools/build-ohsdigi.sh builds in a podman container; release.sh's
    tests need only its outputs, under the names it writes them."""
    script = repo / "tools" / "build-ohsdigi.sh"
    script.write_text('#!/bin/bash\nset -euo pipefail\n[ "$1" = --out ] && out=$2\n'
                      'for t in linux-amd64 linux-arm64; do mkdir -p "$out/$t"; echo so > "$out/$t/ohsdigi.abi3.so"; done\n'
                      'mkdir -p "$out/windows-amd64"; echo pyd > "$out/windows-amd64/ohsdigi.pyd"\n')
    script.chmod(0o755)


def run_site_build(repo: Path, out: Path, url: str = "https://example.invalid/") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo / "tools" / "site-build.py"), "--out", str(out), "--url", url],
                          capture_output=True, text=True, timeout=60)


def release_env(repo: Path, releases: Path) -> dict[str, str]:
    """What release.sh runs with in these tests: the scratch release folder,
    the stand-in osslsigncode, and a source site of this test's own beside
    the scratch repository (scratch_home already keeps it off /srv; this
    keeps one test's manifests out of the next's)."""
    return dict(os.environ, RELEASES=str(releases), OSSLSIGNCODE=str(repo / "fake-osslsigncode"),
                OHS_RELEASE_KEY=str(scratch_key(repo.parent)), OPENHAMSHACK_RELEASE_KEY=str(scratch_key(repo.parent)),
                SOURCE_SITE=str(repo.parent / "source-site"),
                SOURCE_SITE_ARCHIVE=str(repo.parent / "source-site-archive"),
                GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def run_release(repo: Path, ver: str, releases: Path) -> subprocess.CompletedProcess:
    env = release_env(repo, releases)
    return subprocess.run(["bash", str(repo / "tools" / "release.sh"), ver],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=120)


def local_refs(html_text: str) -> set[str]:
    """Every src=/href= in the page that points at a local file - i.e. not
    http(s), not mailto, not a bare in-page anchor."""
    refs = set(re.findall(r'(?:src|href)="([^"]+)"', html_text))
    return {r for r in refs if not re.match(r'^(https?:|mailto:|#)', r)}


def published(out: Path, source_name: str) -> list[Path]:
    """The files in out/shots/ made from docs' `source_name`: site-build.py
    names each after its own bytes (<stem>-<hash>.<ext>, and sm-<stem>-...
    for a shrunk inline copy)."""
    stem = Path(source_name).stem
    shots = out / "shots"
    if not shots.is_dir():
        return []
    return sorted(p for p in shots.iterdir()
                  if re.fullmatch(rf"(sm-)?{re.escape(stem)}-[0-9a-f]{{12}}\.(jpg|png)", p.name))


def page_images(page: str) -> list[tuple[str, int, int, str]]:
    """(src, width, height, the whole tag) for every <img> in a page; a tag
    without both dimensions fails the test that reads it."""
    out = []
    for tag in re.findall(r"<img\b[^>]*>", page):
        src = re.search(r'src="([^"]+)"', tag).group(1)
        w = re.search(r'width="(\d+)"', tag)
        h = re.search(r'height="(\d+)"', tag)
        if not (w and h):
            raise AssertionError(f"{tag} has no width and height")
        out.append((src, int(w.group(1)), int(h.group(1)), tag))
    return out


def image_size(path: Path) -> tuple[int, int]:
    if Image is not None:
        with Image.open(path) as im:
            return im.size
    return site._png_size(path.read_bytes())


def utc_today() -> str:
    """What tools/sitemap_sync.py stamps a changed page with - UTC, not
    whatever the test host's local date happens to be, so this never
    flakes on a host west of Greenwich just before local midnight."""
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class SiteBuildPlaceholdersAndFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.out = self.root / "out"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def deb_bytes(self) -> bytes:
        return b"not a real package, just test bytes for openhamshack-nb 0.3.0"

    def place_deb(self, ver: str = "0.3.0", with_sha: bool = True) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        deb = self.out / f"openhamshack-nb_{ver}_all.deb"
        deb.write_bytes(self.deb_bytes())
        if with_sha:
            sha = hashlib.sha256(deb.read_bytes()).hexdigest()
            (self.out / f"{deb.name}.sha256").write_text(f"{sha}  {deb.name}\n")
        return deb

    def test_every_placeholder_is_substituted(self) -> None:
        self.place_deb()
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertNotRegex(page, r"\{\{[A-Z_]+\}\}")

    def test_every_local_reference_in_the_page_exists_on_disk(self) -> None:
        self.place_deb()
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        refs = local_refs(page)
        self.assertTrue(refs, "page referenced no local files at all")
        for ref in refs:
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing from {self.out}")

    def test_download_link_and_checksum_match_the_published_deb_with_sha_file(self) -> None:
        deb = self.place_deb("0.3.0", with_sha=True)
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertIn(f'href="{deb.name}"', page)
        expected_sha = hashlib.sha256(deb.read_bytes()).hexdigest()
        self.assertIn(expected_sha, page)
        self.assertIn(f"sudo apt install ./{deb.name}", page)

    def test_checksum_is_recomputed_when_no_sha_file_was_written(self) -> None:
        deb = self.place_deb("0.3.0", with_sha=False)
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertIn(hashlib.sha256(deb.read_bytes()).hexdigest(), page)

    def test_version_badge_names_the_newest_deb_by_version_not_by_filename_sort(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        for ver in ("0.2.0", "0.10.0", "0.3.0"):  # string sort would put 0.10.0 before 0.2.0
            (self.out / f"openhamshack-nb_{ver}_all.deb").write_bytes(f"deb {ver}".encode())
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertIn('<span class="badge">0.10.0</span>', page)
        self.assertIn("openhamshack-nb_0.10.0_all.deb", page)

    def test_a_release_with_per_architecture_debs_offers_each_and_installs_amd64(self) -> None:
        # From ohsdigi on, a release is three packages; the older one beside
        # them, "all" only, is not offered.
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "openhamshack-nb_0.1.4_all.deb").write_bytes(b"old")
        for arch in ("amd64", "arm64", "all"):
            (self.out / f"openhamshack-nb_0.2.0_{arch}.deb").write_bytes(arch.encode())
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertIn('<span class="badge">0.2.0</span>', page)
        for arch in ("amd64", "arm64", "all"):
            self.assertIn(f'href="openhamshack-nb_0.2.0_{arch}.deb"', page)
        self.assertIn("sudo apt install ./openhamshack-nb_0.2.0_amd64.deb", page)
        self.assertIn("Raspberry Pi", page)
        self.assertNotIn("openhamshack-nb_0.1.4_all.deb", page)

    def test_no_deb_yet_builds_a_page_that_says_so_instead_of_failing(self) -> None:
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        self.assertIn("No release has been published yet", page)
        self.assertNotRegex(page, r"\{\{[A-Z_]+\}\}")

    def test_screenshots_present_in_source_are_published_and_shown(self) -> None:
        self.place_deb()
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "index.html").read_text()
        for name, _caption in site.SHOTS[:3]:
            self.assertTrue(published(self.out, name), name)
        shown = page_images(page)
        self.assertEqual(len(shown), 3)
        for src, w, h, attrs in shown:
            self.assertTrue((self.out / src).exists(), src)
            self.assertEqual((w, h), image_size(self.out / src), src)
            self.assertIn('loading="lazy"', attrs)

    def test_screenshots_absent_from_source_are_silently_skipped(self) -> None:
        self.place_deb()
        # SHOTS[3:] were never written into docs/screenshots by make_repo().
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        for name, _caption in site.SHOTS[3:]:
            self.assertFalse(published(self.out, name), name)


@unittest.skipIf(Image is None, "Pillow is needed to make and measure screenshots")
class ScreenshotsForTheWeb(unittest.TestCase):
    """docs/screenshots' PNGs are the source; what the site serves is made
    from them: the smaller of PNG and JPEG, an inline copy that is never
    bigger than the full-size file, named after its own bytes so it can be
    cached for a year, and old names moved to the archive, not deleted."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "openhamshack-nb_0.3.0_all.deb").write_bytes(b"deb")
        self.docs = self.repo / "docs" / "screenshots"
        self.names = [n for n, _c in site.SHOTS[:3]]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self) -> subprocess.CompletedProcess:
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res

    def shown(self) -> dict[str, tuple[Path, Path, tuple[int, int]]]:
        """{source stem: (inline file, full-size file, the <img>'s size)}"""
        page = (self.out / "index.html").read_text()
        out = {}
        for m in re.finditer(r'<a href="(shots/[^"]+)"><img src="(shots/[^"]+)" width="(\d+)" height="(\d+)"', page):
            full, small = self.out / m.group(1), self.out / m.group(2)
            stem = re.sub(r"^sm-|-[0-9a-f]{12}\.\w+$", "", full.name)
            out[stem] = (small, full, (int(m.group(3)), int(m.group(4))))
        return out

    def test_a_busy_wide_screenshot_is_a_smaller_jpeg_with_a_960_wide_inline_copy(self) -> None:
        # Gaussian noise on a dark field: what a waterfall looks like to a
        # compressor, and what made the PNG thumbnails half a megabyte.
        src = self.docs / self.names[0]
        Image.effect_noise((1920, 1080), 30).convert("RGB").save(src)
        self.build()
        small, full, size = self.shown()[Path(self.names[0]).stem]
        self.assertEqual(full.suffix, ".jpg")
        self.assertEqual(small.suffix, ".jpg")
        self.assertLess(full.stat().st_size, src.stat().st_size)
        self.assertLess(small.stat().st_size, full.stat().st_size)
        self.assertEqual(size, (960, 540))
        self.assertEqual(image_size(small), (960, 540))
        self.assertEqual(image_size(full), (1920, 1080))
        from PIL import JpegImagePlugin
        for f in (small, full):           # no chroma subsampling (4:4:4): thin coloured lines survive
            with Image.open(f) as im:
                self.assertEqual(JpegImagePlugin.get_sampling(im), 0, f.name)

    def test_a_dialog_barely_wider_than_the_page_is_shown_as_itself_never_a_bigger_copy(self) -> None:
        # settings-radio.png (980x720) was resampled to 960 and came out 75%
        # bigger than itself; a flat dialog like it is now shown full size.
        src = self.docs / self.names[1]
        im = Image.new("RGB", (980, 720), (24, 28, 36))
        for i in range(0, 700, 40):
            im.paste((60, 70, 90), (20, i, 960, i + 18))
        im.save(src)
        self.build()
        small, full, size = self.shown()[Path(self.names[1]).stem]
        self.assertEqual(small, full)
        self.assertEqual(size, (980, 720))
        self.assertLessEqual(full.stat().st_size, src.stat().st_size)

    def test_no_inline_copy_is_ever_bigger_than_its_full_size_file(self) -> None:
        Image.effect_noise((1920, 1080), 30).convert("RGB").save(self.docs / self.names[0])
        Image.new("RGB", (1600, 900), (10, 12, 18)).save(self.docs / self.names[1])
        Image.new("RGB", (980, 720), (200, 200, 200)).save(self.docs / self.names[2])
        self.build()
        shown = self.shown()
        self.assertEqual(len(shown), 3)
        for stem, (small, full, _size) in shown.items():
            self.assertLessEqual(small.stat().st_size, full.stat().st_size, stem)

    def test_a_screenshot_that_uses_transparency_stays_png(self) -> None:
        im = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
        im.paste((200, 50, 50, 255), (50, 50, 250, 150))
        im.save(self.docs / self.names[0])
        self.build()
        small, full, _size = self.shown()[Path(self.names[0]).stem]
        self.assertEqual(full.suffix, ".png")
        with Image.open(full) as out:
            self.assertEqual(out.getchannel("A").getextrema()[0], 0)

    def test_names_follow_the_bytes_and_a_rerender_archives_the_old_files(self) -> None:
        src = self.docs / self.names[0]
        Image.effect_noise((1920, 1080), 30).convert("RGB").save(src)
        self.build()
        first = set(published(self.out, self.names[0]))
        self.assertEqual(len(first), 2)                       # full size and inline
        again = self.build()
        self.assertEqual(set(published(self.out, self.names[0])), first)   # same bytes, same names
        self.assertNotIn("remove from the remote site", again.stdout)

        Image.effect_noise((1920, 1080), 60).convert("RGB").save(src)      # re-rendered
        res = self.build()
        now = set(published(self.out, self.names[0]))
        self.assertEqual(len(now), 2)
        self.assertFalse(now & first)
        archive = self.root / "out-archive" / "shots"
        for old in first:
            self.assertTrue((archive / old.name).is_file(), old.name)        # moved, never deleted
            self.assertIn(f"shots/{old.name}", res.stdout)                 # and listed for the public host
        page = (self.out / "index.html").read_text()
        for ref in local_refs(page):
            self.assertTrue((self.out / ref).exists(), ref)


class ReleaseNotesFromCommits(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.out = self.root / "out"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build(self) -> str:
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        return (self.out / "index.html").read_text()

    def test_notes_are_grouped_under_the_release_they_belong_to(self) -> None:
        touch_commit(self.repo, "ohsnb/foo.py", "Add foo")
        commit(self.repo, "Release 0.2.0")
        touch_commit(self.repo, "ohsnb/bar.py", "Fix bar")
        commit(self.repo, "Release 0.3.0")
        page = self.build()
        i020, i030 = page.index("0.2.0"), page.index("0.3.0")
        self.assertLess(i030, i020, "newest release's notes must come first")
        # "Fix bar" happened after 0.2.0 was cut, so it belongs to 0.3.0, not 0.2.0.
        between_030_and_020 = page[i030:i020]
        self.assertIn("Fix bar", between_030_and_020)
        self.assertNotIn("Add foo", between_030_and_020)
        self.assertIn("Add foo", page[i020:])

    def test_release_marker_commits_and_merges_do_not_appear_as_notes(self) -> None:
        commit(self.repo, "Add foo")
        commit(self.repo, "Release 0.2.0")
        page = self.build()
        self.assertNotIn("<li>Release 0.2.0</li>", page)
        self.assertNotIn("Merge branch", page)

    def test_no_release_commit_yet_says_so_rather_than_failing(self) -> None:
        commit(self.repo, "Add foo")
        page = self.build()
        self.assertEqual(run_site_build(self.repo, self.out).returncode, 0)
        self.assertIn("No tagged release yet", page)


class ReleaseScriptRefusals(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.releases = self.root / "releases"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refuses_a_dirty_tree(self) -> None:
        (self.repo / "ohsnb" / "scratch.txt").write_text("uncommitted")
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("uncommitted changes", res.stderr)
        self.assertFalse(self.releases.exists())

    def test_refuses_a_version_already_published(self) -> None:
        self.releases.mkdir()
        existing = self.releases / "openhamshack-nb_0.5.0_all.deb"
        existing.write_bytes(b"already here")
        before_log = subprocess.run(_git(self.repo) + ["log", "--format=%s"],
                                    check=True, capture_output=True, text=True).stdout
        res = run_release(self.repo, "0.5.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already published", res.stderr)
        self.assertEqual(existing.read_bytes(), b"already here")  # not overwritten
        after_log = subprocess.run(_git(self.repo) + ["log", "--format=%s"],
                                   check=True, capture_output=True, text=True).stdout
        self.assertEqual(before_log, after_log, "a refused release must not commit")

    def test_refuses_when_the_tests_fail(self) -> None:
        (self.repo / "tests" / "test_ok.py").write_text(
            "import unittest\n\n\nclass Broken(unittest.TestCase):\n"
            "    def test_fails(self):\n        self.fail('deliberately broken')\n")
        commit(self.repo, "break the tests")
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("tests fail", res.stderr)
        self.assertFalse(self.releases.exists())


class ReleasePublishesForReal(unittest.TestCase):
    """release.sh run end to end against a scratch repo and a scratch
    release folder - exactly how a test should exercise it, and never how
    a person should: this is the one place that is allowed to."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_release_writes_version_commits_and_publishes_deb_sha_and_site(self) -> None:
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertEqual(res.returncode, 0, res.stderr)

        self.assertEqual((self.repo / "ohsnb" / "VERSION").read_text().strip(), "0.4.0")
        log = subprocess.run(_git(self.repo) + ["log", "-1", "--format=%s"],
                             check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(log, "Release 0.4.0")
        status = subprocess.run(_git(self.repo) + ["status", "--porcelain"],
                                check=True, capture_output=True, text=True).stdout
        self.assertEqual(status, "", "release.sh must leave a clean tree behind")

        deb = self.releases / "openhamshack-nb_0.4.0_all.deb"
        self.assertTrue(deb.exists())
        sha_file = self.releases / "openhamshack-nb_0.4.0_all.deb.sha256"
        self.assertTrue(sha_file.exists())
        self.assertEqual(sha_file.read_text().split()[0], hashlib.sha256(deb.read_bytes()).hexdigest())

        page = (self.releases / "index.html").read_text()
        self.assertIn('<span class="badge">0.4.0</span>', page)
        self.assertIn("openhamshack-nb_0.4.0_all.deb", page)
        self.assertIn("Release 0.4.0", log)  # sanity: the commit this release notes itself from exists

        # One package per architecture ohsdigi is built for, each with its
        # checksum, and the ohsdigi binaries kept beside the site, not on it:
        # the .pyd there is the one the Windows build must take.
        for arch in ("amd64", "arm64"):
            deb = self.releases / f"openhamshack-nb_0.4.0_{arch}.deb"
            self.assertTrue(deb.exists(), arch)
            sha = (self.releases / f"{deb.name}.sha256").read_text().split()[0]
            self.assertEqual(sha, hashlib.sha256(deb.read_bytes()).hexdigest())
        built = self.root / "releases-build" / "openhamshack-nb-0.4.0-ohsdigi"
        self.assertTrue((built / "windows-amd64" / "ohsdigi.pyd").exists())
        self.assertIn(str(built / "windows-amd64" / "ohsdigi.pyd"), res.stdout)
        self.assertFalse(any(p.suffix in (".so", ".pyd") for p in self.releases.rglob("*")))

        # The release commit's own source: made into the build folder and
        # published in NB's section of the source site, as the commit
        # itself (the tarball is that commit's tree).
        ball = self.root / "releases-build" / "openhamshack-nb-0.4.0-src.tar.gz"
        with tarfile.open(ball) as t:
            self.assertEqual(t.extractfile("openhamshack-nb-0.4.0/ohsnb/VERSION").read(), b"0.4.0\n")
        source_site = self.root / "source-site"
        self.assertEqual((source_site / "files" / ball.name).read_bytes(), ball.read_bytes())
        manifest = (source_site / "manifests" / "openhamshack-nb.txt").read_text()
        head = subprocess.run(_git(self.repo) + ["rev-parse", "HEAD"], check=True, capture_output=True,
                              text=True).stdout.strip()
        self.assertIn(f"@own {ball.name} | {hashlib.sha256(ball.read_bytes()).hexdigest()} | GPL-3.0-or-later", manifest)
        self.assertIn(head, manifest)
        self.assertIn("<h3>OpenHamShack QO-100 NB's own source, per release</h3>", (source_site / "index.html").read_text())

    def test_refuses_to_publish_anything_when_its_source_cannot_be_published(self) -> None:
        # The source site already has a different file under this version's
        # tarball name: publish-own refuses it, and so nothing of the
        # version may appear.
        decoy = self.root / "openhamshack-nb-0.4.0-src.tar.gz"
        decoy.write_bytes(b"some other tarball")
        env = release_env(self.repo, self.releases)
        subprocess.run([sys.executable, str(self.repo / "tools" / "source-site.py"), "publish-own", "openhamshack-nb",
                        str(decoy), "--licence", "GPL-3.0-or-later", "--carried", "x", "--covers", "x"],
                       env=env, check=True, capture_output=True)
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("own source could not be published", res.stderr)
        self.assertEqual(list(self.releases.glob("*.deb")), [])
        self.assertFalse((self.root / "releases-build" / "openhamshack-nb-0.4.0-ohsdigi").exists())

    def test_a_second_release_builds_on_the_first_without_clobbering_it(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        touch_commit(self.repo, "ohsnb/radio.py", "Add something worth a changelog line")
        res = run_release(self.repo, "0.5.0", self.releases)
        self.assertEqual(res.returncode, 0, res.stderr)
        # Each release's own source stays published beside the next.
        manifest = (self.root / "source-site" / "manifests" / "openhamshack-nb.txt").read_text()
        self.assertIn("@own openhamshack-nb-0.5.0-src.tar.gz", manifest)
        self.assertIn("@own openhamshack-nb-0.4.0-src.tar.gz", manifest)
        # Both .debs stay published; the site now headlines the new one but
        # still has the old one's bytes on disk if anyone has the old link.
        self.assertTrue((self.releases / "openhamshack-nb_0.4.0_all.deb").exists())
        self.assertTrue((self.releases / "openhamshack-nb_0.5.0_all.deb").exists())
        page = (self.releases / "index.html").read_text()
        self.assertIn('<span class="badge">0.5.0</span>', page)
        self.assertIn("Add something worth a changelog line", page)


class WindowsInstaller(unittest.TestCase):
    """release.sh --windows adds an installer built elsewhere to a release
    already published, and the page offers it only once it is there."""

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

    def built_exe(self, ver: str, good_sha: bool = True, signature: str = "") -> Path:
        exe = self.incoming / f"openhamshack-nb-{ver}-setup.exe"
        exe.write_bytes(f"MZ installer {ver} {signature}".encode())
        sha = hashlib.sha256(exe.read_bytes() if good_sha else b"other bytes").hexdigest()
        (self.incoming / f"{exe.name}.sha256").write_text(f"{sha}  {exe.name}\n")
        return exe

    def add_windows(self, exe: Path, osslsigncode: str | None = None, *extra: str) -> subprocess.CompletedProcess:
        env = release_env(self.repo, self.releases)
        if osslsigncode:
            env["OSSLSIGNCODE"] = osslsigncode
        return subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--windows", str(exe), *extra],
                              cwd=self.repo, env=env, capture_output=True, text=True, timeout=60)

    def refused(self, res: subprocess.CompletedProcess, exe: Path, why: str) -> None:
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(why, res.stderr)
        self.assertFalse((self.releases / exe.name).exists())
        self.assertNotIn(exe.name, self.page())

    def test_refuses_an_unsigned_installer(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0", signature="unsigned")
        self.refused(self.add_windows(exe), exe, "no valid Authenticode signature")

    def test_allow_unsigned_publishes_a_beta_build_with_no_signature(self) -> None:
        # BETA-PLAN: installers are unsigned for the beta.
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0", signature="unsigned")
        res = self.add_windows(exe, None, "--allow-unsigned")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("UNSIGNED", res.stderr)
        self.assertTrue((self.releases / exe.name).exists())

    def test_allow_unsigned_never_passes_a_wrong_signature(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        for sig, why in (("other-signer", "not 360 Technology"), ("no-timestamp", "without a valid timestamp")):
            exe = self.built_exe("0.4.0", signature=sig)
            self.refused(self.add_windows(exe, None, "--allow-unsigned"), exe, why)

    def test_refuses_one_signed_by_anyone_else(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0", signature="other-signer")
        self.refused(self.add_windows(exe), exe, "not 360 Technology")

    def test_refuses_a_signature_without_a_timestamp(self) -> None:
        # The certificate lives three days; without a timestamp the
        # installer would stop verifying soon after it was published.
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0", signature="no-timestamp")
        self.refused(self.add_windows(exe), exe, "without a valid timestamp")

    def test_refuses_when_the_signature_cannot_be_checked_at_all(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0")
        res = self.add_windows(exe, osslsigncode=str(self.root / "no-such-osslsigncode"))
        self.refused(res, exe, "osslsigncode is not installed")

    @unittest.skipUnless(shutil.which("osslsigncode"), "osslsigncode is not installed (apt install osslsigncode)")
    def test_the_real_osslsigncode_refuses_an_unsigned_installer(self) -> None:
        # No stand-in: the check release.sh really runs, on a file with no
        # signature, against the root kept in packaging/windows/.
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0")
        self.refused(self.add_windows(exe, osslsigncode="osslsigncode"), exe, "no valid Authenticode signature")

    def page(self) -> str:
        return (self.releases / "index.html").read_text()

    def test_a_release_without_one_offers_no_windows_download(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        self.assertNotIn("setup.exe", self.page())
        self.assertNotIn("Windows 10/11", self.page())

    def test_a_ham_installer_in_the_folder_is_never_nbs_download(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        (self.releases / "openhamshack-radio-0.4.0-setup.exe").write_bytes(b"MZ ham")
        self.assertEqual(run_site_build(self.repo, self.releases).returncode, 0)
        self.assertNotIn("setup.exe", self.page())

    def test_the_installer_from_an_earlier_release_is_offered_until_the_next_one(self) -> None:
        # A new release's .debs are on the page; the installer on offer is
        # still the last one's until its own arrives, and an older .deb is
        # never mistaken for the newest.
        (self.releases).mkdir(parents=True, exist_ok=True)
        (self.releases / "openhamshack-nb_0.3.0_all.deb").write_bytes(b"old deb")
        (self.releases / "openhamshack-nb-0.3.0-setup.exe").write_bytes(b"MZ old")
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        page = self.page()
        self.assertIn('href="openhamshack-nb-0.3.0-setup.exe"', page)
        self.assertIn('href="openhamshack-nb_0.4.0_all.deb"', page)
        self.assertNotIn('href="openhamshack-nb_0.3.0_all.deb"', page)

    def test_adding_it_publishes_exe_and_sha_and_the_page_offers_both(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        exe = self.built_exe("0.4.0")
        res = self.add_windows(exe)
        self.assertEqual(res.returncode, 0, res.stderr)
        published = self.releases / exe.name
        self.assertEqual(published.read_bytes(), exe.read_bytes())
        self.assertTrue((self.releases / f"{exe.name}.sha256").exists())
        page = self.page()
        self.assertIn(f'href="{exe.name}"', page)
        self.assertIn(hashlib.sha256(exe.read_bytes()).hexdigest(), page)
        self.assertIn("Run anyway", page)
        self.assertIn("openhamshack-nb_0.4.0_all.deb", page)    # the .deb is still offered beside it
        for ref in local_refs(page):
            self.assertTrue((self.releases / ref).exists(), f"{ref} is referenced but missing")

    def test_refuses_a_copy_that_does_not_match_its_checksum(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        res = self.add_windows(self.built_exe("0.4.0", good_sha=False))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("does not match", res.stderr)
        self.assertFalse((self.releases / "openhamshack-nb-0.4.0-setup.exe").exists())

    def test_refuses_an_installer_for_another_version(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        res = self.add_windows(self.built_exe("0.3.9"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ohsnb/VERSION is 0.4.0", res.stderr)

    def test_refuses_before_the_release_itself_is_published(self) -> None:
        res = self.add_windows(self.built_exe("0.1.0"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not published", res.stderr)
        self.assertFalse((self.releases / "openhamshack-nb-0.1.0-setup.exe").exists())

    def test_a_newer_installer_moves_the_older_one_to_the_archive(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        old = self.built_exe("0.4.0")
        self.assertEqual(self.add_windows(old).returncode, 0)
        old_bytes = old.read_bytes()
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        new = self.built_exe("0.5.0")
        res = self.add_windows(new)
        self.assertEqual(res.returncode, 0, res.stderr)
        archive = self.root / "releases-archive"
        self.assertFalse((self.releases / old.name).exists())
        self.assertFalse((self.releases / f"{old.name}.sha256").exists())
        self.assertEqual((archive / old.name).read_bytes(), old_bytes)
        self.assertTrue((archive / f"{old.name}.sha256").exists())
        self.assertTrue((self.releases / new.name).exists())
        # Older .debs stay on the site; only installers go.
        self.assertTrue((self.releases / "openhamshack-nb_0.4.0_all.deb").exists())
        # The upload side is told, by site path, exactly what to delete there.
        tail = res.stdout.split("remove from the remote site:\n", 1)[1]
        self.assertEqual(sorted(l.strip() for l in tail.splitlines() if l.strip()),
                         sorted([old.name, f"{old.name}.sha256"]))
        page = self.page()
        self.assertNotIn(old.name, page)
        self.assertIn(f'href="{new.name}"', page)
        for ref in local_refs(page):
            self.assertTrue((self.releases / ref).exists(), f"{ref} is referenced but missing")

    def test_the_first_installer_has_nothing_to_remove(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        res = self.add_windows(self.built_exe("0.4.0"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("nothing to remove from the remote site", res.stdout)
        self.assertFalse((self.root / "releases-archive").exists())

    def test_never_replaces_a_published_installer(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        first = self.built_exe("0.4.0")
        self.assertEqual(self.add_windows(first).returncode, 0)
        original = (self.releases / first.name).read_bytes()
        first.write_bytes(b"MZ different bytes")
        sha = hashlib.sha256(first.read_bytes()).hexdigest()
        (self.incoming / f"{first.name}.sha256").write_text(f"{sha}  {first.name}\n")
        res = self.add_windows(first)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already published", res.stderr)
        self.assertEqual((self.releases / first.name).read_bytes(), original)


def head(repo: Path) -> str:
    return subprocess.run(_git(repo) + ["rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def built_dmg(folder: Path, name: str, data: bytes = b"", good_sha: bool = True) -> Path:
    """A stand-in disk image as build-macos.sh leaves one: the file and its
    .sha256 (shasum -a 256's format, which sha256sum -c reads)."""
    folder.mkdir(exist_ok=True)
    dmg = folder / name
    dmg.write_bytes(data or f"koly image {name}".encode())
    sha = hashlib.sha256(dmg.read_bytes() if good_sha else b"other bytes").hexdigest()
    (folder / f"{name}.sha256").write_text(f"{sha}  {name}\n")
    return dmg


def add_macos(repo: Path, releases: Path, dmg: Path, commit_id: str, *app: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(repo / "tools" / "release.sh"), *app, "--macos", str(dmg),
                           "--commit", commit_id], cwd=repo, env=release_env(repo, releases),
                          capture_output=True, text=True, timeout=120)


class MacPreview(unittest.TestCase):
    """release.sh --macos puts a labelled, unsigned Mac preview on the site
    (Brian, 07/10/2026): its own source first, the update feed untouched,
    and a page that tells a Mac user what they are getting."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"
        self.site = self.root / "source-site"
        self.incoming = self.root / "from-mac"
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        # Built from main after the release, as the first preview was.
        touch_commit(self.repo, "ohsnb/mac.py", "Mac support after 0.4.0")
        self.built = head(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def page(self) -> str:
        return (self.releases / "index.html").read_text()

    def test_publishes_the_image_and_a_page_section_that_says_what_it_is(self) -> None:
        feed = (self.releases / "update.json").read_bytes()
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")
        res = add_macos(self.repo, self.releases, dmg, self.built)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.releases / dmg.name).read_bytes(), dmg.read_bytes())
        self.assertTrue((self.releases / f"{dmg.name}.sha256").exists())
        page = self.page()
        self.assertIn(f'href="{dmg.name}"', page)
        self.assertIn(hashlib.sha256(dmg.read_bytes()).hexdigest(), page)
        for words in ("macOS (preview)", "unsigned", "0.4.0+mac-preview.1", "Apple Silicon", "macOS 14",
                      "Open Anyway", "Privacy &amp; Security", "microphone", "Local Network", "ip:192.168.2.1",
                      "SoapySDR", "JS8", "FreeDV 2020", "no WSJT-X is needed",
                      "https://openhamshack.com/source/#openhamshack-nb-macos"):
            self.assertIn(words, page)
        # The app carries no Intel code since 17/10/2026 (tools/build-macos.sh).
        self.assertNotIn("Rosetta", page)
        for ref in local_refs(page):
            self.assertTrue((self.releases / ref).exists(), f"{ref} is referenced but missing")
        # Not offered to installed copies: the feed is byte for byte as it was.
        self.assertEqual((self.releases / "update.json").read_bytes(), feed)
        self.assertIn("the update feed is unchanged", res.stdout)

    def test_a_release_without_one_says_nothing_about_macos(self) -> None:
        self.assertNotIn("macOS", self.page())
        self.assertNotIn(".dmg", self.page())

    def test_the_next_release_neither_feeds_it_nor_drops_it_from_the_page(self) -> None:
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")
        self.assertEqual(add_macos(self.repo, self.releases, dmg, self.built).returncode, 0)
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        feed = json.loads((self.releases / "update.json").read_text())
        self.assertEqual({f["platform"] for f in feed["files"]}, {"linux"})
        self.assertIn(f'href="{dmg.name}"', self.page())

    def test_a_newer_preview_replaces_the_older_one(self) -> None:
        first = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")
        self.assertEqual(add_macos(self.repo, self.releases, first, self.built).returncode, 0)
        touch_commit(self.repo, "ohsnb/mac.py", "A Mac fix")
        second = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.2-arm64.dmg")
        res = add_macos(self.repo, self.releases, second, head(self.repo))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.releases / first.name).exists())
        self.assertTrue((self.root / "releases-archive" / first.name).exists())
        self.assertIn(f"remove from the remote site:\n  {first.name}\n  {first.name}.sha256", res.stdout)
        page = self.page()
        self.assertNotIn(first.name, page)
        self.assertIn("0.4.0+mac-preview.2", page)

    def refused(self, res: subprocess.CompletedProcess, dmg: Path, why: str) -> None:
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(why, res.stderr)
        self.assertFalse((self.releases / dmg.name).exists())
        self.assertNotIn(dmg.name, self.page())
        self.assertFalse((self.site / "manifests" / "openhamshack-nb-macos.txt").exists())

    def test_refuses_an_unlabelled_image(self) -> None:
        # A release .dmg belongs in the update feed, which waits for a signed build.
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-arm64.dmg")
        self.refused(add_macos(self.repo, self.releases, dmg, self.built), dmg, "only a labelled preview")

    def test_refuses_the_other_apps_image_or_another_version(self) -> None:
        for name in ("openhamshack-radio-0.4.0-mac-preview.1-arm64.dmg", "openhamshack-nb-0.3.0-mac-preview.1-arm64.dmg"):
            dmg = built_dmg(self.incoming, name)
            self.refused(add_macos(self.repo, self.releases, dmg, self.built), dmg, "is not openhamshack-nb-0.4.0-")

    def test_refuses_a_version_whose_release_is_not_published(self) -> None:
        (self.repo / "ohsnb" / "VERSION").write_text("0.6.0\n")
        commit(self.repo, "VERSION ahead of any release", allow_empty=False)
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.6.0-mac-preview.1-arm64.dmg")
        self.refused(add_macos(self.repo, self.releases, dmg, head(self.repo)), dmg, "release 0.6.0 is not published")

    def test_refuses_a_damaged_copy(self) -> None:
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg", good_sha=False)
        self.refused(add_macos(self.repo, self.releases, dmg, self.built), dmg, "does not match its .sha256")

    def test_refuses_a_commit_that_is_not_in_this_branchs_history(self) -> None:
        subprocess.run(_git(self.repo) + ["checkout", "-q", "-b", "side"], check=True)
        touch_commit(self.repo, "ohsnb/side.py", "On a side branch")
        side = head(self.repo)
        subprocess.run(_git(self.repo) + ["checkout", "-q", "-"], check=True)
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")
        self.refused(add_macos(self.repo, self.releases, dmg, side), dmg, "not in this branch's history")
        self.refused(add_macos(self.repo, self.releases, dmg, "0" * 40), dmg, "is not a commit")

    def test_never_replaces_a_published_image(self) -> None:
        dmg = built_dmg(self.incoming, "openhamshack-nb-0.4.0-mac-preview.1-arm64.dmg")
        self.assertEqual(add_macos(self.repo, self.releases, dmg, self.built).returncode, 0)
        original = (self.releases / dmg.name).read_bytes()
        dmg = built_dmg(self.incoming, dmg.name, b"different bytes")
        res = add_macos(self.repo, self.releases, dmg, self.built)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already published", res.stderr)
        self.assertEqual((self.releases / dmg.name).read_bytes(), original)


class UserGuidePage(unittest.TestCase):
    """docs/USERGUIDE.md published as guide.html, and the front page's links
    to it - present exactly when the guide is."""

    GUIDE = (
        "# Test guide\n\n"
        "Intro with `code`, **bold**, *italic* and ip:<address> kept as text.\n\n"
        "## Installing on Windows\n\n"
        "1. First step:\n"
        "   - a sub-item\n"
        "2. Second step, see [the table](#the-table).\n\n"
        "## The table\n\n"
        "| Keys | Does |\n| --- | --- |\n| **Group** | |\n| Ctrl + 1 | USB |\n\n"
        "```\nsudo apt install ./x.deb\n```\n\n"
        "![A shot](screenshots/one.png)\n\n"
        "<!-- hidden comment -->\n")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "openhamshack-nb_0.3.0_all.deb").write_bytes(b"deb")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def with_guide(self, text: str | None = None) -> None:
        (self.repo / "docs" / "USERGUIDE.md").write_text(text if text is not None else self.GUIDE)
        _write_png(self.repo / "docs" / "screenshots" / "one.png")

    def build(self) -> subprocess.CompletedProcess:
        return run_site_build(self.repo, self.out)

    def test_without_a_guide_there_is_no_page_and_no_link(self) -> None:
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.out / "guide.html").exists())
        self.assertNotIn("guide.html", (self.out / "index.html").read_text())

    def test_the_guide_renders_and_the_front_page_links_to_it(self) -> None:
        self.with_guide()
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "guide.html").read_text()
        self.assertNotRegex(page, r"\{\{[A-Z_]+\}\}")
        self.assertIn('<h2 id="installing-on-windows">Installing on Windows</h2>', page)
        self.assertIn("<code>code</code>", page)
        self.assertIn("<b>bold</b>", page)
        self.assertIn("<i>italic</i>", page)
        self.assertIn("ip:&lt;address&gt;", page)          # text, not swallowed as a tag
        self.assertIn("<li>a sub-item</li>", page)
        self.assertIn('<a href="#the-table">', page)
        self.assertIn('<tr class="sub">', page)
        self.assertIn('data-label="Keys"', page)
        self.assertIn("sudo apt install ./x.deb", page)
        self.assertNotIn("hidden comment", page)
        self.assertNotIn("Test guide</h1>", page)          # the page header carries the title
        self.assertTrue(published(self.out, "one.png"))
        for ref in local_refs(page):
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")
        ids = set(re.findall(r'id="([^"]+)"', page))
        for anchor in re.findall(r'href="#([^"]+)"', page):
            self.assertIn(anchor, ids)
        self.assertIn('href="guide.html"', (self.out / "index.html").read_text())

    def test_a_heading_that_skips_a_level_is_shown_one_below_its_parent(self) -> None:
        # HAM's guide has "## Settings" then "#### Station": on the page
        # that was an h2 followed by h4s.
        self.with_guide("# G\n\n## Settings\n\n#### Station\n\nA.\n\n#### Radio\n\n### Below radio\n\n"
                        "## Next\n\n### Fine\n\n#### Also fine\n")
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "guide.html").read_text()
        outline = re.findall(r'<h(\d) id="([^"]+)"', page)
        self.assertEqual(outline, [("2", "settings"), ("3", "station"), ("3", "radio"), ("3", "below-radio"),
                                   ("2", "next"), ("3", "fine"), ("4", "also-fine")])
        levels = [1] + [int(lv) for lv, _a in outline]
        for before, after in zip(levels, levels[1:]):
            self.assertLessEqual(after, before + 1)
        self.assertIn('href="#settings"', page)        # the contents still list the ## headings
        self.assertNotIn('href="#station"', page)

    def test_a_missing_screenshot_fails_the_build_rather_than_publishing_a_broken_page(self) -> None:
        self.with_guide("# G\n\n![Gone](screenshots/not-there.png)\n")
        res = self.build()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not-there.png", res.stderr + res.stdout)

    def test_the_windows_download_links_to_the_guides_windows_section(self) -> None:
        self.with_guide()
        exe = self.out / "openhamshack-nb-0.3.0-setup.exe"
        exe.write_bytes(b"MZ")
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        index = (self.out / "index.html").read_text()
        self.assertIn(f'href="{exe.name}"', index)
        self.assertIn('href="guide.html#installing-on-windows"', index)
        self.assertIn('id="installing-on-windows"', (self.out / "guide.html").read_text())

    def test_the_real_guide_builds_with_every_image_and_anchor_present(self) -> None:
        real = REPO_ROOT / "docs" / "USERGUIDE.md"
        if not real.exists():
            self.skipTest("no docs/USERGUIDE.md in this checkout")
        if not (REPO_ROOT / "docs" / "screenshots").is_dir():
            # A release's source tarball leaves the screenshots out
            # (.gitattributes); its SOURCE-NOTES.txt says how to render them.
            self.skipTest("no docs/screenshots in this tree (a source tarball)")
        shutil.copy2(real, self.repo / "docs" / "USERGUIDE.md")
        shutil.copytree(REPO_ROOT / "docs" / "screenshots", self.repo / "docs" / "screenshots", dirs_exist_ok=True)
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "guide.html").read_text()
        for ref in local_refs(page):
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")
        ids = set(re.findall(r'id="([^"]+)"', page))
        for anchor in re.findall(r'href="#([^"]+)"', page):
            self.assertIn(anchor, ids, f"#{anchor} has no heading")
        self.assertIn('id="installing-on-windows"', page)   # the front page's Windows link lands here


class SitemapSync(unittest.TestCase):
    """tools/site-build.py keeps another session's sitemap.xml and
    robots.txt (06/10/2026) current: a page's <lastmod> moves to today only
    when that page's bytes actually changed, a page not yet listed gets a
    <url> of its own, and nothing the tool did not write - an unrelated
    entry, robots.txt, the file's very existence - is ever touched. Never
    created from nothing: placing the file in the first place is the other
    session's job, not this tool's."""

    OLD = "2020-01-01"
    BASE = "https://example.invalid/"   # what run_site_build's --url already uses by default

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        self.out = self.root / "out"
        self.out.mkdir()
        (self.out / "openhamshack-nb_0.3.0_all.deb").write_bytes(b"deb")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def seed(self, entries: list[tuple[str, str]]) -> None:
        """entries: (path under BASE, lastmod) - "" for the home page."""
        body = "".join(f'  <url><loc>{self.BASE}{p}</loc><lastmod>{d}</lastmod></url>\n' for p, d in entries)
        (self.out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + '</urlset>\n')

    def build(self) -> subprocess.CompletedProcess:
        return run_site_build(self.repo, self.out, self.BASE)

    def sitemap(self) -> str:
        return (self.out / "sitemap.xml").read_text()

    def test_never_created_when_absent(self) -> None:
        res = self.build()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.out / "sitemap.xml").exists())

    def test_unchanged_page_keeps_its_date(self) -> None:
        # Build for real content first, stamp the home entry OLD as if it
        # had been that way for years, then build again with nothing in
        # the repo or the folder different: the page comes out byte for
        # byte the same as before, so the date must not move either.
        self.assertEqual(self.build().returncode, 0)
        self.seed([("", self.OLD)])
        self.assertEqual(self.build().returncode, 0)
        self.assertIn(f"<lastmod>{self.OLD}</lastmod>", self.sitemap())

    def test_changed_page_gets_todays_lastmod(self) -> None:
        self.assertEqual(self.build().returncode, 0)
        self.seed([("", self.OLD)])
        # A different .deb under the same name changes the page's checksum
        # line - a real difference in what gets published, not a no-op.
        (self.out / "openhamshack-nb_0.3.0_all.deb").write_bytes(b"deb, but not the same bytes as before")
        self.assertEqual(self.build().returncode, 0)
        self.assertIn(f"<loc>{self.BASE}</loc><lastmod>{utc_today()}</lastmod>", self.sitemap())

    def test_a_new_page_gets_a_url_entry(self) -> None:
        self.seed([("", self.OLD)])   # guide.html does not exist yet, so it is not listed
        (self.repo / "docs" / "USERGUIDE.md").write_text("# G\n\nHello.\n")
        self.assertEqual(self.build().returncode, 0)
        self.assertIn(f"<loc>{self.BASE}guide.html</loc><lastmod>{utc_today()}</lastmod>", self.sitemap())

    def test_unrelated_entries_are_preserved(self) -> None:
        self.seed([("", self.OLD), ("blog/post-1.html", "2019-05-05")])
        self.assertEqual(self.build().returncode, 0)
        self.assertIn(f"<loc>{self.BASE}blog/post-1.html</loc><lastmod>2019-05-05</lastmod>", self.sitemap())

    def test_shots_downloads_and_the_source_pointer_are_never_listed(self) -> None:
        self.seed([("", self.OLD)])
        (self.out / "source").mkdir()   # a legacy per-product source/ folder, as source_html() expects
        (self.repo / "docs" / "USERGUIDE.md").write_text("# G\n\n![Shot](screenshots/one.png)\n")
        _write_png(self.repo / "docs" / "screenshots" / "one.png")
        (self.out / "openhamshack-nb-0.3.0-setup.exe").write_bytes(b"MZ")
        self.assertEqual(self.build().returncode, 0)
        self.assertTrue((self.out / "source" / "index.html").exists())   # the pointer page was written
        sm = self.sitemap()
        for bad in ("shots/", "source/", ".deb", ".exe"):
            self.assertNotIn(bad, sm, f"{bad!r} must never be a sitemap entry")

    def test_robots_txt_is_untouched(self) -> None:
        self.seed([("", self.OLD)])
        robots = "User-agent: *\nAllow: /\nSitemap: https://example.invalid/sitemap.xml\n"
        (self.out / "robots.txt").write_text(robots)
        self.assertEqual(self.build().returncode, 0)
        self.assertEqual((self.out / "robots.txt").read_text(), robots)


# --------------------------------------------------------------------------- OpenHamShack Radio
#
# The same tools with --app ham / `release.sh ham`: HAM's own templates
# (site/ham/), guide (docs/ham/USERGUIDE.md), screenshots, package name,
# release marker ("Release HAM x.y.z") and release notes limited to HAM's
# own files. Every test runs the real tools in a scratch repository, as
# above.

def make_ham_repo(root: Path) -> Path:
    """make_repo() plus what HAM's build reads: ohsradio/VERSION, a HAM
    screenshot or two and a file under ohsradio/ for the notes to find."""
    repo = make_repo(root)
    (repo / "ohsradio").mkdir()
    (repo / "ohsradio" / "VERSION").write_text("0.1.0\n")
    shots = repo / "docs" / "ham" / "screenshots"
    shots.mkdir(parents=True)
    for name, _caption in site.HAM_SHOTS[:2]:
        _write_png(shots / name)
    commit(repo, "scratch ham base", allow_empty=False)
    return repo


def stub_build_deb_both(repo: Path) -> None:
    """A build-deb.sh stand-in taking build-deb.sh's real arguments,
    [nb|ham] [--arch A] [version], and writing a placeholder under the
    right name."""
    script = repo / "tools" / "build-deb.sh"
    script.write_text('#!/bin/bash\nset -euo pipefail\napp=nb\narch=all\n'
                      'if [ "${1:-}" = nb ] || [ "${1:-}" = ham ]; then app=$1; shift; fi\n'
                      'if [ "${1:-}" = --arch ]; then arch=$2; shift 2; fi\n'
                      'case $app in nb) pkg=openhamshack-nb ;; ham) pkg=openhamshack-radio ;; esac\n'
                      'echo "dummy $app $arch deb for $1" > "${pkg}_${1}_${arch}.deb"\n')
    script.chmod(0o755)
    stub_build_ohsdigi(repo)


def run_ham_site_build(repo: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo / "tools" / "site-build.py"), "--app", "ham", "--out", str(out),
                           "--url", "https://example.invalid/"], capture_output=True, text=True, timeout=60)


def run_ham_release(repo: Path, releases: Path, *args: str) -> subprocess.CompletedProcess:
    env = release_env(repo, releases)
    return subprocess.run(["bash", str(repo / "tools" / "release.sh"), "ham", *args],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=120)


class HamSite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def place(self, name: str, data: bytes) -> Path:
        p = self.out / name
        p.write_bytes(data)
        return p

    def build(self) -> str:
        res = run_ham_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        return (self.out / "index.html").read_text()

    def test_offers_the_ham_deb_with_its_checksum_and_never_an_nb_one(self) -> None:
        deb = self.place("openhamshack-radio_0.1.0_all.deb", b"ham package bytes")
        self.place("openhamshack-nb_0.9.0_all.deb", b"nb package bytes")    # a stray NB package
        page = self.build()
        self.assertNotRegex(page, r"\{\{[A-Z_]+\}\}")
        self.assertIn(f'href="{deb.name}"', page)
        self.assertIn(hashlib.sha256(b"ham package bytes").hexdigest(), page)
        self.assertIn(f"sudo apt install ./{deb.name}", page)
        self.assertIn("0.1.0 preview", page)
        self.assertNotIn("openhamshack-nb_0.9.0_all.deb", page)
        for ref in local_refs(page):
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")

    def test_says_it_is_a_simulator_tested_preview_and_has_no_windows_installer_yet(self) -> None:
        self.place("openhamshack-radio_0.1.0_all.deb", b"ham")
        self.place("openhamshack-nb-0.9.0-setup.exe", b"MZ nb")     # NB's installer is never HAM's download
        page = self.build()
        self.assertIn("Preview — simulator-tested only; nothing tried on real radios or on air yet", page)
        self.assertIn("No Windows installer has been published yet", page)
        self.assertNotIn("setup.exe", page)
        self.assertIn("openhamshack.com/desktop/nb/", page)   # the sibling link

    def test_offers_hams_windows_installer_once_there_is_one(self) -> None:
        self.place("openhamshack-radio_0.2.0_all.deb", b"ham")
        exe = self.place("openhamshack-radio-0.2.0-setup.exe", b"MZ ham installer")
        self.place("openhamshack-nb-0.9.0-setup.exe", b"MZ nb")
        page = self.build()
        self.assertIn(f'href="{exe.name}"', page)
        self.assertIn(hashlib.sha256(b"MZ ham installer").hexdigest(), page)
        self.assertIn("Run anyway", page)
        self.assertIn("PlutoSDR USB drivers", page)               # offered by the installer, not a download
        self.assertNotIn("(not 1.0)", page)
        self.assertIn("Hermes-Lite 2", page)                      # HAM's own note: the firewall
        self.assertNotIn("No Windows installer", page)
        self.assertNotIn("openhamshack-nb-0.9.0-setup.exe", page)
        for ref in local_refs(page):
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")

    def test_uses_hams_own_favicon_and_screenshots(self) -> None:
        self.place("openhamshack-radio_0.1.0_all.deb", b"ham")
        self.build()
        self.assertEqual((self.out / "favicon.svg").read_bytes(),
                         (self.repo / "site" / "ham" / "favicon.svg").read_bytes())
        for name, _caption in site.HAM_SHOTS[:2]:
            self.assertTrue(published(self.out, name), name)
        for name, _caption in site.HAM_SHOTS[2:]:
            self.assertFalse(published(self.out, name), name)

    def test_no_deb_yet_says_so(self) -> None:
        page = self.build()
        self.assertIn("No release has been published yet", page)
        self.assertIn("unreleased", page)

    def test_the_guide_is_hams_and_the_front_page_links_to_it(self) -> None:
        self.place("openhamshack-radio_0.1.0_all.deb", b"ham")
        (self.repo / "docs" / "ham" / "USERGUIDE.md").write_text(
            "# HAM guide\n\n## Transmitting safely\n\nThe licence guard.\n\n"
            f"![A shot](screenshots/{site.HAM_SHOTS[0][0]})\n")
        (self.repo / "docs" / "USERGUIDE.md").write_text("# NB guide\n\n## Beacon lock\n\nNot HAM's.\n")
        page = self.build()
        self.assertIn('href="guide.html"', page)
        guide = (self.out / "guide.html").read_text()
        self.assertNotRegex(guide, r"\{\{[A-Z_]+\}\}")
        self.assertIn('id="transmitting-safely"', guide)
        self.assertNotIn("Beacon lock", guide)
        self.assertIn("OpenHamShack Radio user guide", guide)
        for ref in local_refs(guide):
            self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")

    def test_the_real_ham_guide_builds_with_every_image_and_anchor_present(self) -> None:
        real = REPO_ROOT / "docs" / "ham" / "USERGUIDE.md"
        if not real.exists():
            self.skipTest("no docs/ham/USERGUIDE.md in this checkout")
        if not (REPO_ROOT / "docs" / "ham" / "screenshots").is_dir():
            self.skipTest("no docs/ham/screenshots in this tree (a source tarball)")
        shutil.copy2(real, self.repo / "docs" / "ham" / "USERGUIDE.md")
        shutil.copytree(REPO_ROOT / "docs" / "ham" / "screenshots", self.repo / "docs" / "ham" / "screenshots",
                        dirs_exist_ok=True)
        self.place("openhamshack-radio_0.1.0_all.deb", b"ham")
        index = self.build()
        guide = (self.out / "guide.html").read_text()
        for page in (index, guide):
            for ref in local_refs(page):
                self.assertTrue((self.out / ref).exists(), f"{ref} is referenced but missing")
        ids = set(re.findall(r'id="([^"]+)"', guide))
        for anchor in re.findall(r'href="#([^"]+)"', guide):
            self.assertIn(anchor, ids, f"#{anchor} has no heading")
        self.assertIn('id="not-yet-verified"', guide)


class HamReleaseNotes(unittest.TestCase):
    """One repository, two apps: each site's notes come from its own release
    commits, and HAM's only from commits touching HAM's files."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        self.out = self.root / "out"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def touch(self, rel: str, message: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(message)
        commit(self.repo, message, allow_empty=False)

    def test_each_app_reads_only_its_own_release_commits_and_ham_only_its_own_files(self) -> None:
        self.touch("ohsradio/radio.py", "HAM: a band simulator")
        self.touch("ohsnb/radio.py", "NB: beacon lock tweak")
        commit(self.repo, "Release 0.2.0")              # NB's
        self.touch("ohsradio/guard.py", "HAM: the licence guard")
        commit(self.repo, "Release HAM 0.1.0")          # HAM's
        res = run_ham_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        ham = (self.out / "index.html").read_text()
        self.assertIn("0.1.0", ham)
        self.assertNotIn("0.2.0", ham)
        self.assertIn("HAM: the licence guard", ham)
        self.assertIn("HAM: a band simulator", ham)
        self.assertNotIn("NB: beacon lock tweak", ham)
        self.assertNotIn("Release HAM", ham)
        nb_out = self.root / "nb"
        res = run_site_build(self.repo, nb_out)
        self.assertEqual(res.returncode, 0, res.stderr)
        nb = (nb_out / "index.html").read_text()
        self.assertIn("<h3>0.2.0", nb)
        self.assertNotIn("<h3>0.1.0", nb)                # HAM's release is not NB's

    def test_nb_notes_are_the_commits_nb_is_built_from_and_none_of_hams(self) -> None:
        # NB's notes used to list every commit, so a release after HAM's
        # first would have been mostly HAM's work.
        commit(self.repo, "Release 0.2.0")
        self.touch("ohsnb/radio.py", "NB: beacon lock tweak")
        self.touch("ohscore/engine.py", "Core: a fix both apps ship")
        self.touch("tools/build-deb.sh", "Tooling: the .deb both apps are built by")
        self.touch("docs/USERGUIDE.md", "NB guide: a correction")
        self.touch("ohsradio/guard.py", "HAM: the licence guard")
        self.touch("docs/ham/USERGUIDE.md", "HAM guide: a correction")
        self.touch("ohscore/devices/hl2.py", "HL2: a driver fix only HAM uses")
        self.touch("packaging/openhamshack-radio.desktop", "HAM: its menu entry")
        self.touch("tests/test_x.py", "Tests: only a test")
        self.touch("HANDOVER.md", "Handover: where things stand")
        commit(self.repo, "Release 0.3.0")
        res = run_site_build(self.repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        nb = (self.out / "index.html").read_text()
        notes = nb[nb.index("<h3>0.3.0"):nb.index("<h3>0.2.0")]
        for line in ("NB: beacon lock tweak", "Core: a fix both apps ship",
                     "Tooling: the .deb both apps are built by", "NB guide: a correction"):
            self.assertIn(line, notes)
        for line in ("HAM: the licence guard", "HAM guide: a correction", "HL2: a driver fix only HAM uses",
                     "HAM: its menu entry", "Tests: only a test", "Handover: where things stand"):
            self.assertNotIn(line, nb)


class HamRelease(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_ham_repo(self.root)
        stub_build_deb_both(self.repo)
        commit(self.repo, "stub build-deb.sh", allow_empty=False)
        self.releases = self.root / "ham-releases"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_publishes_the_ham_deb_sha_and_site_and_commits_its_own_marker(self) -> None:
        res = run_ham_release(self.repo, self.releases, "0.1.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.repo / "ohsradio" / "VERSION").read_text().strip(), "0.1.0")
        log = subprocess.run(_git(self.repo) + ["log", "-1", "--format=%s"],
                             check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(log, "Release HAM 0.1.0")
        deb = self.releases / "openhamshack-radio_0.1.0_all.deb"
        self.assertTrue(deb.exists())
        self.assertFalse(list(self.releases.glob("openhamshack-nb_*")))
        sha = (self.releases / "openhamshack-radio_0.1.0_all.deb.sha256").read_text().split()[0]
        self.assertEqual(sha, hashlib.sha256(deb.read_bytes()).hexdigest())
        page = (self.releases / "index.html").read_text()
        self.assertIn("0.1.0 preview", page)
        self.assertIn(sha, page)
        self.assertIn("simulator-tested only", page)
        status = subprocess.run(_git(self.repo) + ["status", "--porcelain"],
                                check=True, capture_output=True, text=True).stdout
        self.assertEqual(status, "")
        # HAM's own source goes in HAM's section, under HAM's name.
        source_site = self.root / "source-site"
        self.assertIn("@own openhamshack-radio-0.1.0-src.tar.gz",
                      (source_site / "manifests" / "openhamshack-radio.txt").read_text())
        self.assertFalse((source_site / "manifests" / "openhamshack-nb.txt").exists())
        self.assertIn("<h3>OpenHamShack Radio's own source, per release</h3>", (source_site / "index.html").read_text())

    def test_refuses_a_version_already_published(self) -> None:
        self.releases.mkdir()
        (self.releases / "openhamshack-radio_0.1.0_all.deb").write_bytes(b"already here")
        res = run_ham_release(self.repo, self.releases, "0.1.0")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already published", res.stderr)
        self.assertEqual((self.releases / "openhamshack-radio_0.1.0_all.deb").read_bytes(), b"already here")

    def test_an_nb_deb_of_the_same_version_does_not_block_ham(self) -> None:
        self.releases.mkdir()
        (self.releases / "openhamshack-nb_0.1.0_all.deb").write_bytes(b"nb")
        self.assertEqual(run_ham_release(self.repo, self.releases, "0.1.0").returncode, 0)

    def built_exe(self, name: str) -> Path:
        incoming = self.root / "from-windows"
        incoming.mkdir(exist_ok=True)
        exe = incoming / name
        exe.write_bytes(f"MZ {name}".encode())
        (incoming / f"{name}.sha256").write_text(f"{hashlib.sha256(exe.read_bytes()).hexdigest()}  {name}\n")
        return exe

    def test_adds_hams_windows_installer_and_the_ham_page_offers_it(self) -> None:
        self.assertEqual(run_ham_release(self.repo, self.releases, "0.1.0").returncode, 0)
        exe = self.built_exe("openhamshack-radio-0.1.0-setup.exe")
        res = run_ham_release(self.repo, self.releases, "--windows", str(exe))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.releases / exe.name).read_bytes(), exe.read_bytes())
        self.assertTrue((self.releases / f"{exe.name}.sha256").exists())
        page = (self.releases / "index.html").read_text()
        self.assertIn(f'href="{exe.name}"', page)
        self.assertIn("simulator-tested only", page)              # HAM's page, rebuilt as HAM's
        self.assertIn("openhamshack-radio_0.1.0_all.deb", page)

    def test_refuses_nbs_installer_given_as_hams(self) -> None:
        self.assertEqual(run_ham_release(self.repo, self.releases, "0.1.0").returncode, 0)
        res = run_ham_release(self.repo, self.releases, "--windows",
                              str(self.built_exe("openhamshack-nb-0.1.0-setup.exe")))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("is not openhamshack-radio-0.1.0-setup.exe", res.stderr)
        self.assertFalse((self.releases / "openhamshack-nb-0.1.0-setup.exe").exists())

    def test_refuses_hams_installer_for_another_version_or_before_its_release(self) -> None:
        res = run_ham_release(self.repo, self.releases, "--windows",
                              str(self.built_exe("openhamshack-radio-0.1.0-setup.exe")))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not published", res.stderr)
        self.assertEqual(run_ham_release(self.repo, self.releases, "0.1.0").returncode, 0)
        res = run_ham_release(self.repo, self.releases, "--windows",
                              str(self.built_exe("openhamshack-radio-0.0.9-setup.exe")))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ohsradio/VERSION is 0.1.0", res.stderr)


class SitemapAndRobotsSurviveRelease(unittest.TestCase):
    """robots.txt and sitemap.xml (another session's, 06/10/2026) must ride
    through everything release.sh does to a release folder - a normal
    release, archiving a superseded Windows installer, retiring a legacy
    per-product source/ folder, and the source site's own prune - none of
    which has anything to do with either file, so none of it may move or
    remove them."""

    SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               '  <url><loc>https://openhamshacknb.brian-henderson.co.uk/</loc><lastmod>2020-01-01</lastmod></url>\n'
               '</urlset>\n')
    ROBOTS = "User-agent: *\nAllow: /\nSitemap: https://openhamshacknb.brian-henderson.co.uk/sitemap.xml\n"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = make_repo(self.root)
        stub_build_deb(self.repo)
        commit(self.repo, "stub build-deb.sh for the release test", allow_empty=False)
        self.releases = self.root / "releases"
        self.releases.mkdir()
        (self.releases / "sitemap.xml").write_text(self.SITEMAP)
        (self.releases / "robots.txt").write_text(self.ROBOTS)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def assert_survived(self, folder: Path | None = None, sitemap: str | None = None,
                        robots: str | None = None) -> None:
        folder = folder or self.releases
        self.assertTrue((folder / "sitemap.xml").exists())
        self.assertEqual((folder / "robots.txt").read_text(), robots if robots is not None else self.ROBOTS)
        # The server-level files site-build.py writes ride through all of it too.
        if folder == self.releases:
            self.assertTrue((folder / ".htaccess").is_file())
            self.assertTrue((folder / "404.html").is_file())

    def test_survives_a_normal_release(self) -> None:
        res = run_release(self.repo, "0.4.0", self.releases)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_survived()
        # This run really is the first time index.html exists in the
        # folder, so the home entry's date must have moved off the
        # placeholder - proof the regeneration ran, not just that the file
        # happened to survive untouched.
        self.assertIn(f"<lastmod>{utc_today()}</lastmod>", (self.releases / "sitemap.xml").read_text())

    def test_survives_archiving_a_superseded_windows_installer(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        incoming = self.root / "from-windows"
        incoming.mkdir()

        def exe(ver: str) -> Path:
            p = incoming / f"openhamshack-nb-{ver}-setup.exe"
            p.write_bytes(f"MZ {ver}".encode())
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            (incoming / f"{p.name}.sha256").write_text(f"{sha}  {p.name}\n")
            return p

        env = release_env(self.repo, self.releases)

        def add(exe_path: Path) -> subprocess.CompletedProcess:
            return subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--windows", str(exe_path)],
                                  cwd=self.repo, env=env, capture_output=True, text=True, timeout=60)

        self.assertEqual(add(exe("0.4.0")).returncode, 0)
        self.assertEqual(run_release(self.repo, "0.5.0", self.releases).returncode, 0)
        res = add(exe("0.5.0"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_survived()
        archive = self.root / "releases-archive"
        self.assertFalse((archive / "sitemap.xml").exists())
        self.assertFalse((archive / "robots.txt").exists())

    def test_survives_retiring_a_legacy_source_folder(self) -> None:
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        # --retire-product-source refuses unless the public source site
        # already shows this package complete; a "public" copy reached by
        # file:// stands in for an upload, exactly as the source-site
        # tests' own --live checks do.
        public = self.root / "public-source-site"
        shutil.copytree(self.root / "source-site", public)
        (self.releases / "source").mkdir()
        (self.releases / "source" / "old-lib-1.0.tar.gz").write_bytes(b"old")
        (self.releases / "source" / "index.html").write_text("<html>old pointer</html>")
        env = release_env(self.repo, self.releases)
        env["SOURCE_SITE_URL"] = public.as_uri() + "/"
        res = subprocess.run(["bash", str(self.repo / "tools" / "release.sh"), "--retire-product-source"],
                             cwd=self.repo, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.root / "releases-archive" / "source" / "old-lib-1.0.tar.gz").exists())
        self.assert_survived()

    def test_survives_the_source_sites_own_prune(self) -> None:
        # tools/source-site.py build's own prune step (every release runs
        # it) must never reach past site/files/ - the source site has
        # sitemap.xml and robots.txt of its own, right beside it.
        source_site = self.root / "source-site"
        source_site.mkdir(parents=True)
        source_sitemap = self.SITEMAP.replace("openhamshacknb", "source")
        source_robots = self.ROBOTS.replace("openhamshacknb", "source")
        (source_site / "sitemap.xml").write_text(source_sitemap)
        (source_site / "robots.txt").write_text(source_robots)
        self.assertEqual(run_release(self.repo, "0.4.0", self.releases).returncode, 0)
        self.assert_survived()
        self.assert_survived(source_site, robots=source_robots)


class ServerFiles(unittest.TestCase):
    """.htaccess (from site/htaccess, site/ham/htaccess) and the 404 page
    are written into the folder on every build and never removed - by a
    rebuild, a release, or the archiving release.sh does."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nb_gets_its_htaccess_and_a_404_page_that_leads_home(self) -> None:
        repo = make_repo(self.root)
        (self.out / "openhamshack-nb_0.4.2_all.deb").write_bytes(b"deb")
        res = run_site_build(repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.out / ".htaccess").read_text(), (repo / "site" / "htaccess").read_text())
        # The installers that named /source/ are from before the OpenHamShack
        # rename, so their source is in the source site's openhamshack-nb section.
        self.assertIn("#openhamshack-nb ", (self.out / ".htaccess").read_text())
        page = (self.out / "404.html").read_text()
        self.assertIn('<meta name="robots" content="noindex">', page)
        self.assertIn('<a href="/">OpenHamShack QO-100 NB</a>', page)
        self.assertIn("https://openhamshack.com/source/#openhamshack-nb", page)
        # Served at any depth (/a/b/c), so nothing in it may be relative.
        for ref in local_refs(page):
            self.assertTrue(ref.startswith("/"), f"{ref} would break below the top level")
            self.assertTrue((self.out / ref.lstrip("/")).exists(), ref)

    def test_a_site_in_a_folder_links_within_its_folder(self) -> None:
        # Since 0.1.16 the site is /desktop/nb/ on openhamshack.com: a bare
        # "/" in its 404 page would lead to the OpenHamShack home page and
        # "/favicon.svg" to that site's icon, so every link carries the folder.
        repo = make_repo(self.root)
        (self.out / "openhamshack-nb_0.4.2_all.deb").write_bytes(b"deb")
        res = run_site_build(repo, self.out, url="https://openhamshack.com/desktop/nb/")
        self.assertEqual(res.returncode, 0, res.stderr)
        page = (self.out / "404.html").read_text()
        self.assertIn('<a href="/desktop/nb/">OpenHamShack QO-100 NB</a>', page)
        refs = local_refs(page)
        self.assertTrue(refs)
        for ref in refs:
            self.assertTrue(ref.startswith("/desktop/nb/"), ref)
            self.assertTrue((self.out / ref.removeprefix("/desktop/nb/")).exists(), ref)

    def test_ham_gets_its_own(self) -> None:
        repo = make_ham_repo(self.root)
        res = run_ham_site_build(repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.out / ".htaccess").read_text(), (repo / "site" / "ham" / "htaccess").read_text())
        self.assertIn("#openhamshack-ham ", (self.out / ".htaccess").read_text())
        self.assertIn('<a href="/">OpenHamShack Radio</a>', (self.out / "404.html").read_text())

    def test_a_rebuild_keeps_them_current_and_never_removes_them(self) -> None:
        repo = make_repo(self.root)
        self.assertEqual(run_site_build(repo, self.out).returncode, 0)
        (repo / "site" / "htaccess").write_text("# changed in the repository\n")
        res = run_site_build(repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.out / ".htaccess").read_text(), "# changed in the repository\n")
        self.assertTrue((self.out / "404.html").is_file())


def head_meta(page: str) -> dict[str, str]:
    """Every <meta property|name=... content=...> in a page, by key."""
    return {k: html.unescape(v)
            for k, v in re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', page)}


def jsonld(page: str) -> list[dict]:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]


class PageMetadata(unittest.TestCase):
    """What search engines and link previews read: a canonical address, Open
    Graph and Twitter card tags with a real screenshot, and schema.org
    SoftwareApplication data naming the version and downloads actually in
    the folder - and nothing the site cannot back up."""

    URL = "https://example.invalid/"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def build_nb(self) -> tuple[str, str | None]:
        self.repo = self.repo if hasattr(self, "repo") else make_repo(self.root)
        res = run_site_build(self.repo, self.out, self.URL)
        self.assertEqual(res.returncode, 0, res.stderr)
        guide = self.out / "guide.html"
        return (self.out / "index.html").read_text(), guide.read_text() if guide.exists() else None

    def assert_preview_card(self, page: str, canonical: str) -> None:
        self.assertIn(f'<link rel="canonical" href="{canonical}">', page)
        meta = head_meta(page)
        title = html.unescape(re.search(r"<title>(.*?)</title>", page).group(1))
        self.assertEqual(meta["og:title"], title)
        self.assertEqual(meta["og:description"], meta["description"])
        self.assertEqual(meta["og:url"], canonical)
        self.assertEqual(meta["twitter:card"], "summary_large_image")
        image = meta["og:image"]
        self.assertTrue(image.startswith(self.URL + "shots/"), image)
        local = self.out / image[len(self.URL):]
        self.assertTrue(local.is_file(), image)
        self.assertEqual((int(meta["og:image:width"]), int(meta["og:image:height"])), image_size(local))

    def test_nb_front_page_and_guide_carry_canonical_and_preview_tags(self) -> None:
        self.repo = make_repo(self.root)
        (self.repo / "docs" / "USERGUIDE.md").write_text("# G\n\n## One\n\nText.\n")
        for arch in ("amd64", "arm64", "all"):
            (self.out / f"openhamshack-nb_0.4.2_{arch}.deb").write_bytes(arch.encode())
        index, guide = self.build_nb()
        self.assert_preview_card(index, self.URL)
        self.assert_preview_card(guide, self.URL + "guide.html")

    def test_nb_structured_data_names_the_release_in_the_folder(self) -> None:
        (self.out / "openhamshack-nb_0.1.0_all.deb").write_bytes(b"old")
        for arch in ("amd64", "arm64", "all"):
            (self.out / f"openhamshack-nb_0.4.2_{arch}.deb").write_bytes(arch.encode())
        index, _guide = self.build_nb()
        [data] = jsonld(index)
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual(data["@type"], "SoftwareApplication")
        self.assertEqual(data["name"], "OpenHamShack QO-100 NB")
        self.assertEqual(data["softwareVersion"], "0.4.2")
        self.assertEqual(data["downloadUrl"], [f"{self.URL}openhamshack-nb_0.4.2_{a}.deb" for a in ("amd64", "arm64", "all")])
        for u in data["downloadUrl"]:
            self.assertTrue((self.out / u[len(self.URL):]).is_file(), u)
        self.assertEqual(data["offers"]["price"], "0")
        self.assertIn("GPL-3.0-or-later", data["license"])
        self.assertEqual(data["author"]["name"], "360 Technology")
        self.assertEqual(data["publisher"]["name"], "360 Technology")
        self.assertNotIn("Windows", data["operatingSystem"])       # no installer in the folder
        self.assertTrue((self.out / data["screenshot"]["url"][len(self.URL):]).is_file())
        # Nothing invented: no ratings or reviews exist, so none are claimed.
        self.assertFalse({"aggregateRating", "review", "reviews"} & set(data))
        self.assertEqual(data["description"], head_meta(index)["description"])

    def test_windows_appears_once_an_installer_is_offered(self) -> None:
        (self.out / "openhamshack-nb_0.4.2_all.deb").write_bytes(b"deb")
        (self.out / "openhamshack-nb-0.4.2-setup.exe").write_bytes(b"MZ")
        index, _guide = self.build_nb()
        [data] = jsonld(index)
        self.assertIn("Windows", data["operatingSystem"])
        self.assertIn(f"{self.URL}openhamshack-nb-0.4.2-setup.exe", data["downloadUrl"])

    def test_before_any_release_no_version_or_download_is_claimed(self) -> None:
        index, _guide = self.build_nb()
        [data] = jsonld(index)
        self.assertNotIn("softwareVersion", data)
        self.assertNotIn("downloadUrl", data)

    def test_ham_carries_its_own_name_version_and_screenshot(self) -> None:
        repo = make_ham_repo(self.root)
        (self.out / "openhamshack-radio_0.2.3_all.deb").write_bytes(b"ham")
        (self.out / "openhamshack-nb_0.9.0_all.deb").write_bytes(b"nb")
        res = run_ham_site_build(repo, self.out)
        self.assertEqual(res.returncode, 0, res.stderr)
        index = (self.out / "index.html").read_text()
        self.assert_preview_card(index, self.URL)
        [data] = jsonld(index)
        self.assertEqual(data["name"], "OpenHamShack Radio")
        self.assertEqual(data["softwareVersion"], "0.2.3")
        self.assertEqual(data["downloadUrl"], [f"{self.URL}openhamshack-radio_0.2.3_all.deb"])
        self.assertIn("preview", data["applicationSubCategory"])
        self.assertIn(Path(site.HAM_SHOTS[0][0]).stem, head_meta(index)["og:image"])

    def test_the_old_source_pointer_is_not_indexed(self) -> None:
        (self.out / "openhamshack-nb_0.4.2_all.deb").write_bytes(b"deb")
        (self.out / "openhamshack-nb-0.4.2-setup.exe").write_bytes(b"MZ")
        (self.out / "source").mkdir()
        self.build_nb()
        pointer = (self.out / "source" / "index.html").read_text()
        self.assertIn('<meta name="robots" content="noindex">', pointer)
        self.assertIn('lang="en-GB"', pointer)
        self.assertIn("https://openhamshack.com/source/#openhamshack-nb", pointer)


if __name__ == "__main__":
    unittest.main()
