#!/usr/bin/env python3
"""Write ohsdigi's JS8 tables from JS8Call 2.2.0's own source.

    gen_js8_tables.py <js8call source dir>

<js8call source dir> is the unpacked js8call_2.2.0+ds.orig.tar.xz (Debian's
source package, the same code JS8Call's upstream tag v2.2.0 holds). Two
files are written next to this script's crate:

- src/js8/ldpc_tables.rs: the (174,87) LDPC code JS8 inherited from FT8 as
  it was before WSJT-X 2.0 (lib/ft8/ldpc_174_87_params.f90 for the
  generator and column order, lib/ft8/bpdecode174.f90 for the parity-check
  lists), parsed from the DATA statements so no index is typed by hand.
- src/js8/jsc.bin.gz: JS8Call's word-compression dictionary (jsc_map.cpp:
  262 144 words, ~6 MB of C++), as a compact binary the crate reads at
  first use (src/js8/jsc.rs documents the layout; its lookup order,
  jsc_list.cpp, is rebuilt there and checked against JS8Call's below). The
  `size` field of each entry is kept as stored rather than recomputed from
  the string: two entries disagree with their own strings ("@ALLCALL"
  says 7, "ROSIDS" 1), and JS8Call's compressor advances by that field,
  so recomputing it would change what we send.
"""
import gzip
import os
import re
import struct
import sys

SRC = sys.argv[1].rstrip("/")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "src", "js8")


def fortran_block(text, name):
    m = re.search(r"data " + name + r"/(.*?)/", text, re.S)
    return m.group(1)


params = open(SRC + "/lib/ft8/ldpc_174_87_params.f90").read()
bp = open(SRC + "/lib/ft8/bpdecode174.f90").read()
gen = re.findall(r'"([0-9a-f]{22})"', fortran_block(params, "g"))
colorder = [int(x) for x in re.findall(r"\d+", fortran_block(params, "colorder"))]
Mn = [int(x) for x in re.findall(r"\d+", fortran_block(bp, "Mn"))]
Nm = [int(x) for x in re.findall(r"\d+", fortran_block(bp, "Nm"))]
nrw = [int(x) for x in re.findall(r"\d+", fortran_block(bp, "nrw"))]
assert len(gen) == 87 and len(colorder) == 174
assert len(Mn) == 174 * 3 and len(Nm) == 87 * 7 and len(nrw) == 87
# Each row is 87 bits in 22 hex digits; the 88th is padding. osd174.f90
# writes that bit into the next row's storage when it is set (no bounds
# check), so the port relies on it being clear - checked here.
assert all(int(g[-1], 16) & 1 == 0 for g in gen)
assert sorted(colorder) == list(range(174))

o = [
    "// Generated mechanically from JS8Call 2.2.0 (GPL-3; Jordan Sherer KN4CRD,",
    "// after WSJT-X 1.9 by K1JT, K9AN et al.) by harness/gen_js8_tables.py:",
    "// lib/ft8/ldpc_174_87_params.f90 (GENERATOR, COLORDER) and",
    "// lib/ft8/bpdecode174.f90 (MN, NM, NRW). Nothing here was typed by hand.",
    "// Indices in MN and NM are 1-based as in the Fortran (0 pads NM's rows).",
    "",
    "/// The 87 parity rows of the generator, each 87 message bits as written",
    "/// in WSJT-X 1.9's hex strings (22 digits, most significant first; the",
    "/// 88th bit is always clear).",
    "pub const GENERATOR: [&str; 87] = [",
]
o += ['    "%s",' % g for g in gen]
o += ["];", "", "/// Codeword column order: encode174 puts bit i (parity then message) at",
      "/// position COLORDER[i].", "pub const COLORDER: [u8; 174] = ["]
for i in range(0, 174, 20):
    o.append("    " + ", ".join(str(x) for x in colorder[i:i + 20]) + ",")
o += ["];", "", "/// For each of the 174 bits, the three checks it takes part in (1-based).",
      "pub const MN: [[u8; 3]; 174] = ["]
for i in range(174):
    o.append("    [%d, %d, %d]," % tuple(Mn[3 * i:3 * i + 3]))
o += ["];", "", "/// For each of the 87 checks, the bits it covers (1-based; 0 pads).",
      "pub const NM: [[u8; 7]; 87] = ["]
for i in range(87):
    o.append("    [" + ", ".join(str(x) for x in Nm[7 * i:7 * i + 7]) + "],")
o += ["];", "", "/// Bits per check: 5, 6 or 7.",
      "pub const NRW: [u8; 87] = [" + ", ".join(map(str, nrw)) + "];", ""]
open(os.path.join(OUT, "ldpc_tables.rs"), "w").write("\n".join(o))


def tuples(path, name):
    src = open(path, "rb").read()
    body = src[src.index(b"JSC::" + name.encode()):]
    body = body[body.index(b"{") + 1:body.index(b"};")]
    out = []
    for m in re.finditer(rb'\{"((?:[^"\\]|\\.)*)"\s*(?:/\*.*?\*/)?\s*,\s*(\d+)\s*,\s*(\d+)\}', body):
        s = m.group(1)
        s = re.sub(rb"\\x([0-9a-fA-F]{2})", lambda mm: bytes([int(mm.group(1), 16)]), s)
        s = s.replace(b"\\n", b"\n").replace(b"\\t", b"\t").replace(b'\\"', b'"').replace(b"\\\\", b"\\")
        out.append((s, int(m.group(2)), int(m.group(3))))
    return out


mp = tuples(SRC + "/jsc_map.cpp", "map")
lst = tuples(SRC + "/jsc_list.cpp", "list")
pre = tuples(SRC + "/jsc_list.cpp", "prefix")
assert len(mp) == 262144 and len(lst) == 262144 and len(pre) == 103
assert all(mp[i][2] == i for i in range(len(mp)))

# JSC::list (the compressor's lookup order) is not stored: src/js8/jsc.rs
# rebuilds it from the map, which halves the file. That is only sound if
# the rebuild matches what jsc_list.cpp holds, so it is checked here: per
# first character (JSC::prefix), the entries in descending byte order,
# "@ALLCALL" filed under "ALLCALL"; a character with one entry returns it
# unread. Entries jsc_list.cpp has dropped into another character's range
# (Latin-1 letters, \n, \x1a inside B, F and J) never match a word of that
# character and so change nothing. The one size the list disagrees with
# the map on is ROSIDS (6 there, 1 here), which jsc.rs applies.
def key(i):
    return b"ALLCALL" if mp[i][0] == b"@ALLCALL" else mp[i][0]
groups = {}
for i in range(len(mp)):
    groups.setdefault(key(i)[:1], []).append(i)
assert set(groups) == {p[0] for p in pre}
for ch, cnt, ix in pre:
    if cnt == 1:
        assert len(groups[ch]) == 1 and lst[ix][2] == groups[ch][0]
        continue
    real = [x[2] for x in lst[ix:ix + cnt] if key(x[2])[:1] == ch]
    assert real == sorted(groups[ch], key=key, reverse=True), ch
sizes = [(x[2], x[1]) for x in lst if x[1] != mp[x[2]][1]]
assert sizes == [(262143, 6)] and mp[262143][0] == b"ROSIDS", sizes

blob = bytearray(b"JSC2")
for s, size, _ in mp:
    blob += struct.pack("<BB", size, len(s)) + s
open(os.path.join(OUT, "jsc.bin.gz"), "wb").write(gzip.compress(bytes(blob), 9, mtime=0))
print("ldpc_tables.rs, jsc.bin.gz (%d bytes raw)" % len(blob))
