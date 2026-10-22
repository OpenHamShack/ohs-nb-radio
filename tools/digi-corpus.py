#!/usr/bin/env python3
"""Make the FT8/FT4 encoder corpus: what WSJT-X's own ft8code and ft4code
say about several thousand messages, as test data for ohsdigi.

    tools/digi-corpus.py [--out FILE] [--count N] [--seed S] [--jobs J]

The corpus is the reference rust/ohsdigi is held to, bit for bit: for each
message, the type (i3.n3), the text "as it will be received", the 77
payload bits and the channel symbols, for FT8 and FT4, or the fact that
WSJT-X refuses it ("*** bad message ***") or stops with a run-time error.
It is written to rust/ohsdigi/testdata/ and committed, so the tests that read
it (tests/corpus.rs, tests/test_ohsdigi.py) need no WSJT-X installed; this
script is how it was made and how to remake it, and it needs ft8code and
ft4code from WSJT-X 2.7.0 (Debian's wsjtx 2.7.0+repack-1 was used).

The messages are WSJT-X's own examples (ft8code -T, ft4code -t), then
generated ones covering every message type and its edge cases, then
random combinations of awkward tokens. Generation is seeded, so the same
seed and count make the same corpus. --count sets how many generated
messages there are on top of the fixed ones; a large count (tens of
thousands) written to a scratch file is a differential fuzz run: point
OHSDIGI_EXTRA_CORPUS at it and run `cargo test --test corpus`.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "rust" / "ohsdigi" / "testdata" / "wsjtx-2.7.0-ft8-ft4.tsv.gz"
FIELDS = ["message", "ft8_status", "ft8_type", "ft8_sent", "ft8_bits", "ft8_tones",
          "ft4_status", "ft4_type", "ft4_sent", "ft4_bits", "ft4_tones"]

# --------------------------------------------------------------- running WSJT-X


def _run(tool: str, msg: str) -> tuple[str, str, str, str, str]:
    """(status, i3.n3, sent, bits, tones) from one run of ft8code/ft4code.
    status is ok, bad ("*** bad message ***": WSJT-X sends all-zero or
    undefined tones) or crash (a Fortran run-time error, no output)."""
    r = subprocess.run([tool, msg], capture_output=True)
    out = r.stdout.decode("latin-1").splitlines()
    if r.returncode != 0 or len(out) < 3 or not any("Channel symbols" in l for l in out):
        return ("crash", "", "", "", "")
    head = out[2]
    sent = head[42:79].rstrip()
    i3 = head[83]
    n3 = head[85].strip()
    typ = f"{i3}.{n3}" if n3 else f"{i3}."
    if sent == "*** bad message ***":
        return ("bad", typ, "", "", "")
    marker = "Source-encoded message before scrambling" if tool.endswith("ft4code") else "Source-encoded message, 77 bits"
    bi = next(i for i, l in enumerate(out) if l.startswith(marker))
    bits = out[bi + 1].strip()
    words = out[-1].split()
    if tool.endswith("ft4code"):
        words = words[1:-1]          # the two ramp-symbol placeholders ft4code prints as 0
    tones = "".join(words)
    assert len(bits) == 77 and set(bits) <= {"0", "1"}, (msg, bits)
    assert len(tones) == (103 if tool.endswith("ft4code") else 79), (msg, tones)
    return ("ok", typ, sent, bits, tones)


def run_both(msg: str) -> list[str]:
    return [msg, *_run("ft8code", msg), *_run("ft4code", msg)]

# --------------------------------------------------------------- messages

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
TEXT_CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?"

SECTIONS = ("AB AK AL AR AZ BC CO CT DE EB EMA ENY EPA EWA GA GH IA ID IL IN KS KY LA LAX NS MB MDC ME MI "
            "MN MO MS MT NC ND NE NFL NH NL NLI NM NNJ NNY TER NTX NV OH OK ONE ONN ONS OR ORG PAC PR QC "
            "RI SB SC SCV SD SDG SF SFL SJV SK SNJ STX SV TN UT VA VI VT WCF WI WMA WNY WPA WTX WV WWA WY "
            "DX PE NB").split()
STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
          "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY NB NS QC ON MB SK AB BC NWT NF LB NU "
          "YT PEI DC DR FR GD GR OV ZH ZL X01 X42 X99").split()

# WSJT-X's own examples beyond ft8code -T / ft4code -t (lib/77bit/*.txt),
# and cases found while porting that are worth pinning by name.
FIXED = [
    "CQ K1ABC FN42", "K1ABC W9XYZ EN37", "W9XYZ K1ABC -11", "K1ABC W9XYZ R-09", "W9XYZ K1ABC RRR",
    "K1ABC W9XYZ 73", "K1ABC W9XYZ RR73", "CQ 000 K1ABC FN42", "CQ 999 K1ABC FN42", "CQ A K1ABC FN42",
    "CQ ZZZZ K1ABC FN42", "CQ DX K1ABC FN42", "QRZ K1ABC FN42", "DE K1ABC FN42", "CQ K1ABC/R FN42",
    "CQ PJ4/K1ABC", "CQ K1ABC/QRP", "<PJ4/K1ABC> W9XYZ", "W9XYZ <PJ4/K1ABC> -11", "<PJ4/K1ABC> W9XYZ R-09",
    "W9XYZ PJ4/K1ABC", "W9XYZ PJ4/K1ABC RR73", "PJ4/K1ABC W9XYZ", "K1ABC W9XYZ +999", "K1ABC W9XYZ -999",
    "K1ABC W9XYZ R +05", "K1ABC W9XYZ +5,", "K1ABC W9XYZ +5;", "K1ABC W9XYZ +5/", "K1ABC W9XYZ +2*3",
    "K1ABC W9XYZ +5.", "K1ABC W9XYZ -", "K1ABC W9XYZ +", "CQ_1/23 K1ABC", "CQ 12. K1ABC", "CQ 1.23 K1ABC",
    "CQ /123 K1ABC", "CQ 1/2 K1ABC", "K1ABC W9XYZ 123 4567", "K1ABC W9XYZ 579 4567", "K1ABC W9XYZ 579 0000",
    "K1ABC W9XYZ 579 MA", "K1ABC W9XYZ 579A MA", "K1ABC W9XYZ X 579 MA", "K1ABC W9XYZ , 579 MA",
    "K1ABC W9XYZ 579 9999", "K1ABC W9XYZ 579 8100", "K1ABC W9XYZ 21 EMA", "K1ABC W9XYZ 2Z EMA",
    "K1ABC W9XYZ 33A EMA", "K1ABC W9XYZ 0A EMA", "K1ABC W9XYZ 32F EMA", "K1ABC W9XYZ 1H EMA",
    "<PA3XYZ> <G4ABC/P> R 590003 IO91NP", "<PA3XYZ> <G4ABC> 520001 AA00AA", "<PA3XYZ> <G4ABC> 594095 RR99XX",
    "<PA3XYZ> <G4ABC> 594096 RR99XX", "<PA3XYZ> <G4ABC> 590003 IO91", "K1ABC RR73; W9XYZ <KH1/KH7Z> -08",
    "K1ABC RR73; W9XYZ <KH1/KH7Z> -99", "K1ABC RR73; W9XYZ <KH1/KH7Z> +40", "K1ABC RR73; W9XYZ <KH1/KH7Z> -40",
    "K1ABC FN42 37", "K1ABC FN42 15", "K1ABC FN42 5", "PJ4/K1ABC 37", "K1ABC/7 37", "K1ABC/AB 37",
    "K1ABC/A12 37", "ABCD/E1GHI 37", "123456789ABCDEF012", "123456789ABCDEF0123", "800000", "7FFFFF",
    "7FFFFFFFFFFFFFFFFF", "800000000000000000", "0", "", " ", "  CQ K1ABC FN42", "$DX K1ABC", " $DX K1ABC",
    "cq k1abc fn42", "TNX BOB 73 GL", "TNX BOB 73 GL 72", "HI", "?", "<>", "<...>", "<K1ABC>", "<K1ABC> <W9XYZ>",
    "CQ <K1ABC>", "CQ <PJ4/K1ABC>", "CQ K1ABC R FN42", "CQ K1ABC RRR", "TU; W9XYZ K1ABC R 579 MA",
    "TU; W9XYZ K1ABC R 559 0013", "W9XYZ K1ABC 529 X99", "K1ABC/R W9XYZ/R R FN42", "PA3XYZ/P GM4ABC/P R JO22",
    "QU1RK W9XYZ", "QA1ABC W9XYZ", "3DA0XYZ K1ABC", "3XA1BC K1ABC", "K1ABC W9XYZ FN42AB", "K1ABC W9XYZ RR73;",
    "K1ABC W9XYZ R RRR", "K1ABC W9XYZ +50", "K1ABC W9XYZ +51", "K1ABC W9XYZ -50", "K1ABC W9XYZ -51",
    "K1ABC W9XYZ -30", "K1ABC W9XYZ -31", "K1ABC W9XYZ R+50", "A1ABC B2DEF", "1A1ABC W9XYZ", "-T X", "-t X",
    "K1ABCDEFGHIJKLMNOP W9XYZ", "CQ K1ABCDEFGHIJ", "CQ ABCDEFGHIJKLM", "<KA1ABCDEFGHIJK> W9XYZ",
    "THIS IS A VERY LONG FREE TEXT MESSAGE THAT IS CUT", "A B C D E F G H I J K L M N O P Q R S",
]


def call_std(r: random.Random) -> str:
    """A standard callsign in one of the shapes pack28 accepts (and a few
    it does not, as an operator might type them)."""
    shape = r.choice(["LDL", "LDLL", "LDLLL", "LLDL", "LLDLL", "LLDLLL", "DLDLL", "DLDLLL", "LDDL", "LLDDLL"])
    out = []
    for c in shape:
        out.append(r.choice(LETTERS) if c == "L" else r.choice(DIGITS))
    return "".join(out)


def call_any(r: random.Random) -> str:
    k = r.random()
    if k < 0.6:
        return call_std(r)
    if k < 0.75:
        return call_std(r) + r.choice(["/P", "/R", "/M", "/QRP", "/7", "/MM", "/AM", "/A1", "/12"])
    if k < 0.9:
        pfx = r.choice(["PJ4", "VP2E", "3D2", "W1", "G", "DL", "KH6", "VK9X", "ZL7", "4U1", "TX5"])
        return pfx + "/" + call_std(r)
    return r.choice(["YW18FIFA", "TO4X", "E7DX", "8J1ITU", "II2SAT", "TM100A", "QU1RK", "AB", "A1", "1A2B"])


def grid4(r):
    return r.choice(LETTERS[:18]) + r.choice(LETTERS[:18]) + r.choice(DIGITS) + r.choice(DIGITS)


def grid6(r):
    return grid4(r) + r.choice(LETTERS[:24]) + r.choice(LETTERS[:24])


def report(r):
    v = r.choice(list(range(-35, 55)) + [-60, -51, -50, -31, -30, 49, 50, 51, 99, 0])
    return f"{v:+03d}" if r.random() < 0.8 else str(v)


def bracket(c):
    return f"<{c}>"


def generated(r: random.Random) -> str:
    kind = r.randrange(16)
    a, b = call_any(r), call_any(r)
    if kind == 0:
        return f"CQ {a} {grid4(r)}" if r.random() < 0.7 else f"CQ {a}"
    if kind == 1:
        cq = r.choice(["DX", "TEST", "FD", "NA", "POTA", "SOTA", str(r.randrange(1000)).zfill(3), "WW", "EU", "A",
                       "ABCDE", "12", "1234", "X1"])
        return f"CQ {cq} {a} {grid4(r)}"
    if kind == 2:
        return f"{a} {b} {r.choice([grid4(r), report(r), 'R' + report(r), 'RRR', 'RR73', '73', 'R ' + grid4(r)])}"
    if kind == 3:
        return f"{a} {b}"
    if kind == 4:
        x, y = (bracket(a), b) if r.random() < 0.5 else (a, bracket(b))
        return f"{x} {y} {r.choice(['', 'RRR', 'RR73', '73', report(r), 'R' + report(r), grid4(r)])}".strip()
    if kind == 5:
        r_ = r.choice(["", "R "])
        n = r.choice(list(range(1, 33)) + [0, 33, 99])
        cls = r.choice("ABCDEFGHIZ1")
        return f"{a} {b} {r_}{n}{cls} {r.choice(SECTIONS + ['XX', 'EMAX', 'E'])}"
    if kind == 6:
        tu = r.choice(["", "TU; "])
        r_ = r.choice(["", "R "])
        rst = r.choice(["599", "579", "559", "529", "519", "599", "589", "5NN", "509", "499"])
        ex = r.choice(STATES + [f"{r.randrange(1, 8000):04d}", str(r.randrange(10000)), "0000", "MA1"])
        return f"{tu}{a} {b} {r_}{rst} {ex}"
    if kind == 7:
        r_ = r.choice(["", "R "])
        nx = r.choice([r.randrange(520001, 594096), r.randrange(500000, 600000), 590003])
        return f"{bracket(a)} {bracket(b)} {r_}{nx} {grid6(r) if r.random() < 0.9 else grid4(r)}"
    if kind == 8:
        return f"{a} RR73; {b} {bracket(call_any(r))} {report(r)}"
    if kind == 9:
        n = r.randrange(1, 20)
        s = "".join(r.choice("0123456789ABCDEFabcdef") for _ in range(n))
        return s if r.random() < 0.9 else s + r.choice(["G", " X", "-", "+1"])
    if kind == 10:
        n = r.randrange(1, 20)
        return "".join(r.choice(TEXT_CHARS + "abcxyz#*,;:<>") for _ in range(n))
    if kind == 11:
        return f"{a} {grid4(r)} {r.randrange(0, 70)}" if r.random() < 0.5 else f"{a} {r.randrange(0, 70)}"
    if kind == 12:
        return f"CQ {a}" if "/" in a else f"CQ {a}/{r.choice(['P', 'QRP', 'MM', 'A'])}"
    if kind == 13:
        # spacing, case and length
        words = [a.lower() if r.random() < 0.3 else a, b, grid4(r)]
        sep = lambda: " " * r.choice([1, 1, 2, 3])
        return r.choice(["", " ", "  "]) + sep().join(words) + r.choice(["", " ", "   "])
    return fuzz(r)


TOKENS = ["CQ", "QRZ", "DE", "TU;", "RR73;", "RRR", "RR73", "73", "R", "+05", "-12", "R-07", "R+03", "+5,",
          "-5/", "+", "-", "R-", "R+", "599", "579A", "MA", "EMA", "DX", "1A", "16A", "33B", "<", ">", "<>",
          "<...>", "<K1ABC", "K1ABC>", "$DX", "CQ_DX", "CQ_123", "FN42", "IO91NP", "AA00", "RR99", "SS00",
          "0013", "8000", "590003", "520000", "?", ".", "/", "//", "K1ABC/", "/P", "Q1ABC", "QU1RK", "A0", "0A",
          "ABC123", "1234567890123", "ABCDEFGHIJKLMNOPQ", "#", "*", "2*3", "+2*", ",", "a1b", "TU", "R 5"]


def fuzz(r: random.Random) -> str:
    n = r.randrange(1, 8)
    parts = []
    for _ in range(n):
        k = r.random()
        if k < 0.45:
            parts.append(r.choice(TOKENS))
        elif k < 0.75:
            parts.append(call_any(r) if r.random() < 0.8 else bracket(call_any(r)))
        elif k < 0.85:
            parts.append(grid4(r) if r.random() < 0.7 else grid6(r))
        else:
            parts.append(report(r))
    return " ".join(parts)


def wsjtx_examples() -> list[str]:
    """The test messages built into ft8code (-T) and ft4code (-t)."""
    out = []
    for tool, flag in (("ft8code", "-T"), ("ft4code", "-t")):
        text = subprocess.run([tool, flag], capture_output=True, text=True).stdout
        for line in text.splitlines():
            if len(line) > 41 and line[:3].strip().rstrip(".").isdigit():
                out.append(line[4:41].rstrip())
    return out


def messages(count: int, seed: int) -> list[str]:
    r = random.Random(seed)
    seen: set[str] = set()
    out: list[str] = []
    for m in wsjtx_examples() + FIXED + [generated(r) for _ in range(count)]:
        # A tab or newline would break the TSV, and neither is anything an
        # operator can type into a message field.
        if "\t" in m or "\n" in m or m in seen:
            continue
        # "-T" and "-t" alone are the tools' switches for their built-in
        # examples, not messages.
        if m.strip() in ("-T", "-t"):
            continue
        seen.add(m)
        out.append(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--count", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    for tool in ("ft8code", "ft4code"):
        if not shutil.which(tool):
            print(f"{tool} not found: install WSJT-X 2.7.0 (Debian: apt install wsjtx)", file=sys.stderr)
            return 1
    try:
        ver = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "wsjtx"], capture_output=True, text=True).stdout
    except OSError:
        ver = ""
    if ver and not ver.startswith("2.7.0"):
        print(f"warning: wsjtx {ver} installed; the corpus is meant to come from 2.7.0", file=sys.stderr)
    msgs = messages(a.count, a.seed)
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        rows = list(ex.map(run_both, msgs))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# ft8code/ft4code from wsjtx {ver or 'unknown'}; tools/digi-corpus.py --count {a.count} --seed {a.seed}",
             "\t".join(FIELDS)]
    lines += ["\t".join(row) for row in rows]
    data = ("\n".join(lines) + "\n").encode("latin-1")
    if a.out.suffix == ".gz":
        # mtime 0 and no file name: the same corpus is the same bytes.
        with open(a.out, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0, compresslevel=9) as gz:
            gz.write(data)
    else:
        a.out.write_bytes(data)
    stats: dict[str, int] = {}
    for row in rows:
        for k in (row[1], row[6]):
            stats[k] = stats.get(k, 0) + 1
    print(f"{len(rows)} messages -> {a.out} ({a.out.stat().st_size} bytes); results {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
