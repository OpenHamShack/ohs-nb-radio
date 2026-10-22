"""Pluto family (ADALM-Pluto, Pluto+, LibreSDR, Pluto nano) through the
libiio 0.26 Python bindings directly - no pyadi-iio, which Debian does not
package. All of them are an AD936x behind the same IIO driver, so one class
serves; the variant is identified at runtime from the context attributes,
not from a product name.

NOT YET TESTED ON HARDWARE: there is no Pluto on the development host. The
attribute names follow the ADI driver (drivers/iio/adc/ad9361.c) and the
research notes; each step that could plausibly differ between firmware
versions is wrapped so a failure is reported with the attribute's name.

Decisions:

- **Sample rate** 1.2 MS/s by default (an integer 100 x 12 kHz). Below
  2.083 MS/s the AD9361 needs its x4 FIR; `ad9361_set_bb_rate()` from
  libad9361 (via ctypes) loads a matching one, as DJ0ABR does. Without
  libad9361 we load our own x4 FIR through `filter_fir_config` and enable it.
  Some firmware refuses both (a Nano PlutoSDR on Tezuka tezuka-v0.3.21:
  every filter_fir_config write is EINVAL, the attribute reads "FIR Rx: 0,0
  Tx: 0,0", and libad9361 returns -22 for the same reason). Then the radio
  runs at the smallest integer multiple M of the engine's rate that needs no
  FIR (2.4 MS/s for both 1.2 MS/s and 600 kS/s) and this class decimates on
  receive and interpolates on transmit (ohscore/dsp/multirate.py), so `fs` -
  and everything above the device - is unchanged.
- **Receive DC**: the AD9361's RF/BB DC and quadrature trackers are left on,
  and the engine places DC in the middle beacon's guard band (radio.py), so
  the tracker's notch and any residual spur land where nobody transmits.
- **Transmit**: the TX LO is placed 30 kHz outside the uplink passband by the
  engine (radio.plan_tx_lo) and the signal by the NCO, so LO leakage never
  reaches the transponder. Unkeyed, the TX LO is powered down and the
  attenuation is at its maximum (-89.75 dB). While keyed the buffer is
  streamed (cyclic off) and the engine writes continuously, silence
  included - nobody has documented what the DAC does on underflow.
- **Discovery** (discover(), below) never trusts `iio.scan_contexts()` alone.
  Observed on a real laptop (Debian 13, libiio 0.26, avahi-daemon not
  installed): the combined scan raises `OSError [Errno 26] Text file busy`
  and takes USB down with it, not just the network half - the exception's
  text never mentions Avahi (that sentence is only ever printed by libiio's
  C code to stderr), so the one way to tell *why* is to check whether
  avahi-daemon's own socket exists, not to pattern-match the error. A failed
  combined scan falls back to asking libiio for one backend at a time
  (sidesteps Avahi entirely for "usb"), and direct probes of a short list of
  likely IP addresses run regardless of how the scan went, each bounded to
  `timeout_s` so a radio that simply isn't there costs about a second, not
  the kernel's multi-minute TCP connect retry budget.
"""
from __future__ import annotations

import ctypes
import ipaddress
import logging
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import host
from .base import Device, DeviceError

log = logging.getLogger("ohscore.devices.pluto")

TX_ATTEN_MAX = -89.75
NO_FIR_MIN = 2_083_334     # lowest AD9361 baseband rate without the x4 FIR in the chain

# Description text libiio's scan returns for a real Pluto/LibreSDR, e.g.
# "192.168.2.1 (Nano PlutoSDR (Z7010-AD9361)), serial=UQRUR7HPFYWAMKGY" --
# every AD936x variant we support names itself with one of these. "local:"
# (a laptop's own hwmon/battery/NVMe sensors) and anything else unrecognised
# is dropped rather than offered as a radio.
_AD936X_MARKERS = ("pluto", "ad9361", "ad9363", "ad9364", "libresdr")


def _looks_like_ad936x(description: str) -> bool:
    d = description.lower()
    return any(m in d for m in _AD936X_MARKERS)


def _serial_from_description(description: str) -> str | None:
    m = re.search(r"serial=(\S+)", description)
    return m.group(1) if m else None


@dataclass
class _Candidate:
    uri: str
    description: str
    serial: str | None
    # Identities this candidate was known by before _prefer_ipv4 rewrote
    # its uri, so the rewrite never costs it a match in _dedupe.
    aliases: frozenset = frozenset()


def _ipv4(text: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        return None


def _ipv6(text: str) -> str | None:
    # libiio's mDNS path writes link-local addresses with their scope
    # ("fe80::1%enp3s0"); the scope says which interface, not which radio,
    # so it is dropped for matching purposes.
    try:
        return str(ipaddress.IPv6Address(text.strip("[]").split("%", 1)[0]))
    except ValueError:
        return None


def _uri_host(uri: str) -> str | None:
    return uri[len("ip:"):] if uri.startswith("ip:") else None


def _described_host(description: str) -> str | None:
    """The address libiio puts in front of the model: "192.168.2.1 (...)"
    or, from the mDNS path, "fe80::1%eth0 (...)". USB entries start with a
    vendor:product pair ("0456:b673") instead, which is neither."""
    m = re.match(r"(\S+) \(", description)
    return m.group(1) if m else None


def _preference(uri: str) -> int:
    """Lower sorts first. The numeric IPv4 route needs no USB permissions
    and no mDNS; a name needs mDNS to resolve on every later start, not
    just this one; an IPv6 address from the mDNS path is usually
    link-local, so it only works with the interface scope attached and
    breaks when the interface is renamed; usb: needs udev to have given
    this user access to the device node."""
    host_ = _uri_host(uri)
    if host_ is not None:
        if _ipv4(host_):
            return 0
        return 2 if _ipv6(host_) else 1
    if uri.startswith("usb:"):
        return 3
    return 4


def _identity(text: str) -> str | None:
    if v4 := _ipv4(text):
        return f"v4:{v4}"
    if v6 := _ipv6(text):
        return f"v6:{v6}"
    # Anything else with a colon is a USB vendor:product pair, which every
    # Pluto of one model shares - matching on it would merge two radios.
    if ":" in text or "." not in text:
        return None
    return f"name:{text.lower().rstrip('.')}"


def _identities(c: _Candidate) -> set[str]:
    """Everything that says "this is that radio": its serial, and every
    address or name it was reached or described by. Two candidates that
    share any one of these are the same radio. The serial is the only
    identity a USB entry has; an mDNS entry for a LibreSDR can have no
    serial at all (Find listed "ip:libre-2.local" on 04/10 with nothing to
    merge on), so without the address keys it could never meet the
    numeric entry for the same box."""
    keys = set(c.aliases)
    if c.serial:
        keys.add(f"serial:{c.serial}")
    for text in (_uri_host(c.uri), _described_host(c.description)):
        if text and (k := _identity(text)):
            keys.add(k)
    return keys


def _resolve_ipv4(name: str, timeout_s: float) -> str | None:
    """`name`'s IPv4 address, or None. A .local name goes through nss-mdns
    when that is installed and to unicast DNS when it is not (usually a
    quick NXDOMAIN, not always), and getaddrinfo cannot be cancelled - so,
    as with _open_with_timeout, it runs on its own thread and this stops
    waiting at the deadline."""
    box: list = []

    def run():
        try:
            infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
            box.append(infos[0][4][0] if infos else None)
        except (OSError, UnicodeError):
            box.append(None)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    return box[0] if box else None


def _prefer_ipv4(c: _Candidate, timeout_s: float) -> _Candidate:
    """Turn ip:<name> or ip:<IPv6> into ip:<IPv4> when the radio's IPv4
    address can be known - from the description if libiio put it there,
    else by resolving the name - because the number is what keeps working
    on a host without Avahi or nss-mdns, which is the common case on the
    laptops this runs on. Nothing is lost: the name moves to the front of
    the description, so the list still says "libre-2.local", and the old
    identities ride along as aliases so merging still matches on them."""
    host_ = _uri_host(c.uri)
    if host_ is None or _ipv4(host_):
        return c
    named = _ipv6(host_) is None
    described = _described_host(c.description)
    v4 = _ipv4(described) if described else None
    if v4 is None and named:
        v4 = _resolve_ipv4(host_, timeout_s)
    if v4 is None:
        return c
    desc = c.description
    if named:
        desc = host_ + desc[len(described):] if described else f"{host_} {desc}"
    return _Candidate(f"ip:{v4}", desc, c.serial, frozenset(_identities(c)))


def _dedupe(cands: list[_Candidate]) -> list[_Candidate]:
    """The same radio shows up more than once in practice: ip: and usb:
    for one Pluto share a serial (observed), the mDNS scan can name a
    LibreSDR with no serial while a probe reaches it by number, and a
    direct probe can repeat something the scan already found. Candidates
    are grouped by any shared identity (serial, IPv4, IPv6 or name - see
    _identities), except that two different serials are never merged:
    two radios behind one address is unlikely, but listing both is the
    safe way to be wrong. Each group keeps its most-preferred uri (see
    _preference), and a hostname known to any member replaces a bare
    address at the front of the winner's description so it stays visible."""
    groups: list[dict] = []
    for c in cands:
        keys, serial = _identities(c), c.serial
        hits = [g for g in groups
                if g["keys"] & keys and not (serial and g["serial"] and g["serial"] != serial)]
        if hits:
            g = hits[0]
            for other in hits[1:]:
                if g["serial"] and other["serial"] and g["serial"] != other["serial"]:
                    continue
                g["members"] += other["members"]
                g["keys"] |= other["keys"]
                g["serial"] = g["serial"] or other["serial"]
                groups.remove(other)
        else:
            g = {"keys": set(), "serial": None, "members": []}
            groups.append(g)
        g["members"].append(c)
        g["keys"] |= keys
        g["serial"] = g["serial"] or serial

    out = []
    for g in groups:
        # min() keeps the first-seen among equals, so scan order breaks ties.
        best = min(g["members"], key=lambda m: _preference(m.uri))
        desc = best.description
        described = _described_host(desc)
        # The name as the radio announced it ("Nano.local"), not the
        # case-folded key it was matched on.
        names = [h for m in g["members"]
                 for h in (_uri_host(m.uri), _described_host(m.description))
                 if h and (_identity(h) or "").startswith("name:")]
        if names and described and (_ipv4(described) or _ipv6(described)):
            desc = names[0] + desc[len(described):]
        out.append(_Candidate(best.uri, desc, g["serial"]))
    return out


def _backend_scan(iio_mod, backend: bytes) -> dict[str, str]:
    """Scan one libiio backend only (b"usb" or b"ip"), bypassing whatever
    the combined scan does to merge them - which is how it drags USB down
    with Avahi (see the module docstring). There is no public per-backend
    scan in the Python binding, only the private ctypes calls
    `iio.scan_contexts()` itself uses, so every symbol is feature-detected:
    a binding that lacks one (a future libiio, or a different wrapper)
    yields no candidates from this path instead of an AttributeError."""
    names = ("_create_scan_context", "_get_context_info_list", "_context_info_get_uri",
              "_context_info_get_description", "_context_info_list_free", "_destroy_scan_context",
              "_POINTER", "_byref", "_ContextInfoPtr")
    if not all(hasattr(iio_mod, n) for n in names):
        return {}
    ptr = iio_mod._POINTER(iio_mod._ContextInfoPtr)()
    ctx = iio_mod._create_scan_context(backend, 0)
    try:
        n = iio_mod._get_context_info_list(ctx, iio_mod._byref(ptr))
        out = {}
        for i in range(n):
            uri = iio_mod._context_info_get_uri(ptr[i]).decode("ascii")
            out[uri] = iio_mod._context_info_get_description(ptr[i]).decode("ascii")
        iio_mod._context_info_list_free(ptr)
        return out
    finally:
        iio_mod._destroy_scan_context(ctx)


def _usb_network_addresses() -> list[str]:
    """IPv4 addresses ending .10 on a /24, bound to an enx*/usb* interface
    - the host side of the Pluto's own RNDIS-over-USB link (observed:
    enx00e022121743, 192.168.2.10/24, Pluto at .1). Linux-only (SIOCGIFADDR
    via fcntl); any failure - no such ioctl, no permission, nothing found -
    just means no candidates come from this source, not an error."""
    try:
        import fcntl
        names = [n for _, n in socket.if_nameindex() if n.startswith(("enx", "usb"))]
    except (ImportError, AttributeError, OSError):
        return []
    SIOCGIFADDR, SIOCGIFNETMASK = 0x8915, 0x891B

    def _ioctl_ip(sock, name: str, request: int) -> str | None:
        try:
            packed = struct.pack("256s", name.encode("ascii")[:15])
            res = fcntl.ioctl(sock.fileno(), request, packed)
        except OSError:
            return None
        return socket.inet_ntoa(res[20:24])

    out = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for name in names:
            addr = _ioctl_ip(s, name, SIOCGIFADDR)
            mask = _ioctl_ip(s, name, SIOCGIFNETMASK)
            if addr and mask == "255.255.255.0" and addr.endswith(".10"):
                out.append(addr)
    return out


def _direct_candidates() -> list[str]:
    """URIs worth trying even when the scan found nothing (or degraded):
    the Pluto's factory-default address, its mDNS name (in case Avahi is
    running but the combined scan missed it for some unrelated reason),
    and the .1 address on every USB-network interface that looks like a
    Pluto's own RNDIS link."""
    uris = ["ip:192.168.2.1", "ip:pluto.local"]
    for addr in _usb_network_addresses():
        host = addr[:-len("10")] + "1"
        uri = f"ip:{host}"
        if uri not in uris:
            uris.append(uri)
    return uris


def _open_with_timeout(iio_mod, uri: str, timeout_s: float):
    """Open `uri` as an IIO context, giving up after timeout_s even though
    the binding has no way to cancel an in-flight connect. A dead address
    on a live subnet (route exists, nothing answers) hangs the normal way
    for the kernel's full SYN-retry budget - tens of seconds to minutes -
    not the handful of seconds this needs to feel instant, so the open
    runs on its own thread and this just stops waiting at the deadline;
    if it finishes later anyway, nothing is left depending on it."""
    box: list = []

    def run():
        try:
            ctx = iio_mod.Context(uri)
            try:
                ctx.set_timeout(max(1, int(timeout_s * 1000)))
            except Exception:  # noqa: BLE001 - best-effort; absence doesn't disqualify the context
                pass
            box.append(ctx)
        except Exception:  # noqa: BLE001 - any failure to open just means "not there"
            box.append(None)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    return box[0] if box else None


def _probe_ad936x(iio_mod, uri: str, timeout_s: float) -> _Candidate | None:
    ctx = _open_with_timeout(iio_mod, uri, timeout_s)
    if ctx is None:
        return None
    try:
        if ctx.find_device("ad9361-phy") is None:
            return None  # answered, but it is not a Pluto family radio
        attrs = getattr(ctx, "attrs", {})
        model = attrs.get("hw_model") or attrs.get("hw_model_variant") or "AD936x"
        serial = attrs.get("hw_serial")
        host = uri.split(":", 1)[1] if ":" in uri else uri
        desc = f"{host} ({model})" + (f", serial={serial}" if serial else "")
        return _Candidate(uri, desc, serial)
    except Exception:  # noqa: BLE001 - a context that answers but misbehaves is not a candidate
        return None


def _avahi_running() -> bool:
    return Path("/var/run/avahi-daemon/socket").exists()


def discover(timeout_s: float = 1.0, notes: list[str] | None = None) -> list[tuple[str, str]]:
    """Find Pluto-family radios: ADALM-Pluto, Pluto+, LibreSDR, Pluto nano -
    all AD936x under one IIO driver. Returns (uri, description) pairs, one
    per radio found; never raises - on a laptop with nothing plugged in,
    every step here timing out or finding nothing is the normal case, not
    an error. `notes`, if given, collects user-facing sentences about
    anything that degraded along the way (Settings' Find button uses this
    to explain a "nothing found" result instead of just shrugging)."""
    # import_iio() turns every way the bindings can fail to load (missing,
    # no DLL on Windows, libiio 1.0) into one sentence; discover() never
    # raises, so that sentence becomes a note instead.
    try:
        iio = import_iio()
    except DeviceError as e:
        if notes is not None:
            notes.append(str(e))
        return []

    cands: list[_Candidate] = []

    def _absorb(scan: dict[str, str]):
        for uri, desc in scan.items():
            if _looks_like_ad936x(desc):
                cands.append(_Candidate(uri, desc, _serial_from_description(desc)))

    try:
        _absorb(iio.scan_contexts())
    except Exception as e:  # noqa: BLE001 - libiio surfaces this as plain OSError today, but any
        # failure here must not take the rest of discover() down with it.
        if notes is not None:
            if _avahi_running():
                notes.append(f"Full device scan failed ({e}); fell back to a USB/IP-only search.")
            else:
                notes.append("Full device scan failed; network discovery needs avahi-daemon "
                              "(sudo apt install avahi-daemon). Fell back to a USB/IP-only search.")
        # Confirmed on this (avahi-less) dev host: the "usb" backend scan
        # comes back clean (empty, here - no radio attached), but "ip"
        # still raises the exact same OSError. libiio's IP backend scan
        # finds *other* IIOD hosts by mDNS, so it is Avahi's codepath too
        # - only "usb" actually sidesteps the bug. Each backend is tried
        # and caught on its own so one still-broken backend can never
        # cost the other, which is the entire point of this fallback.
        for backend in (b"usb", b"ip"):
            try:
                _absorb(_backend_scan(iio, backend))
            except Exception:  # noqa: BLE001 - this fallback is itself best-effort
                pass

    for uri in _direct_candidates():
        try:
            cand = _probe_ad936x(iio, uri, timeout_s)
        except Exception:  # noqa: BLE001 - a bad probe must not stop the others
            cand = None
        if cand is not None:
            cands.append(cand)

    cands = [_prefer_ipv4(c, timeout_s) for c in cands]
    return [(c.uri, c.description) for c in _dedupe(cands)]


def import_iio():
    """The libiio Python bindings, or DeviceError with the sentence to act on.

    ImportError is not the only way this fails. On Windows the bindings
    resolve libiio.dll at import time: the build bundles libiio 0.26 and
    host.bundled_libiio() points the import at it, but a run from source or
    a damaged install falls back to whatever DLL the system has. No DLL
    makes ctypes raise TypeError or OSError, and a libiio 1.0 DLL (ADI's
    newest installer, a different interface) lacks the 0.2x symbols the
    bindings look up, which is an AttributeError. All of them mean "the
    right libiio is missing", so all of them say so instead of escaping as
    a traceback."""
    try:
        with host.bundled_libiio():
            import iio
    except ImportError as e:
        raise DeviceError(host.hint("libiio")) from e
    except AttributeError as e:
        raise DeviceError(f"The installed libiio is not the 0.2x series these bindings speak ({e}); "
                          f"libiio 1.0 changed its interface. {host.hint('libiio')}") from e
    except (OSError, TypeError) as e:
        raise DeviceError(f"libiio could not be loaded ({e}). {host.hint('libiio')}") from e
    return iio


def _fir_x4(ntaps: int = 128) -> list[int]:
    """A x4 decimation/interpolation FIR for the AD9361's programmable stage:
    passband to 0.4 of the output rate, int16 coefficients."""
    from ..dsp.fir import lowpass
    h = lowpass(0.11, 1.0, ntaps - 1)       # cutoff relative to the FIR's input rate (4x output)
    h = np.concatenate([h, [0.0]])
    # Unity DC gain would leave the taps tiny in int16; scale so the largest
    # is ~3/4 of full scale and let the stage's GAIN field set the level.
    # (Unverified on hardware: compare levels with libad9361's FIR if both
    # are available.)
    return [int(round(c)) for c in h / np.abs(h).max() * 24000]


class PlutoDevice(Device):
    rx_prefetch = True           # read on its own thread (Device.rx_prefetch)
    kind = "pluto"
    can_tx = True
    # The hardware runs at m x fs when its firmware refuses the FIR
    # (_set_rate); m = 1 is the normal case, with no software rate change.
    m = 1
    dec = None
    interp = None
    # Tuning range (the AD9364 identity; open() narrows it for an AD9363).
    rx_range = (70e6, 6e9)
    tx_range = (46.875e6, 6e9)
    identity = ""
    # How the rate was reached, for the log and a diagnostics report: the
    # FIR question is the first thing to ask about a Pluto that misbehaves
    # (see _set_rate).
    fir = ""
    # What the radio says it is, for HAM's chip check and the AD9364 fix
    # (which picks ADI's command by firmware version): context attributes,
    # read once at open() and never written.
    fw_version = ""
    serial = ""

    def __init__(self, uri: str = "ip:192.168.2.1", fs: float = 1_200_000.0, cfg: dict | None = None):
        self.uri = uri
        self.fs = float(fs)
        self.cfg = cfg or {}
        self.ctx = None
        self.rxbuf = None
        self.txbuf = None
        self.left = np.zeros(0, np.complex64)
        self.block = int(self.fs * 0.075)     # 75 ms: the engine's block, and DJ0ABR's order of size
        self.tx_block = self.block
        self.model = ""
        self.tx_on = False
        self._air_end = self._real_end = 0.0      # see tx_queued(); restarted by each tx_start
        self.rx_if = None
        self.tx_lo = None
        self.notes: list[str] = []

    # -- helpers -------------------------------------------------------------
    def _attr(self, chan, name: str, value):
        try:
            chan.attrs[name].value = str(value)
        except (KeyError, OSError) as e:
            raise DeviceError(f"Pluto: could not set {name}={value} ({e})") from e

    def _try(self, chan, name: str, value):
        try:
            chan.attrs[name].value = str(value)
            return True
        except (KeyError, OSError):
            return False

    def open(self) -> None:
        iio = import_iio()
        try:
            self.ctx = iio.Context(self.uri)
        except OSError as e:
            # LibreSDR is said to default to ip:198.51.100.10, but the research
            # found no source for that, so the sentence points at the scan.
            # On Windows libiio reports failure through the Win32 last-error,
            # which its bindings do not read, so the OSError arrives as
            # "[Errno 0] No error" - worse than saying nothing.
            why = f" ({e})" if e.errno else ""
            # The Windows build carries libiio alone, not ADI's iio_info, so
            # there the sentence points at Find, and at the installer's
            # driver option rather than at a download. ">", not "›": this
            # sentence is also printed by the console build, whose code page
            # has no "›".
            if host.WINDOWS:
                lists = "Find in Settings > Radio lists what is found"
                usb = (" On Windows, a Pluto on USB needs ADI's PlutoSDR drivers: run the installer again "
                       "with \"Install the PlutoSDR USB drivers\" ticked.")
            elif host.MACOS:
                # The Mac app carries no iio_info either. It needs no driver:
                # macOS takes the Pluto's USB network interface as it is, so
                # a Pluto on USB is ip:192.168.2.1 there too.
                lists, usb = "Find in Settings > Radio lists what is found", ""
            else:
                lists, usb = "iio_info -s lists what is found", ""
            # Seen 07/10/2026: a LibreSDR on the LAN, reachable by ping and a
            # direct TCP connection from the same Mac, refused by libiio with
            # exactly this errno - macOS's Local Network privacy (macOS 15+)
            # blocking the socket before it ever reached the radio, with no
            # prompt because Info.plist had not asked for it yet.
            local_network = host.local_network_hint(e.errno, _uri_host(self.uri) or "")
            raise DeviceError(f"No Pluto at {self.uri}{why}. A LibreSDR or Pluto+ on Ethernet has its own "
                              f"address (ip:<address>); {lists}.{usb}{local_network}") from e
        attrs = getattr(self.ctx, "attrs", {})
        self.model = attrs.get("hw_model", "") or attrs.get("hw_model_variant", "") or "AD936x"
        # Which chip the firmware runs it as (docs/ham/DESIGN-HAM.md 4.3): as
        # an AD9363 (ADI's default) the driver keeps the LOs inside
        # 325 MHz-3.8 GHz; as an AD9364 ("the AD9364 hack") it allows RX from
        # 70 MHz and TX from 46.875 MHz to 6 GHz. NB, on 739 MHz and 2.4 GHz,
        # works either way; OpenHamShack Radio's 2 m needs the AD9364 setting.
        self.identity = (attrs.get("ad9361-phy,model", "") or "").lower()
        if self.identity == "ad9363":
            self.rx_range = self.tx_range = (325e6, 3.8e9)
        self.fw_version = attrs.get("fw_version", "") or ""
        self.serial = attrs.get("hw_serial", "") or ""
        self.phy = self.ctx.find_device("ad9361-phy")
        self.rxdev = self.ctx.find_device("cf-ad9361-lpc")
        self.txdev = self.ctx.find_device("cf-ad9361-dds-core-lpc")
        if not (self.phy and self.rxdev and self.txdev):
            raise DeviceError(f"{self.uri} is not an AD936x (no ad9361-phy / cf-ad9361 devices)")
        self.rx_lo_ch = self.phy.find_channel("altvoltage0", True)
        self.tx_lo_ch = self.phy.find_channel("altvoltage1", True)
        self.rx_ch = self.phy.find_channel("voltage0", False)
        self.tx_ch = self.phy.find_channel("voltage0", True)
        self._set_rate()
        self._attr(self.rx_ch, "rf_bandwidth", int(self.fs))
        self._try(self.tx_ch, "rf_bandwidth", int(self.fs))
        self._try(self.rx_ch, "rf_port_select", "A_BALANCED")
        self._try(self.tx_ch, "rf_port_select", "A")
        for name in ("quadrature_tracking_en", "rf_dc_offset_tracking_en", "bb_dc_offset_tracking_en"):
            self._try(self.rx_ch, name, 1)
        self.set_rx_gain(self.cfg.get("rxGainMode", "slow_attack"), float(self.cfg.get("rxGain", 40.0)))
        # Transmit quiet until keyed: full attenuation and the TX LO off.
        self._attr(self.tx_ch, "hardwaregain", TX_ATTEN_MAX)
        self._try(self.tx_lo_ch, "powerdown", 1)
        for i in (0, 1):
            self.rxdev.find_channel(f"voltage{i}", False).enabled = True
        try:
            self.rxdev.set_kernel_buffers_count(4)
        except (AttributeError, OSError):
            pass
        self.rxbuf = iio.Buffer(self.rxdev, self.block * self.m, False)
        self.iio = iio

    def set_rx_gain(self, mode: str, db: float) -> None:
        """Live, while receiving: these are the same attribute writes a gain
        slider in GNU Radio or SDR++ makes mid-stream, and the receive
        buffer carries on. Mode first, because the driver only honours a
        hardwaregain written while the mode is manual."""
        self._attr(self.rx_ch, "gain_control_mode", mode)
        if mode == "manual":
            self._attr(self.rx_ch, "hardwaregain", float(db))

    def rx_gain_now(self) -> float | None:
        # The driver reads back the gain its AGC chose ("54.000000 dB").
        try:
            return float(str(self.rx_ch.attrs["hardwaregain"].value).split()[0])
        except (AttributeError, KeyError, OSError, ValueError, IndexError):
            return None

    def _set_rate(self):
        """Below 2.083 MS/s the x4 FIR must be in the chain: libad9361's
        own, else ours. If the firmware refuses both, run the hardware
        faster and change rate in software (module docstring)."""
        self.m, self.dec = 1, None
        if self.fs >= NO_FIR_MIN:
            self._attr(self.rx_ch, "sampling_frequency", int(self.fs))
            self.fir = "not needed"
            log.info("Pluto %s: %g S/s, no FIR needed", self.uri, self.fs)
            return
        refused = []                  # why each way failed, for the note or the error
        lib = host.find_library("ad9361")
        if lib:
            try:
                ad = ctypes.CDLL(lib)
                ad.ad9361_set_bb_rate.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
                ad.ad9361_set_bb_rate.restype = ctypes.c_int
                ret = ad.ad9361_set_bb_rate(ctypes.cast(self.phy._device, ctypes.c_void_p), int(self.fs))
                if ret == 0:
                    self.fir = f"libad9361's ({lib})"
                    log.info("Pluto %s: %g S/s, FIR accepted (libad9361, %s)", self.uri, self.fs, lib)
                    return
                refused.append(f"libad9361's ad9361_set_bb_rate returned {ret}")
            except (OSError, AttributeError) as e:
                refused.append(f"libad9361 unusable ({e})")
        else:
            refused.append("libad9361 is not installed")
        try:
            self._load_own_fir()
            self.notes.extend(f"{r}; loaded our own FIR" for r in refused if lib)
            self.fir = "our own"
            log.info("Pluto %s: %g S/s, our own FIR accepted (%s)", self.uri, self.fs, "; ".join(refused))
            return
        except (KeyError, OSError, DeviceError) as e:
            refused.append(f"our own FIR was refused ({e})")
        # Both refused. On the Tezuka nano that is the firmware, not a
        # missing package: even `cat file > filter_fir_config` on the radio
        # itself is EINVAL. Without the FIR the AD9361 runs fine at
        # >= 2.083 MS/s (2.4 MS/s measured there: 2.37 MS/s delivered over
        # USB, flat noise), so take the smallest multiple of fs above that.
        m = -(-NO_FIR_MIN // int(self.fs))
        hw = int(self.fs) * m
        self._try(self.phy, "in_out_voltage_filter_fir_en", 0)
        try:
            self.rx_ch.attrs["sampling_frequency"].value = str(hw)
        except (KeyError, OSError) as e:
            hint = " - install libad9361-0" if not lib else ""
            raise DeviceError(f"Pluto: could not set {self.fs:.0f} S/s: {'; '.join(refused)}; "
                              f"and {hw} S/s without the FIR failed too ({e}){hint}") from e
        from ..dsp.multirate import Decimator
        self.m = m
        self.dec = Decimator(m)
        self.fir = f"refused; hardware at {hw} S/s, decimated by {m} in software"
        log.warning("Pluto %s: FIR refused (%s); running at %d S/s and decimating by %d", self.uri,
                    "; ".join(refused), hw, m)
        self.notes.append(f"This firmware will not load the AD9361's FIR ({'; '.join(refused)}), so the radio "
                          f"runs at {hw / 1e6:g} MS/s and the program converts to {self.fs / 1e6:g} MS/s "
                          f"(costs some CPU, nothing else)")

    def _load_own_fir(self):
        taps = _fir_x4()
        text = "RX 3 GAIN -6 DEC 4\nTX 3 GAIN 0 INT 4\n" + "".join(f"{t},{t}\n" for t in taps)
        # Drop to a rate the FIR-less path supports before swapping filters.
        self._try(self.rx_ch, "sampling_frequency", 3_000_000)
        self.phy.attrs["filter_fir_config"].value = text
        ok = False
        for name in ("in_out_voltage_filter_fir_en",):
            if name in self.phy.attrs:
                self.phy.attrs[name].value = "1"
                ok = True
        if not ok:
            ch = self.phy.find_channel("out", False) or self.phy.find_channel("out", True)
            if ch is not None and "voltage_filter_fir_en" in ch.attrs:
                ch.attrs["voltage_filter_fir_en"].value = "1"
                ok = True
        if not ok:
            raise DeviceError("no FIR enable attribute found")
        self.rx_ch.attrs["sampling_frequency"].value = str(int(self.fs))

    # -- receive -------------------------------------------------------------
    def set_rx_if(self, hz: float) -> None:
        self.rx_if = float(hz)
        try:
            self._attr(self.rx_lo_ch, "frequency", int(round(hz)))
        except DeviceError as e:
            if hz < 325e6 or hz > 3.8e9:
                raise DeviceError(f"This Pluto will not tune {hz / 1e6:.3f} MHz: its firmware runs it as an AD9363 "
                                  f"(325 MHz-3.8 GHz). The AD9364 setting reaches 70 MHz-6 GHz; ADI's "
                                  f"'customizing' page gives the two fw_setenv commands. The program never "
                                  f"changes firmware itself.") from e
            raise

    def tx_full_w(self, hz: float) -> float:
        # About +6.5 dBm (kittenlabs, a single source: docs/qo100-research.md
        # section 4), less at the band extremes (unmeasured). An estimate.
        return 0.0045

    def read(self, n: int) -> np.ndarray:
        while len(self.left) < n:
            try:
                self.rxbuf.refill()
                raw = self.rxbuf.read()
            except OSError as e:
                raise DeviceError(f"Pluto receive failed: {e}") from e
            iq = np.frombuffer(raw, np.int16).astype(np.float32).view(np.complex64) / 2048.0
            if self.dec is not None:
                iq = self.dec(iq)
            self.left = np.concatenate([self.left, iq])
        out, self.left = self.left[:n], self.left[n:]
        return out

    # -- transmit ------------------------------------------------------------
    def set_tx_freq(self, hz: float) -> None:
        self.tx_lo = float(hz)
        self._attr(self.tx_lo_ch, "frequency", int(round(hz)))

    def set_tx_gain(self, db: float) -> None:
        db = max(TX_ATTEN_MAX, min(0.0, round(float(db) * 4) / 4))
        self._attr(self.tx_ch, "hardwaregain", db)

    def tx_start(self) -> None:
        if self.tx_on:
            return
        self._attr(self.tx_ch, "hardwaregain", TX_ATTEN_MAX)
        self._try(self.tx_lo_ch, "powerdown", 0)
        for i in (0, 1):
            self.txdev.find_channel(f"voltage{i}", True).enabled = True
        try:
            self.txdev.set_kernel_buffers_count(4)
        except (AttributeError, OSError):
            pass
        self.txbuf = self.iio.Buffer(self.txdev, self.tx_block * self.m, False)
        self.tx_pending = np.zeros(0, np.complex64)
        # When (monotonic) the last sample pushed so far will have left the
        # DAC, and the last of them that was written rather than padding.
        # See tx_queued().
        self._air_end = self._real_end = 0.0
        if self.m > 1:
            # Fresh each over: its history is the previous over's last
            # samples, which tx_stop's zeros have long since followed.
            from ..dsp.multirate import Interpolator
            self.interp = Interpolator(self.m)
        self.tx_on = True

    def write(self, iq: np.ndarray) -> None:
        if not self.tx_on:
            raise DeviceError("Transmit is not started")
        self.tx_pending = np.concatenate([self.tx_pending, np.asarray(iq, np.complex64)])
        while len(self.tx_pending) >= self.tx_block:
            blk, self.tx_pending = self.tx_pending[:self.tx_block], self.tx_pending[self.tx_block:]
            self._push(blk)
            self._real_end = self._air_end

    def _push(self, blk: np.ndarray) -> None:
        """One tx_block of IQ at fs into the kernel's ring of buffers."""
        if self.m > 1:
            blk = self.interp(blk)          # m x tx_block at the hardware rate, unity gain
        # 12-bit DAC, MSB-aligned in int16: full scale is +-2047 << 4.
        s = np.empty(2 * len(blk), np.int16)
        s[0::2] = np.clip(np.round(blk.real * 32767), -32767, 32767)
        s[1::2] = np.clip(np.round(blk.imag * 32767), -32767, 32767)
        try:
            self.txbuf.write(bytearray(s.tobytes()))
            self.txbuf.push()
        except OSError as e:
            raise DeviceError(f"Pluto transmit failed: {e}") from e
        # push() returns once the ring has room: at once for the first four
        # buffers, then each time the DAC finishes one. Either way this
        # block starts after everything already pushed has gone, or now if
        # the DAC had run dry, and takes a block's time at the DAC's clock.
        self._air_end = max(self._air_end, time.monotonic()) + self.tx_block / self.fs

    def tx_finish(self) -> None:
        # The last part-block would otherwise wait in tx_pending for samples
        # that are never coming, and tx_stop would drop it with the rest:
        # up to 75 ms. Padded with silence to a whole buffer, which also
        # carries the interpolator's last few samples out.
        if not self.tx_on or not len(self.tx_pending):
            return
        k = self.tx_block - len(self.tx_pending)
        blk = np.concatenate([self.tx_pending, np.zeros(k, np.complex64)])
        self.tx_pending = np.zeros(0, np.complex64)
        self._push(blk)
        self._real_end = self._air_end - k / self.fs

    def tx_queued(self) -> float:
        # libiio says nothing about how full the kernel's ring is, so it is
        # timed instead (see _push): the ring is four buffers of tx_block
        # (75 ms) each - set_kernel_buffers_count(4) in tx_start - so up to
        # 300 ms is in flight once the ring is full, plus the part-block
        # waiting here. The host's clock against the radio's crystal is a
        # few ppm, microseconds over a ring this short.
        if not self.tx_on:
            return 0.0
        return len(self.tx_pending) / self.fs + max(0.0, self._real_end - time.monotonic())

    def tx_stop(self) -> None:
        if not self.tx_on:
            return
        self.tx_on = False
        try:
            self._attr(self.tx_ch, "hardwaregain", TX_ATTEN_MAX)
            if self.txbuf is not None:
                z = bytearray(4 * self.tx_block * self.m)
                self.txbuf.write(z)
                self.txbuf.push()
        except (OSError, DeviceError):
            pass
        self.txbuf = None
        self._try(self.tx_lo_ch, "powerdown", 1)

    def tx_latency(self) -> float:
        # Four kernel buffers of one block each, plus what is waiting here.
        # (A buffer is m x tx_block at m x fs: the same 75 ms either way.)
        lat = (4 * self.tx_block + len(getattr(self, "tx_pending", ()))) / self.fs
        if self.m > 1:
            # The interpolator delays what goes out and the decimator what
            # comes back, (taps - 1) / 2 each at the hardware rate (one
            # filter design serves both): 15 us each at 2.4 MS/s from
            # 1.2 MS/s, 30 us from 600 kS/s. TxMonitor finds the delay in
            # 10 ms steps within a 0.5 s window, so this is far below what it
            # can see; it is added because it is exact and costs nothing.
            lat += 2 * self.dec.delay / (self.fs * self.m)
        return lat

    def close(self) -> None:
        try:
            self.tx_stop()
        finally:
            self.rxbuf = None
            self.txbuf = None
            self.ctx = None

    def context_attrs(self) -> dict:
        """The IIO context attributes of the radio this device has open
        (fw_version, hw_model, hw_serial, ad9361-phy,model...), read from
        that context: {} when it is not open. Never opens one."""
        ctx = self.ctx
        if ctx is None:
            return {}
        try:
            return {str(k): str(v) for k, v in dict(getattr(ctx, "attrs", {}) or {}).items()}
        except (OSError, AttributeError, TypeError):
            return {}

    def status(self) -> dict:
        st = {"kind": "pluto", "uri": self.uri, "model": self.model, "fs": self.fs, "rxLo": self.rx_if,
              "txLo": self.tx_lo, "tx": self.tx_on, "notes": list(self.notes), "identity": self.identity,
              "fir": self.fir, "hwRate": self.fs * self.m, "fwVersion": self.fw_version, "serial": self.serial}
        try:
            st["xoCorrection"] = self.phy.attrs["xo_correction"].value
        except (AttributeError, KeyError, OSError):
            pass
        try:
            st["rssi"] = self.rx_ch.attrs["rssi"].value
        except (AttributeError, KeyError, OSError):
            pass
        return st
