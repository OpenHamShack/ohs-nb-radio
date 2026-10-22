"""Packaging tests: build the real .deb with tools/build-deb.sh and check
what it actually does, never what its scripts say. The .deb is a build
artefact of a shell script, not ohsnb, so these drive dpkg-deb and the
installed launcher as a user would -- no assertion here reads this repo's
own source text."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The .deb is built with dpkg-deb on Debian. Elsewhere (the Windows build
# runs this suite under Windows Python) there is nothing to build it with,
# which says nothing about the package, so the module is skipped, not failed.
if shutil.which("dpkg-deb") is None:
    raise unittest.SkipTest("dpkg-deb not installed: the .deb is built and checked on Debian")

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "tools" / "build-deb.sh"
VERSION = (REPO_ROOT / "ohsnb" / "VERSION").read_text().strip()


def build(tmpdir, version=None):
    """Run build-deb.sh with tmpdir as cwd, so the .deb lands there and
    never in the repo. Returns the built .deb's path."""
    args = [str(BUILD_SCRIPT)]
    if version:
        args.append(version)
    subprocess.run(args, cwd=tmpdir, check=True, capture_output=True, text=True)
    v = version or VERSION
    deb = Path(tmpdir) / f"openhamshack-nb_{v}_all.deb"
    assert deb.is_file(), f"build-deb.sh did not produce {deb}"
    return deb


def field(deb, name):
    return subprocess.run(["dpkg-deb", "-f", str(deb), name],
                           check=True, capture_output=True, text=True).stdout.strip()


def contents(deb):
    out = subprocess.run(["dpkg-deb", "-c", str(deb)],
                          check=True, capture_output=True, text=True).stdout
    return [line.split()[-1] for line in out.splitlines()]


class BuildsCleanly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_version_comes_from_ohsnb_version_file(self):
        deb = build(self.tmp.name)
        self.assertEqual(field(deb, "Version"), VERSION)

    def test_explicit_version_argument_overrides_the_file(self):
        deb = build(self.tmp.name, version="9.9.9")
        self.assertEqual(deb.name, "openhamshack-nb_9.9.9_all.deb")
        self.assertEqual(field(deb, "Version"), "9.9.9")

    def test_leaves_no_artefact_in_the_repo(self):
        build(self.tmp.name)
        self.assertEqual(list(REPO_ROOT.glob("*.deb")), [])
        self.assertEqual(list((REPO_ROOT / "tools").glob("*.deb")), [])

    def test_rebuilding_does_not_fail(self):
        # dpkg-deb --build must not choke on a pre-existing output file,
        # and the script's own temp workdir must not collide with itself.
        build(self.tmp.name)
        build(self.tmp.name)


class ControlFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_identity(self):
        self.assertEqual(field(self.deb, "Package"), "openhamshack-nb")
        self.assertEqual(field(self.deb, "Architecture"), "all")

    def test_installed_size_is_a_plausible_positive_number(self):
        # The payload is a Python package plus a handful of small assets;
        # bound it loosely so a future ohsnb/ growth spurt doesn't need
        # this test touched, but a build that forgot to copy ohsnb/ (or
        # one that accidentally included a stray venv) would trip it.
        kib = int(field(self.deb, "Installed-Size"))
        self.assertGreater(kib, 50)
        self.assertLess(kib, 50_000)

    def test_depends_names_the_hard_requirements(self):
        depends = field(self.deb, "Depends")
        # python3-cryptography: the update feed's signature check (ohscore/update.py).
        for pkg in ("python3 (>= 3.11)", "python3-numpy", "python3-pyqt6", "python3-pyaudio", "python3-cryptography"):
            self.assertIn(pkg, depends)

    def test_recommends_and_suggests_are_optional_extras_not_depends(self):
        depends = field(self.deb, "Depends")
        recommends = field(self.deb, "Recommends")
        suggests = field(self.deb, "Suggests")
        # wsjtx: Recommends only here, in the "all" package, which has no
        # ohsdigi (see Ohsdigi below for the per-architecture packages).
        for pkg in ("python3-libiio", "libiio-utils", "libad9361-0", "avahi-daemon", "wsjtx", "python3-soapysdr",
                    "python3-serial"):
            self.assertIn(pkg, recommends)
            self.assertNotIn(pkg, depends)
        self.assertIn("libcodec2-1.2 | libcodec2-1.0", recommends)
        for pkg in ("soapysdr-module-rtlsdr", "soapysdr-module-airspy", "js8call"):
            self.assertIn(pkg, suggests)
            self.assertNotIn(pkg, depends)
            self.assertNotIn(pkg, recommends)

    def test_maintainer_scripts_are_present_and_executable(self):
        info = subprocess.run(["dpkg-deb", "-I", str(self.deb)],
                               check=True, capture_output=True, text=True).stdout
        self.assertIn("postinst", info)
        self.assertIn("postrm", info)


class PackageContents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name)
        cls.listing = contents(cls.deb)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ships_the_launcher_the_app_and_its_core(self):
        self.assertIn("./usr/bin/openhamshack-nb", self.listing)
        self.assertIn("./usr/lib/openhamshack-nb/ohsnb/radio.py", self.listing)
        self.assertIn("./usr/lib/openhamshack-nb/ohsnb/__main__.py", self.listing)
        self.assertIn("./usr/lib/openhamshack-nb/ohscore/__init__.py", self.listing)

    def test_ships_desktop_icon_metainfo_and_man_page(self):
        self.assertIn("./usr/share/applications/openhamshack-nb.desktop", self.listing)
        self.assertIn("./usr/share/icons/hicolor/scalable/apps/openhamshack-nb.svg", self.listing)
        self.assertIn("./usr/share/metainfo/openhamshack-nb.metainfo.xml", self.listing)
        self.assertIn("./usr/share/man/man1/openhamshack-nb.1.gz", self.listing)
        self.assertIn("./usr/share/doc/openhamshack-nb/copyright", self.listing)

    def test_its_only_udev_rule_is_the_pads(self):
        # libiio0 already installs /usr/lib/udev/rules.d/90-libiio0.rules
        # on this distro family (see docs/INSTALL.md); a second Pluto rule
        # would be redundant at best and a conflicting-rule bug at worst.
        # The one rule of our own is the AKP03E's, named after the package
        # so NB and Radio install side by side, and numbered before
        # 73-seat-late.rules, where systemd turns uaccess into an ACL.
        rules = [p for p in self.listing if "udev" in p and not p.endswith("/")]
        self.assertEqual(rules, ["./usr/lib/udev/rules.d/60-openhamshack-nb-pad.rules"])
        self.assertLess("60-openhamshack-nb-pad.rules", "73-seat-late.rules")

    def test_the_pad_rule_is_one_udev_accepts_for_the_akp03e_only(self):
        root = Path(self.tmp.name) / "x"
        subprocess.run(["dpkg-deb", "-x", str(self.deb), str(root)], check=True)
        rule = root / "usr/lib/udev/rules.d/60-openhamshack-nb-pad.rules"
        lines = [ln for ln in rule.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(lines), 1)
        for part in ('KERNEL=="hidraw*"', 'ATTRS{idVendor}=="0300"', 'ATTRS{idProduct}=="3002"', 'TAG+="uaccess"'):
            self.assertIn(part, lines[0])
        udevadm = shutil.which("udevadm") or ("/usr/bin/udevadm" if Path("/usr/bin/udevadm").exists() else None)
        if udevadm is None:
            self.skipTest("no udevadm here")
        res = subprocess.run([udevadm, "verify", "--no-style", str(rule)], capture_output=True, text=True)
        if "unknown option" in (res.stderr or "").lower() or "unknown command" in (res.stderr or "").lower():
            self.skipTest("this udevadm has no verify")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_ships_no_compiled_or_cache_artefacts(self):
        self.assertFalse(any("__pycache__" in p for p in self.listing))
        self.assertFalse(any(p.endswith((".pyc", ".pyo")) for p in self.listing))

    def test_payload_files_are_world_readable(self):
        out = subprocess.run(["dpkg-deb", "-c", str(self.deb)],
                              check=True, capture_output=True, text=True).stdout
        for line in out.splitlines():
            perms = line.split()[0]
            if perms.startswith("-"):  # regular file, not a directory
                self.assertEqual(perms[7], "r", f"not world-readable: {line}")


class ExtractedPackageRuns(unittest.TestCase):
    """The real point of the launcher: it must find ohsnb/ by its own
    location, not by anything baked in at build time, because dpkg can
    extract this package to any root (and because this is exactly what
    an install under a different prefix, or this test, does)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name)
        cls.extracted = Path(cls.tmp.name) / "root"
        subprocess.run(["dpkg-deb", "-x", str(cls.deb), str(cls.extracted)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self, *extra_args, env_override=None):
        launcher = self.extracted / "usr" / "bin" / "openhamshack-nb"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        if env_override:
            env.update(env_override)
        # cwd is a bare scratch dir, not the repo and not the extracted
        # root, so nothing but the launcher's own path math can find ohsnb/.
        with tempfile.TemporaryDirectory() as cwd:
            return subprocess.run([str(launcher), *extra_args], cwd=cwd, env=env,
                                   capture_output=True, text=True, timeout=30)

    def test_headless_engine_starts_and_stops_cleanly(self):
        res = self._run("--headless", "--no-audio", "--seconds", "2")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("rx-lock", res.stdout)
        self.assertIn("stopped;", res.stdout)

    def test_never_transmits_in_headless_mode(self):
        # Safety rule #1 (DESIGN.md): never transmits on its own. Headless
        # mode has no PTT source at all, so the keyed marker must never
        # appear in its own status lines.
        res = self._run("--headless", "--no-audio", "--seconds", "2")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(" TX ", res.stdout)

    def test_installed_app_uses_its_own_copy_of_the_core(self):
        # The .deb carries ohscore privately beside ohsnb. Ask the installed
        # interpreter where both came from: with the repo off the path, a
        # package that forgot ohscore would fail here, and one that found it
        # anywhere but the extracted tree would name the wrong folder.
        libdir = self.extracted / "usr" / "lib" / "openhamshack-nb"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run(
                [sys.executable, "-c",
                 "import ohsnb.__main__, ohscore; print(ohsnb.__file__); print(ohscore.__file__)"],
                cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        for line in res.stdout.split():
            self.assertTrue(Path(line).resolve().is_relative_to(libdir.resolve()), line)

    def test_installed_copy_can_check_an_update_signature(self):
        # The package's own ohscore, with the system's cryptography (its
        # Depends), checking RFC 8032's test vector: what start-up logs as
        # "update signatures", and what every update check needs first.
        libdir = self.extracted / "usr" / "lib" / "openhamshack-nb"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c", "from ohscore import update; print(update.describe_verifier())"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("self-test passed", res.stdout)

    def test_installed_copy_reads_its_own_cty_dat_with_no_wsjtx(self):
        # The Country column with no WSJT-X anywhere: the package's own
        # ohscore/data/cty.dat, found beside the installed dxcc.py. OR4TN is
        # Antarctica only by Big CTY's exact-call list (Belgium by prefix).
        libdir = self.extracted / "usr" / "lib" / "openhamshack-nb"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c",
                                  "from ohscore import dxcc, host; host.wsjtx_cty_files = lambda: []; "
                                  "print(dxcc.BUNDLED); print(dxcc.load(None).lookup('OR4TN').name)"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        path, name = res.stdout.strip().splitlines()
        self.assertTrue(Path(path).resolve().is_relative_to(libdir.resolve()), path)
        self.assertEqual(name, "Antarctica")

    def test_honours_an_unrelated_preexisting_pythonpath(self):
        # The launcher prepends, it must not clobber a PYTHONPATH the
        # environment already set for some other reason.
        marker = str(Path(self.tmp.name) / "not-ohsnb")
        os.makedirs(marker, exist_ok=True)
        res = self._run("--headless", "--no-audio", "--seconds", "1", env_override={"PYTHONPATH": marker})
        self.assertEqual(res.returncode, 0, res.stderr)


class MaintainerScriptsAreOptionalToolSafe(unittest.TestCase):
    """postinst/postrm must exit 0 even when update-desktop-database and
    gtk-update-icon-cache do not exist, which is normal on a minimal or
    container install. Run them for real with a PATH that only has the
    coreutils they need to find out, rather than trusting the script."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name)
        cls.extracted = Path(cls.tmp.name) / "root"
        cls.extracted.mkdir()
        subprocess.run(["dpkg-deb", "-e", str(cls.deb), str(cls.extracted / "DEBIAN")], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _bare_path(self):
        # A PATH with just enough coreutils for `command -v`, sh and env
        # to work, and deliberately missing update-desktop-database and
        # gtk-update-icon-cache.
        bare = Path(self.tmp.name) / "bare-bin"
        bare.mkdir(exist_ok=True)
        for tool in ("sh", "env", "command"):
            real = shutil.which(tool)
            if real and not (bare / tool).exists():
                os.symlink(real, bare / tool)
        return str(bare)

    def test_postinst_configure_exits_zero_without_optional_tools(self):
        script = self.extracted / "DEBIAN" / "postinst"
        res = subprocess.run([str(script), "configure"],
                              env={"PATH": self._bare_path()}, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_postrm_remove_exits_zero_without_optional_tools(self):
        script = self.extracted / "DEBIAN" / "postrm"
        res = subprocess.run([str(script), "remove"],
                              env={"PATH": self._bare_path()}, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)


def _an_amd64_ohsdigi():
    """An x86-64 ohsdigi module to package: the release build if one has been
    made (tools/build-ohsdigi.sh), else a developer's build in ohscore/."""
    for cand in (REPO_ROOT / "rust" / "dist" / "linux-amd64" / "ohsdigi.abi3.so",
                 REPO_ROOT / "ohscore" / "ohsdigi.abi3.so"):
        if cand.is_file():
            return cand
    return None


class ArchitecturePackages(unittest.TestCase):
    """amd64 and arm64 packages carry ohsdigi, the Rust FT8/FT4 encoder; the
    all package is pure Python and never does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self.tmp.name) / "dist"

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self, arch, check=True):
        env = dict(os.environ, OHSDIGI_DIST=str(self.dist))
        return subprocess.run([str(BUILD_SCRIPT), "--arch", arch, "9.9.9"], cwd=self.tmp.name, env=env,
                              check=check, capture_output=True, text=True)

    def _stage(self, as_arch):
        so = _an_amd64_ohsdigi()
        if so is None:
            self.skipTest("no ohsdigi built (tools/build-ohsdigi.sh)")
        (self.dist / f"linux-{as_arch}").mkdir(parents=True)
        shutil.copy(so, self.dist / f"linux-{as_arch}" / "ohsdigi.abi3.so")

    def test_all_carries_no_ohsdigi_even_with_a_developer_build_in_the_tree(self):
        self._build("all")
        deb = Path(self.tmp.name) / "openhamshack-nb_9.9.9_all.deb"
        self.assertEqual(field(deb, "Architecture"), "all")
        self.assertEqual([p for p in contents(deb) if "ohsdigi" in p], [])
        # shack_sdr is native too, so the package for any machine has none
        # (RTTY is then listed with the reason, ohscore/sdr.py).
        self.assertEqual([p for p in contents(deb) if "shack_sdr" in p], [])

    def test_amd64_carries_the_x86_64_shack_sdr_and_the_installed_program_loads_it(self):
        self._stage("amd64")
        self._build("amd64")
        deb = Path(self.tmp.name) / "openhamshack-nb_9.9.9_amd64.deb"
        native = [p for p in contents(deb) if "/shack_sdr/_native" in p]
        self.assertEqual(native, ["./usr/lib/openhamshack-nb/shack_sdr/_native.abi3.so"])
        root = Path(self.tmp.name) / "root"
        subprocess.run(["dpkg-deb", "-x", str(deb), str(root)], check=True)
        libdir = root / "usr" / "lib" / "openhamshack-nb"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c", "from ohscore import sdr; m = sdr.load(); print(m.__file__)"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(Path(res.stdout.strip()).resolve().is_relative_to(libdir.resolve()), res.stdout)

    def test_amd64_carries_ohsdigi_and_the_installed_program_encodes_with_it(self):
        self._stage("amd64")
        self._build("amd64")
        deb = Path(self.tmp.name) / "openhamshack-nb_9.9.9_amd64.deb"
        self.assertEqual(field(deb, "Architecture"), "amd64")
        self.assertIn("libc6 (>= 2.34)", field(deb, "Depends"))
        # ohsdigi decodes, so WSJT-X is only suggested (for jt9 as its shadow).
        self.assertNotIn("wsjtx", field(deb, "Recommends"))
        self.assertIn("wsjtx", field(deb, "Suggests").split(", "))
        self.assertIn("./usr/lib/openhamshack-nb/ohscore/ohsdigi.abi3.so", contents(deb))
        root = Path(self.tmp.name) / "root"
        subprocess.run(["dpkg-deb", "-x", str(deb), str(root)], check=True)
        libdir = root / "usr" / "lib" / "openhamshack-nb"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c",
                                  "from ohscore.modes import ft8; print(ft8._OHSDIGI.__file__); "
                                  "print(len(ft8.Encoder().render(text='CQ GM4BRI IO86', variant='ft4')))"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        path, n = res.stdout.split()
        self.assertTrue(Path(path).resolve().is_relative_to(libdir.resolve()), path)
        self.assertEqual(int(n), 105 * 576)

    def test_a_module_for_the_wrong_architecture_is_refused(self):
        self._stage("arm64")          # an x86-64 module where the arm64 one should be
        res = self._build("arm64", check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not built for arm64", res.stderr)
        self.assertEqual(list(Path(self.tmp.name).glob("*.deb")), [])

    def test_a_missing_module_says_how_to_build_it(self):
        res = self._build("amd64", check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("tools/build-ohsdigi.sh linux-amd64", res.stderr)


if __name__ == "__main__":
    unittest.main()
