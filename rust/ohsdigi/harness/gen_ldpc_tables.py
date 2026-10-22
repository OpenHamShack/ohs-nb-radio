#!/usr/bin/env python3
"""Write src/decode/ldpc_tables.rs from WSJT-X's own parity-check tables.

    gen_ldpc_tables.py <wsjtx lib dir> > ../src/decode/ldpc_tables.rs

<wsjtx lib dir> is the lib/ folder build.sh extracts. The tables are parsed
out of lib/ft8/ldpc_174_91_c_parity.f90's DATA statements so that no index
is typed by hand.
"""
import re
import sys

L = sys.argv[1].rstrip("/") + "/ft8/"
par = open(L + "ldpc_174_91_c_parity.f90").read()


def block(name):
    m = re.search(r"data " + name + r"/(.*?)/", par, re.S)
    return [int(x) for x in re.findall(r"\d+", m.group(1))]


Mn = block("Mn")
Nm = block("Nm")
nrw = block("nrw")
assert len(Mn) == 174 * 3 and len(Nm) == 83 * 7 and len(nrw) == 83
o = [
    "// Generated mechanically from WSJT-X 2.7.0 lib/ft8/ldpc_174_91_c_parity.f90",
    "// (GPL-3; K1JT, K9AN et al.) by harness/gen_ldpc_tables.py, which parses its",
    "// DATA statements, so nothing here was typed by hand. The decoder's half of",
    "// the code; the generator is crate::ldpc::ldpc174_91::GENERATOR. Indices are kept",
    "// 1-based exactly as in the Fortran (0 = unused slot in NM), and converted at",
    "// the point of use.",
    "",
    "/// For each of the 174 bits, the three parity checks it takes part in (1-based).",
    "pub const MN: [[u8; 3]; 174] = [",
]
for i in range(174):
    o.append("    [%d, %d, %d]," % tuple(Mn[3 * i:3 * i + 3]))
o.append("];")
o.append("/// For each of the 83 checks, the bits it covers (1-based; 0 pads the rows of six).")
o.append("pub const NM: [[u8; 7]; 83] = [")
for i in range(83):
    o.append("    [" + ", ".join(str(x) for x in Nm[7 * i:7 * i + 7]) + "],")
o.append("];")
o.append("/// Bits per check: 6 or 7.")
o.append("pub const NRW: [u8; 83] = [" + ", ".join(map(str, nrw)) + "];")
sys.stdout.write("\n".join(o) + "\n")
