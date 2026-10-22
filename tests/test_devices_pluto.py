"""ohscore.devices.pluto.discover(): behaviour only, against a fake `iio`
module - there is no Pluto on any host these tests run on, and the real
libiio bindings are a C extension we cannot usefully fake at the ctypes
level without just re-testing libiio itself.

The fake stands in for python3-libiio's `iio` module well enough to drive
discover()'s own decisions: what a scan returned (or an exception instead),
and what a direct `iio.Context(uri)` open returns (or raises). The one
piece of real libiio plumbing discover() leans on for its Avahi fallback -
the private ctypes-based per-backend scan - is exercised by patching
`pluto._backend_scan` itself rather than reproducing that bridge, since
faking ctypes calls would test libiio's C bridge, not discover()'s
fallback logic.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import sys
import unittest
from unittest import mock

from ohscore.devices import pluto

PLUTO_SERIAL = "UQRUR7HPFYWAMKGY"
# The exact three entries libiio's scan_contexts() returned on a real
# laptop (Debian 13, libiio 0.26) with a Pluto nano on USB and avahi
# running - see pluto.py's module docstring.
REAL_SCAN = {
    "ip:Nano.local": f"192.168.2.1 (Nano PlutoSDR (Z7010-AD9361)), serial={PLUTO_SERIAL}",
    "local:": "(ADP0,BAT0,coretemp,nvme on LENOVO)",
    "usb:3.4.5": f"0456:b673 (Analog Devices Inc. PlutoSDR (ADALM-PLUTO)), serial={PLUTO_SERIAL}",
}


class _FakeContext:
    def __init__(self, devices=None, attrs=None):
        self._devices = devices or {}
        self.attrs = attrs or {}

    def find_device(self, name):
        return self._devices.get(name)

    def set_timeout(self, ms):
        pass  # the fake never blocks, so there is nothing to bound


def _pluto_context(model="Nano PlutoSDR (Z7010-AD9361)", serial=PLUTO_SERIAL):
    attrs = {"hw_model": model}
    if serial:
        attrs["hw_serial"] = serial
    return _FakeContext(devices={"ad9361-phy": object()}, attrs=attrs)


class FakeIIO:
    """uri -> Context stands in for `iio.Context(uri)`; missing uris, and
    anything mapped to an Exception instance, raise - exactly what a dark
    address does for real, just instantly instead of after a TCP timeout."""

    def __init__(self, scan=None, scan_error=None, contexts=None):
        self._scan = scan or {}
        self._scan_error = scan_error
        self._contexts = contexts or {}

    def scan_contexts(self):
        if self._scan_error is not None:
            raise self._scan_error
        return dict(self._scan)

    def Context(self, uri):
        c = self._contexts.get(uri, OSError(f"no such context: {uri}"))
        if isinstance(c, BaseException):
            raise c
        return c


def _discover(fake_iio, **kw):
    """Run discover() against `fake_iio` with no real USB-network
    interfaces in play, so results depend only on what the test wires up
    in `fake_iio`, never on the host this suite happens to run on. Name
    resolution is faked the same way: `resolve` maps a hostname to the
    IPv4 address it should resolve to, and anything else fails to."""
    resolve = kw.pop("resolve", {})
    with mock.patch.dict(sys.modules, {"iio": fake_iio}), \
         mock.patch.object(pluto, "_usb_network_addresses", return_value=[]), \
         mock.patch.object(pluto, "_resolve_ipv4", side_effect=lambda name, t: resolve.get(name)):
        return pluto.discover(timeout_s=0.2, **kw)


class FullScanWorks(unittest.TestCase):
    def test_local_and_unrecognised_entries_are_dropped(self):
        fake = FakeIIO(scan=REAL_SCAN)
        results = _discover(fake)
        uris = [uri for uri, _ in results]
        self.assertNotIn("local:", uris)
        for uri in uris:
            self.assertIn(uri, ("ip:Nano.local", "usb:3.4.5", "ip:192.168.2.1"))

    def test_same_serial_over_ip_and_usb_collapses_to_one_entry_preferring_numeric_ip(self):
        # The scan alone never offers a literal "ip:192.168.2.1" uri (only
        # the mDNS name, "ip:Nano.local") - that candidate comes from
        # discover()'s own direct probe of the Pluto's default address,
        # which here answers as the same radio (same serial).
        fake = FakeIIO(scan=REAL_SCAN, contexts={"ip:192.168.2.1": _pluto_context()})
        results = _discover(fake)
        uris = [uri for uri, _ in results]
        self.assertEqual(uris.count("ip:192.168.2.1"), 1)
        self.assertNotIn("ip:Nano.local", uris)
        self.assertNotIn("usb:3.4.5", uris)

    def test_nothing_found_returns_an_empty_list_without_raising(self):
        fake = FakeIIO(scan={})
        results = _discover(fake)
        self.assertEqual(results, [])


# A LibreSDR on a home LAN (libre-2, 192.0.2.74, DL1JM firmware) as
# libiio's mDNS path describes a serial-less radio: the hostname in the
# uri, the address it happened to answer on - here link-local IPv6 - at
# the front of the description, and no serial. Find listed exactly that
# uri on 04/10.
LIBRE_MODEL = "LibreSDR (Z7020-AD9361)"
LIBRE_V6 = {"ip:libre-2.local": f"fe80::d8c2:4fff:fe1a:2b3c%enp3s0 ({LIBRE_MODEL})"}
LIBRE_V4 = {"ip:libre-2.local": f"192.0.2.74 ({LIBRE_MODEL})"}
USB_PLUTO = {"usb:3.4.5": REAL_SCAN["usb:3.4.5"]}


class PreferIPv4(unittest.TestCase):
    def test_libre_named_by_mdns_with_ipv6_description_is_listed_by_its_ipv4_address(self):
        results = _discover(FakeIIO(scan=LIBRE_V6), resolve={"libre-2.local": "192.0.2.74"})
        self.assertEqual(len(results), 1)
        uri, desc = results[0]
        self.assertEqual(uri, "ip:192.0.2.74")
        self.assertTrue(desc.startswith("libre-2.local ("), desc)  # the name stays visible
        self.assertIn(LIBRE_MODEL, desc)

    def test_ipv4_in_the_description_is_used_without_resolving_the_name(self):
        with mock.patch.dict(sys.modules, {"iio": FakeIIO(scan=LIBRE_V4)}), \
             mock.patch.object(pluto, "_usb_network_addresses", return_value=[]), \
             mock.patch.object(pluto, "_resolve_ipv4") as res:
            results = pluto.discover(timeout_s=0.2)
        res.assert_not_called()
        self.assertEqual(results, [("ip:192.0.2.74", f"libre-2.local ({LIBRE_MODEL})")])

    def test_a_name_that_will_not_resolve_is_kept_rather_than_the_ipv6_address(self):
        results = _discover(FakeIIO(scan=LIBRE_V6))
        self.assertEqual([u for u, _ in results], ["ip:libre-2.local"])

    def test_numeric_and_named_entries_for_one_serial_less_radio_are_merged(self):
        # The mDNS entry plus an entry that reached the same box by number
        # (a per-backend scan or a probe): nothing to merge on but the address.
        scan = dict(LIBRE_V6, **{"ip:192.0.2.74": f"192.0.2.74 ({LIBRE_MODEL})"})
        results = _discover(FakeIIO(scan=scan), resolve={"libre-2.local": "192.0.2.74"})
        self.assertEqual(results, [("ip:192.0.2.74", f"libre-2.local ({LIBRE_MODEL})")])

    def test_usb_pluto_and_lan_libre_are_two_radios_each_listed_once(self):
        scan = dict(REAL_SCAN, **LIBRE_V6)
        fake = FakeIIO(scan=scan, contexts={"ip:192.168.2.1": _pluto_context()})
        results = _discover(fake, resolve={"libre-2.local": "192.0.2.74"})
        self.assertEqual(sorted(u for u, _ in results), ["ip:192.0.2.74", "ip:192.168.2.1"])
        # The Pluto's own mDNS name survives in its label too.
        pluto_desc = dict(results)["ip:192.168.2.1"]
        self.assertTrue(pluto_desc.startswith("Nano.local ("), pluto_desc)
        self.assertIn(PLUTO_SERIAL, pluto_desc)

    def test_usb_only_pluto_is_still_listed_by_usb(self):
        results = _discover(FakeIIO(scan=USB_PLUTO))
        self.assertEqual(results, [("usb:3.4.5", USB_PLUTO["usb:3.4.5"])])


class Dedupe(unittest.TestCase):
    """_dedupe on its own, for the cases discover() cannot easily stage."""

    def test_two_usb_plutos_of_one_model_are_not_merged_on_vendor_product(self):
        a = pluto._Candidate("usb:3.4.5", "0456:b673 (PlutoSDR (ADALM-PLUTO)), serial=AAA", "AAA")
        b = pluto._Candidate("usb:3.6.7", "0456:b673 (PlutoSDR (ADALM-PLUTO)), serial=BBB", "BBB")
        self.assertEqual([c.uri for c in pluto._dedupe([a, b])], ["usb:3.4.5", "usb:3.6.7"])

    def test_two_serial_less_usb_radios_of_one_model_are_not_merged(self):
        a = pluto._Candidate("usb:3.4.5", "0456:b673 (PlutoSDR (ADALM-PLUTO))", None)
        b = pluto._Candidate("usb:3.6.7", "0456:b673 (PlutoSDR (ADALM-PLUTO))", None)
        self.assertEqual(len(pluto._dedupe([a, b])), 2)

    def test_different_serials_behind_one_address_are_never_merged(self):
        a = pluto._Candidate("ip:192.168.2.1", "192.168.2.1 (Pluto), serial=AAA", "AAA")
        b = pluto._Candidate("ip:pluto.local", "192.168.2.1 (Pluto), serial=BBB", "BBB")
        self.assertEqual(len(pluto._dedupe([a, b])), 2)

    def test_a_serial_less_entry_joins_the_radio_whose_address_it_shares(self):
        usb = pluto._Candidate("usb:1.2.3", "0456:b673 (Pluto), serial=AAA", "AAA")
        bare = pluto._Candidate("ip:pluto.local", "192.168.2.1 (Pluto)", None)
        ip = pluto._Candidate("ip:192.168.2.1", "192.168.2.1 (Pluto), serial=AAA", "AAA")
        out = pluto._dedupe([usb, bare, ip])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].uri, "ip:192.168.2.1")
        self.assertEqual(out[0].serial, "AAA")
        self.assertTrue(out[0].description.startswith("pluto.local ("), out[0].description)

    def test_ipv4_beats_name_beats_ipv6_beats_usb(self):
        order = ["usb:1.2.3", "ip:fe80::1%eth0", "ip:libre-2.local", "ip:192.0.2.74"]
        self.assertEqual(sorted(order, key=pluto._preference), list(reversed(order)))


class FullScanFails(unittest.TestCase):
    def test_avahi_failure_falls_back_to_a_usb_backend_scan(self):
        # Matches what was actually observed: the combined scan raises,
        # taking USB down with it, with no mention of Avahi in the
        # exception text at all.
        fake = FakeIIO(scan_error=OSError(26, "Text file busy"))
        usb_only = {"usb:3.4.5": f"0456:b673 (Analog Devices Inc. PlutoSDR (ADALM-PLUTO)), serial={PLUTO_SERIAL}"}

        def fake_backend_scan(iio_mod, backend):
            self.assertIs(iio_mod, fake)
            return usb_only if backend == b"usb" else {}

        with mock.patch.object(pluto, "_backend_scan", side_effect=fake_backend_scan):
            notes = []
            results = _discover(fake, notes=notes)
        self.assertEqual(results, [("usb:3.4.5", usb_only["usb:3.4.5"])])
        self.assertTrue(notes)  # something explains the degraded scan

    def test_a_scan_exception_never_propagates_out_of_discover(self):
        fake = FakeIIO(scan_error=RuntimeError("libiio blew up"))
        with mock.patch.object(pluto, "_backend_scan", return_value={}):
            results = _discover(fake)
        self.assertEqual(results, [])


class MissingLibrary(unittest.TestCase):
    def test_no_python3_libiio_returns_an_empty_list_with_a_note(self):
        # sys.modules[name] = None makes `import iio` raise ImportError,
        # the same trick tests/test_modes_glue.py uses for a missing
        # optional package.
        with mock.patch.dict(sys.modules, {"iio": None}):
            notes = []
            results = pluto.discover(notes=notes)
        self.assertEqual(results, [])
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
