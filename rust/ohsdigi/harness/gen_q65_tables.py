#!/usr/bin/env python3
"""Write src/q65/tables.rs from WSJT-X 2.7.0's own Q65 code tables.

    gen_q65_tables.py <wsjtx lib dir>

<wsjtx lib dir> is the lib/ folder harness/build.sh extracts from
/srv/source-site/files/wsjtx-2.7.0.tgz. The tables are parsed out of
lib/qra/q65/qra15_65_64_irr_e23.c (the (15,65) Q-ary RA code over GF(64)
that Q65 uses) and lib/qra/q65/fadenlorentz.c (the Lorentzian fading
weights; WSJT-X's Q65 always uses that model), so nothing is typed by hand.
"""
import os
import re
import sys

L = sys.argv[1].rstrip("/") + "/qra/q65/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "q65", "tables.rs")
code = open(L + "qra15_65_64_irr_e23.c").read()
code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)        # SO, LOGWO, repfact are commented out
fade = open(L + "fadenlorentz.c").read()


def ints(name, src=code):
    m = re.search(r"static const int " + name + r"\[[^\]]*\]\s*=\s*\{(.*?)\};", src, re.S)
    return [int(x) for x in re.findall(r"-?\d+", m.group(1))]


def floats(name, src):
    m = re.search(r"static const float " + name + r"\[[^\]]*\]\s*=\s*\{(.*?)\};", src, re.S)
    return re.findall(r"[-+0-9.eE]+(?=f)", m.group(1))


tabs = [("ACC_INPUT_IDX", "qra_acc_input_idx", 51), ("ACC_INPUT_WLOG", "qra_acc_input_wlog", 51),
        ("GF_LOG", "qra_log", 64), ("GF_EXP", "qra_exp", 63), ("MSGW", "qra_msgw", 216),
        ("VDEG", "qra_vdeg", 65), ("CDEG", "qra_cdeg", 116), ("V2CMIDX", "qra_v2cmidx", 65 * 5),
        ("C2VMIDX", "qra_c2vmidx", 116 * 3), ("PMAT", "qra_pmat", 64 * 64)]
o = ["// Generated mechanically from WSJT-X 2.7.0 lib/qra/q65/qra15_65_64_irr_e23.c and",
     "// lib/qra/q65/fadenlorentz.c (GPL-3; Nico Palermo IV3NWV, Microtelecom Srl) by",
     "// harness/gen_q65_tables.py, which parses their array initialisers: nothing here",
     "// was typed by hand.", ""]
for rust, c, n in tabs:
    v = ints(c)
    # qra_pmat is declared M*M but initialised for log weights 0..62 only
    # (63 rows); C zero-fills the rest, and so does this.
    assert len(v) == n or (c == "qra_pmat" and len(v) == 63 * 64), (c, len(v))
    v += [0] * (n - len(v))
    o.append(f"pub const {rust}: [i16; {n}] = [")
    for i in range(0, n, 16):
        o.append("    " + ", ".join(map(str, v[i:i + 16])) + ",")
    o.append("];")
lens = ints("glen_tab_lorentz", fade)
assert len(lens) == 64
o.append("/// Taps (the leftmost (L+1)/2 of a symmetric L-tap weighting) per B90 index.")
o.append("pub const LORENTZ_LEN: [usize; 64] = [" + ", ".join(map(str, lens)) + "];")
names = re.search(r"gptr_tab_lorentz\[64\]\s*=\s*\{(.*?)\};", fade, re.S).group(1)
names = re.findall(r"glorentz\d+", names)
assert len(names) == 64
o.append("pub const LORENTZ: [&[f32]; 64] = [")
for i, nm in enumerate(names):
    v = floats(nm, fade)
    assert len(v) == lens[i], (nm, len(v), lens[i])
    o.append("    &[" + ", ".join(x if "." in x or "e" in x.lower() else x + ".0" for x in v) + "],")
o.append("];")
open(OUT, "w").write("\n".join(o) + "\n")
print(OUT)
