"""Self-update without a window (ohscore/update.py): the signed manifest,
what this machine is offered, the download proved against it, Windows'
signer check, the install command and the schedule - and, end to end, a
release folder written and signed by tools/update-feed.py with a test key,
served over a local HTTP server, through to the command that would
install it (never run).

Keys here are throw-away ones made per test run; the real release key is
never touched (and ohscore/update.py's RELEASE_KEYS is left as it is: every
call that needs a key is given the test one).
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import hashlib
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from ohscore import update

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


# ---------------------------------------------------------------- helpers (functions only: imported elsewhere)
def new_key():
    """(private key, keys argument for ohscore.update naming its public half)."""
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return k, [("test key", pub.hex())]


def key_file(k, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return path


def entry(platform="linux", arch="all", version="0.2.0", data=b"package bytes", url=None):
    kind = update.KINDS[platform]
    url = url or {"deb": f"openhamshack-nb_{version}_{arch}.deb", "exe": f"openhamshack-nb-{version}-setup.exe",
                  "dmg": f"openhamshack-nb-{version}-{arch}.dmg"}[kind]
    return {"platform": platform, "arch": arch, "kind": kind, "version": version, "url": url, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "date": "2026-10-07", "notes": "Things got better"}


def manifest(k, keys, files, app="openhamshack-nb", published="2026-10-07T12:00:00Z", **extra):
    """(bytes, signature) of a manifest signed by k."""
    doc = {"schema": 1, "app": app, "key": update.key_id(bytes.fromhex(keys[0][1])), "published": published,
           **extra, "files": files}
    data = (json.dumps(doc, indent=2) + "\n").encode()
    return data, k.sign(data)


class Served:
    """A folder over HTTP on 127.0.0.1, remembering each request's path
    and User-Agent - what a check tells the site about the machine."""

    def __init__(self, folder: Path):
        served = self
        self.requests: list[tuple[str, str, dict]] = []

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(folder), **kw)

            def do_GET(self):
                served.requests.append((self.path, self.headers.get("User-Agent", ""), dict(self.headers)))
                super().do_GET()

            def log_message(self, *_a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def closed_port_url() -> str:
    """A URL nothing answers: a port bound and released again."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/update.json"


def write_release(folder: Path, keyfile: Path, version: str, files: dict[str, bytes], *extra: str):
    """Put `files` in the release folder (with .sha256 sidecars, as
    release.sh does) and sign its feed with tools/update-feed.py."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
        (folder / f"{name}.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    return subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "update-feed.py"), "write", "--key", str(keyfile),
                           "--releases", str(folder), "--version", version, "--untrusted-ok", "--notes", "Test notes",
                           *extra], capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- the manifest
@unittest.skipUnless(HAVE_CRYPTO, "python3-cryptography is not installed")
class Manifest(unittest.TestCase):
    def setUp(self):
        self.k, self.keys = new_key()

    def test_a_signed_manifest_is_read(self):
        data, sig = manifest(self.k, self.keys, [entry()], recommended="0.1.9", notesUrl="index.html#notes")
        m = update.read_manifest(data, sig, "openhamshack-nb", self.keys)
        self.assertEqual(m.app, "openhamshack-nb")
        self.assertEqual(m.recommended, "0.1.9")
        self.assertEqual([(e.platform, e.arch, e.version) for e in m.entries], [("linux", "all", "0.2.0")])

    def test_an_entry_for_a_system_this_version_does_not_know_is_passed_over(self):
        # A feed that starts offering a new system must not stop older
        # copies updating: the entries they know are read, the rest skipped.
        later = dict(entry(), platform="haiku", kind="hpkg", url="openhamshack-nb-0.2.0.hpkg")
        odd_arch = dict(entry(), arch="riscv64", url="openhamshack-nb_0.2.0_riscv64.deb")
        data, sig = manifest(self.k, self.keys, [later, entry(), odd_arch])
        m = update.read_manifest(data, sig, "openhamshack-nb", self.keys)
        self.assertEqual([(e.platform, e.arch) for e in m.entries], [("linux", "all")])
        # ...but a system it does know is still held to every rule.
        data, sig = manifest(self.k, self.keys, [dict(entry("macos", "arm64"), kind="exe")])
        with self.assertRaisesRegex(update.NotTrusted, "kind"):
            update.read_manifest(data, sig, "openhamshack-nb", self.keys)

    def test_a_tampered_manifest_is_refused(self):
        data, sig = manifest(self.k, self.keys, [entry()])
        # One digit of the sha256 changed after signing: someone pointing
        # clients at a file of their own.
        bad = data.replace(b'"version": "0.2.0"', b'"version": "0.2.1"')
        self.assertNotEqual(bad, data)
        with self.assertRaisesRegex(update.NotTrusted, "does not match"):
            update.read_manifest(bad, sig, "openhamshack-nb", self.keys)

    def test_a_signature_by_another_key_is_refused(self):
        other, _ = new_key()
        data, _sig = manifest(self.k, self.keys, [entry()])
        with self.assertRaisesRegex(update.NotTrusted, "does not match"):
            update.read_manifest(data, other.sign(data), "openhamshack-nb", self.keys)

    def test_a_key_this_version_does_not_trust_is_refused_by_name(self):
        other, other_keys = new_key()
        data, sig = manifest(other, other_keys, [entry()])
        with self.assertRaisesRegex(update.NotTrusted, "which this version does not trust"):
            update.read_manifest(data, sig, "openhamshack-nb", self.keys)

    def test_a_next_key_carried_beside_the_current_one_is_trusted_too(self):
        # Rotation: a build lists both; manifests signed by either verify.
        nxt, nxt_keys = new_key()
        both = self.keys + nxt_keys
        for k, ks in ((self.k, self.keys), (nxt, nxt_keys)):
            data, sig = manifest(k, ks, [entry()])
            self.assertEqual(update.read_manifest(data, sig, "openhamshack-nb", both).key,
                             update.key_id(bytes.fromhex(ks[0][1])))

    def test_a_build_that_trusts_no_key_accepts_nothing(self):
        data, sig = manifest(self.k, self.keys, [entry()])
        with self.assertRaisesRegex(update.NotTrusted, "trusts no release key"):
            update.read_manifest(data, sig, "openhamshack-nb", keys=[])

    def test_the_other_apps_manifest_is_refused(self):
        data, sig = manifest(self.k, self.keys, [entry()], app="openhamshack-radio")
        with self.assertRaisesRegex(update.NotTrusted, "for 'openhamshack-radio', not openhamshack-nb"):
            update.read_manifest(data, sig, "openhamshack-nb", self.keys)

    def test_a_later_format_is_refused(self):
        doc = json.loads(manifest(self.k, self.keys, [entry()])[0])
        doc["schema"] = 2
        data = json.dumps(doc).encode()
        with self.assertRaisesRegex(update.NotTrusted, "format 2"):
            update.read_manifest(data, self.k.sign(data), "openhamshack-nb", self.keys)

    def test_a_file_name_that_is_a_path_or_a_url_is_refused_even_signed(self):
        for url in ("../../etc/passwd", "https://elsewhere.example/x.deb", "sub/x.deb", ".hidden"):
            data, sig = manifest(self.k, self.keys, [entry(url=url)])
            with self.assertRaises(update.NotTrusted, msg=url):
                update.read_manifest(data, sig, "openhamshack-nb", self.keys)

    def test_a_truncated_signature_is_refused(self):
        data, sig = manifest(self.k, self.keys, [entry()])
        with self.assertRaisesRegex(update.NotTrusted, "not an Ed25519 signature"):
            update.read_manifest(data, sig[:40], "openhamshack-nb", self.keys)

    def test_the_verifier_proves_itself_on_rfc_8032s_vector(self):
        self.assertIn("self-test passed", update.describe_verifier())


# ---------------------------------------------------------------- what is offered
@unittest.skipUnless(HAVE_CRYPTO, "python3-cryptography is not installed")
class Choosing(unittest.TestCase):
    def setUp(self):
        self.k, self.keys = new_key()

    def read(self, files, **extra):
        return update.read_manifest(*manifest(self.k, self.keys, files, **extra), "openhamshack-nb", self.keys)

    def test_the_machines_own_architecture_first_then_all(self):
        m = self.read([entry(arch="amd64"), entry(arch="arm64"), entry(arch="all")])
        self.assertEqual(update.choose(m, "linux", "amd64", "0.1.8").entry.arch, "amd64")
        self.assertEqual(update.choose(m, "linux", "arm64", "0.1.8").entry.arch, "arm64")
        # No build for this machine (a Pi on 32-bit Raspberry Pi OS): the pure-Python one.
        self.assertEqual(update.choose(m, "linux", "armhf", "0.1.8").entry.arch, "all")
        m = self.read([entry(arch="all")])
        self.assertEqual(update.choose(m, "linux", "amd64", "0.1.8").entry.arch, "all")

    def test_windows_takes_the_installer_and_never_a_deb(self):
        m = self.read([entry(arch="amd64"), entry("windows", "amd64")])
        self.assertEqual(update.choose(m, "windows", "amd64", "0.1.8").entry.kind, "exe")
        self.assertEqual(update.choose(m, "linux", "amd64", "0.1.8").entry.kind, "deb")
        self.assertIsNone(update.choose(self.read([entry()]), "windows", "amd64", "0.1.8"))

    def test_a_mac_takes_its_own_dmg_and_an_intel_mac_is_offered_nothing(self):
        m = self.read([entry(arch="arm64"), entry(arch="all"), entry("windows", "amd64"), entry("macos", "arm64")])
        offer = update.choose(m, "macos", "arm64", "0.1.8")
        self.assertEqual((offer.entry.kind, offer.entry.url), ("dmg", "openhamshack-nb-0.2.0-arm64.dmg"))
        # Never Linux's "all" .deb, and nothing at all for an arch with no .dmg.
        self.assertIsNone(update.choose(m, "macos", "amd64", "0.1.8"))
        self.assertIsNone(update.choose(self.read([entry(arch="all")]), "macos", "arm64", "0.1.8"))

    def test_the_same_version_is_not_offered(self):
        self.assertIsNone(update.choose(self.read([entry(version="0.1.8")]), "linux", "all", "0.1.8"))

    def test_versions_compare_as_numbers(self):
        m = self.read([entry(version="0.1.10")])
        self.assertEqual(update.choose(m, "linux", "all", "0.1.9").entry.version, "0.1.10")

    def test_a_labelled_build_orders_as_the_release_it_was_built_after(self):
        # The macOS preview is "0.1.9+mac-preview.1": the next release is an
        # update for it, the release it was built after is not.
        newer = self.read([entry("macos", "arm64", version="0.1.10")])
        self.assertEqual(update.choose(newer, "macos", "arm64", "0.1.9+mac-preview.1").entry.version, "0.1.10")
        same = self.read([entry("macos", "arm64", version="0.1.9")])
        self.assertIsNone(update.choose(same, "macos", "arm64", "0.1.9+mac-preview.1"))
        # Going back still needs the feed to recommend it.
        older = self.read([entry("macos", "arm64", version="0.1.8")], recommended="0.1.8")
        self.assertTrue(update.choose(older, "macos", "arm64", "0.1.9+mac-preview.1").rollback)
        for bad in ("0.1.9+", "0.1.9+a b", "0.1.9+x+y", "0.1.9-mac-preview.1"):
            with self.assertRaises(ValueError, msg=bad):
                update.installed_version(bad)

    def test_the_feed_itself_may_not_name_a_labelled_build(self):
        # A label marks a build that is not a release; the feed offers releases.
        with self.assertRaises(update.NotTrusted):
            self.read([entry("macos", "arm64", version="0.1.10+mac-preview.1")])

    def test_a_downgrade_is_refused(self):
        self.assertIsNone(update.choose(self.read([entry(version="0.1.7")]), "linux", "all", "0.1.8"))

    def test_a_downgrade_to_the_recommended_version_is_offered_as_a_rollback(self):
        m = self.read([entry(version="0.1.7")], recommended="0.1.7")
        offer = update.choose(m, "linux", "all", "0.1.8")
        self.assertTrue(offer.rollback)
        self.assertEqual(offer.entry.version, "0.1.7")
        # recommended names a different version from the entry: still no.
        m = self.read([entry(version="0.1.7")], recommended="0.1.6")
        self.assertIsNone(update.choose(m, "linux", "all", "0.1.8"))

    def test_urls_resolve_beside_the_manifest(self):
        m = self.read([entry()], notesUrl="index.html#notes")
        offer = update.choose(m, "linux", "all", "0.1.8", "https://openhamshacknb.example/update.json")
        self.assertEqual(offer.url, "https://openhamshacknb.example/openhamshack-nb_0.2.0_all.deb")
        self.assertEqual(offer.notes_url, "https://openhamshacknb.example/index.html#notes")


# ---------------------------------------------------------------- fetching and downloading
@unittest.skipUnless(HAVE_CRYPTO, "python3-cryptography is not installed")
class OverHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        self.server = Served(self.site)
        self.k, self.keys = new_key()
        self.deb = b"the real package " * 1000
        self.publish([entry(data=self.deb)])

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def publish(self, files, **extra):
        data, sig = manifest(self.k, self.keys, files, **extra)
        (self.site / "update.json").write_bytes(data)
        (self.site / "update.json.sig").write_bytes(sig)
        (self.site / "openhamshack-nb_0.2.0_all.deb").write_bytes(self.deb)

    def check(self, app="openhamshack-nb", **kw):
        args = dict(plat="linux", arch="amd64", keys=self.keys, seen=update.Seen(self.root / "seen.json"))
        args.update(kw)
        return update.check(self.server.url + "update.json", app, "0.1.8", **args)

    def test_a_check_finds_the_update_and_says_nothing_but_name_and_version(self):
        r = self.check()
        self.assertEqual(r.status, "available", r.message)
        self.assertEqual(r.offer.entry.version, "0.2.0")
        self.assertEqual([p for p, _ua, _h in self.server.requests], ["/update.json", "/update.json.sig"])
        for _path, ua, headers in self.server.requests:
            self.assertEqual(ua, "openhamshack-nb/0.1.8")
            self.assertNotIn("Cookie", headers)

    def test_offline_is_a_quiet_result_not_an_error(self):
        with self.assertLogs("ohscore.update", "INFO") as logged:
            r = update.check(closed_port_url(), "openhamshack-nb", "0.1.8", plat="linux", arch="amd64", keys=self.keys)
        self.assertIn("could not be reached", logged.output[0])
        self.assertEqual(r.status, "offline")
        self.assertIn("could not be reached", r.message)
        self.assertIsNone(r.offer)

    def test_a_tampered_manifest_on_the_site_is_refused(self):
        data = (self.site / "update.json").read_bytes()
        (self.site / "update.json").write_bytes(data.replace(b"Things got better", b"Things got worse!"))
        with self.assertLogs("ohscore.update", "WARNING") as logged:      # logged, never a dialog
            r = self.check()
        self.assertIn("refused", logged.output[0])
        self.assertEqual(r.status, "refused")
        self.assertIsNone(r.offer)

    def test_an_older_manifest_than_one_already_seen_is_refused(self):
        self.assertEqual(self.check().status, "available")
        # The site (or the CDN's edge, or someone in between) serves an
        # earlier, validly signed manifest.
        self.publish([entry(data=self.deb)], published="2026-10-01T00:00:00Z")
        with self.assertLogs("ohscore.update", "WARNING"):
            r = self.check()
        self.assertEqual(r.status, "refused")
        self.assertIn("older than one already seen", r.message)

    def test_the_download_is_proved_against_the_signed_manifest(self):
        offer = self.check().offer
        path = update.download(offer, self.root / "dl", "openhamshack-nb/0.1.8")
        self.assertEqual(path.read_bytes(), self.deb)
        self.assertEqual(path.name, "openhamshack-nb_0.2.0_all.deb")

    def test_a_download_with_the_wrong_sha256_is_refused_and_removed(self):
        offer = self.check().offer
        swapped = bytearray(self.deb)
        swapped[100] ^= 1                                  # same size, different bytes
        (self.site / "openhamshack-nb_0.2.0_all.deb").write_bytes(bytes(swapped))
        with self.assertRaisesRegex(update.NotTrusted, "does not match the signed manifest"):
            update.download(offer, self.root / "dl", "openhamshack-nb/0.1.8")
        self.assertEqual(list((self.root / "dl").iterdir()), [])

    def test_a_download_longer_than_signed_stops_at_the_size(self):
        offer = self.check().offer
        (self.site / "openhamshack-nb_0.2.0_all.deb").write_bytes(self.deb + b"and a payload")
        with self.assertRaisesRegex(update.NotTrusted, "bigger than the signed manifest"):
            update.download(offer, self.root / "dl", "openhamshack-nb/0.1.8")
        self.assertEqual(list((self.root / "dl").iterdir()), [])

    def test_progress_is_reported_to_the_full_size(self):
        seen = []
        update.download(self.check().offer, self.root / "dl", "ua", progress=lambda a, b: seen.append((a, b)))
        self.assertEqual(seen[-1], (len(self.deb), len(self.deb)))


# ---------------------------------------------------------------- Windows' own signature
class Authenticode(unittest.TestCase):
    """The query is Windows' (PowerShell's Get-AuthenticodeSignature); here
    a stand-in gives its answers, so the decision itself is what is tested."""

    def test_valid_and_signed_by_360_technology_passes(self):
        subject = "CN=360 Technology, O=360 Technology, L=Example, C=GB"
        self.assertEqual(update.check_authenticode(Path("x.exe"), query=lambda p: ("Valid", subject)), subject)

    def test_a_valid_signature_by_anyone_else_is_refused(self):
        for subject in ("CN=Someone Else, O=Someone Else Ltd, C=GB", "CN=360 Technology, O=360 Technology Ltd",
                        "CN=x, O=Not 360 Technology"):
            with self.assertRaisesRegex(update.NotTrusted, "not 360 Technology", msg=subject):
                update.check_authenticode(Path("x.exe"), query=lambda p, s=subject: ("Valid", s))

    def test_unsigned_or_broken_signatures_are_refused(self):
        for status in ("NotSigned", "HashMismatch", "NotTrusted", "UnknownError", ""):
            with self.assertRaises(update.NotTrusted, msg=status):
                update.check_authenticode(Path("x.exe"),
                                          query=lambda p, s=status: (s, "CN=360 Technology, O=360 Technology"))


# ---------------------------------------------------------------- installing
class InstallCommand(unittest.TestCase):
    # The command names the file by its absolute, resolved path, so the
    # expected one is resolved too: on macOS /tmp is a link to /private/tmp.
    def test_a_deb_is_installed_by_apt_through_pkexec(self):
        deb = Path("/tmp/dl/openhamshack-nb_0.2.0_amd64.deb")
        cmd = update.install_command("deb", deb, pkexec="/usr/bin/pkexec")
        self.assertEqual(cmd.argv, ["/usr/bin/pkexec", "apt-get", "install", "-y", str(deb.resolve())])

    def test_without_pkexec_the_exact_command_is_given_instead(self):
        deb = Path("/tmp/my downloads/openhamshack-nb_0.2.0_all.deb")
        cmd = update.install_command("deb", deb, pkexec="")
        self.assertIsNone(cmd.argv)
        self.assertEqual(cmd.manual, f"sudo apt-get install -y '{deb.resolve()}'")

    def test_the_installer_runs_unattended_and_starts_the_program_again(self):
        exe = Path("/tmp/openhamshack-nb-0.2.0-setup.exe")
        cmd = update.install_command("exe", exe)
        self.assertEqual(cmd.argv[0], str(exe.resolve()))
        for switch in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/MERGETASKS=!plutodrivers", "/RELAUNCH=1"):
            self.assertIn(switch, cmd.argv)

    def test_a_dmg_is_opened_in_finder_never_installed(self):
        # Unsigned: the operator drags it across (install_command says why).
        dmg = Path("/tmp/dl/openhamshack-nb-0.2.0-arm64.dmg")
        cmd = update.install_command("dmg", dmg)
        self.assertEqual(cmd.argv, ["/usr/bin/open", str(dmg.resolve())])

    def test_a_frozen_mac_app_counts_as_installed_from_its_dmg(self):
        from unittest import mock
        with mock.patch.object(update, "WINDOWS", False), mock.patch.object(update, "MACOS", True):
            self.assertEqual(update.install_kind("openhamshack-nb"), "")            # from source
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(update.install_kind("openhamshack-nb"), "dmg")

    def test_a_copy_run_from_source_installs_nothing(self):
        with self.assertRaises(update.UpdateError):
            update.install_command("", Path("/tmp/x.deb"))

    def test_only_the_debs_own_copy_counts_as_installed(self):
        if update.WINDOWS or update.MACOS:
            self.skipTest("Linux's rule")
        self.assertEqual(update.install_kind("openhamshack-nb", Path("/usr/lib/openhamshack-nb/ohscore/update.py")), "deb")
        self.assertEqual(update.install_kind("openhamshack-nb", Path("/usr/lib/openhamshack-ham/ohscore/update.py")), "")
        self.assertEqual(update.install_kind("openhamshack-nb", REPO_ROOT / "ohscore" / "update.py"), "")

    def test_never_while_transmitting_or_recording(self):
        self.assertEqual(update.busy_reason({"keyed": True}), "transmitting")
        self.assertEqual(update.busy_reason({"recording": True}), "recording")
        self.assertEqual(update.busy_reason({"keyed": False, "recording": False, "running": True}), "")


# ---------------------------------------------------------------- when
class Schedule(unittest.TestCase):
    def test_first_check_is_due_then_once_a_day(self):
        s = update.Schedule()
        self.assertTrue(s.due(1000.0, True))
        s.mark(1000.0)
        self.assertFalse(s.due(1000.0 + 23.9 * 3600, True))
        self.assertTrue(s.due(1000.0 + 24 * 3600, True))

    def test_a_laptop_that_slept_through_the_day_checks_when_it_wakes(self):
        s = update.Schedule()
        s.mark(0.0)
        self.assertTrue(s.due(3 * 86400.0, True))

    def test_the_setting_off_means_never(self):
        s = update.Schedule()
        self.assertFalse(s.due(1000.0, False))
        s.mark(0.0)
        self.assertFalse(s.due(10 * 86400.0, False))

    def test_put_off_while_transmitting_or_recording_and_done_after(self):
        s = update.Schedule()
        self.assertFalse(s.due(1000.0, True, busy="transmitting"))
        self.assertFalse(s.due(1001.0, True, busy="recording"))
        self.assertTrue(s.due(1002.0, True, busy=""))

    def test_offline_tries_again_within_the_hour_not_tomorrow(self):
        s = update.Schedule()
        s.mark(0.0)
        s.retry_soon(0.0)
        self.assertFalse(s.due(3599.0, True))
        self.assertTrue(s.due(3600.0, True))


# ---------------------------------------------------------------- end to end
@unittest.skipUnless(HAVE_CRYPTO, "python3-cryptography is not installed")
class EndToEnd(unittest.TestCase):
    """tools/update-feed.py writes and signs a release folder with a test
    key; a local HTTP server serves it; a client checks, downloads, proves
    and builds the install command - for a .deb and for the Windows
    installer - and nothing is run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.k, self.keys = new_key()
        self.keyfile = key_file(self.k, self.root / "key" / "ed25519.key")
        self.rel = self.root / "rel"
        self.debs = {f"openhamshack-nb_0.2.0_{a}.deb": f"deb {a} ".encode() * 500 for a in ("amd64", "arm64", "all")}
        res = write_release(self.rel, self.keyfile, "0.2.0", self.debs)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.server = Served(self.rel)
        self.feed = self.server.url + "update.json"

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def test_linux_amd64_through_to_the_pkexec_command(self):
        r = update.check(self.feed, "openhamshack-nb", "0.1.8", plat="linux", arch="amd64", keys=self.keys,
                         seen=update.Seen(self.root / "seen.json"))
        self.assertEqual(r.status, "available", r.message)
        self.assertEqual(r.offer.entry.url, "openhamshack-nb_0.2.0_amd64.deb")
        self.assertEqual(r.offer.entry.notes, "Test notes")
        path = update.download(r.offer, self.root / "dl", update.user_agent("openhamshack-nb", "0.1.8"))
        self.assertEqual(path.read_bytes(), self.debs["openhamshack-nb_0.2.0_amd64.deb"])
        cmd = update.install_command("deb", path, pkexec="/usr/bin/pkexec")
        self.assertEqual(cmd.argv, ["/usr/bin/pkexec", "apt-get", "install", "-y", str(path.resolve())])

    def test_windows_waits_for_its_installer_then_gets_it_once_signed_in(self):
        # The .debs went out first: Windows has nothing yet.
        r = update.check(self.feed, "openhamshack-nb", "0.1.8", plat="windows", arch="amd64", keys=self.keys)
        self.assertEqual(r.status, "unsupported")
        exe = b"MZ installer " * 400
        res = write_release(self.rel, self.keyfile, "0.2.0", {"openhamshack-nb-0.2.0-setup.exe": exe})
        self.assertEqual(res.returncode, 0, res.stderr)
        r = update.check(self.feed, "openhamshack-nb", "0.1.8", plat="windows", arch="amd64", keys=self.keys)
        self.assertEqual(r.status, "available", r.message)
        path = update.download(r.offer, self.root / "dl", "ua")
        update.check_authenticode(path, query=lambda p: ("Valid", "CN=360 Technology, O=360 Technology, C=GB"))
        with self.assertRaises(update.NotTrusted):
            update.check_authenticode(path, query=lambda p: ("Valid", "CN=Mallory, O=Mallory"))
        cmd = update.install_command("exe", path)
        self.assertEqual(cmd.argv, [str(path.resolve()), *update.INNO_ARGS])
        # The Linux entries were kept alongside.
        m = json.loads((self.rel / "update.json").read_text())
        self.assertEqual(sorted((f["platform"], f["arch"]) for f in m["files"]),
                         [("linux", "all"), ("linux", "amd64"), ("linux", "arm64"), ("windows", "amd64")])

    def test_a_feed_signed_by_an_untrusted_key_offers_nothing(self):
        _other, other_keys = new_key()
        with self.assertLogs("ohscore.update", "WARNING"):
            r = update.check(self.feed, "openhamshack-nb", "0.1.8", plat="linux", arch="amd64", keys=other_keys)
        self.assertEqual(r.status, "refused")


if __name__ == "__main__":
    unittest.main()
