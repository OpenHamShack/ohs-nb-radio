#!/usr/bin/env python3
"""Hold ohsdigi's decoder against WSJT-X's own routines, stage by stage, and
against /usr/bin/jt9 end to end.

    compare.py <workdir> stages   [nslots] [depth]   FT8 stages 1-4
    compare.py <workdir> subtract [nslots]           FT8 stage 5
    compare.py <workdir> ft4      [nslots] [depth]   FT4 stages
    compare.py <workdir> e2e  ft8|ft4 [slots-per-snr] [depth]   vs jt9
    compare.py <workdir> time ft8|ft4 [nslots] [depth]
    compare.py <workdir> e2e-nb ft8|ft4 [slots-per-snr] [depth]   same, NB's encoder
    compare.py <workdir> ap [slots]                   stage 6, a-priori decoding vs jt9 -Q
    compare.py <workdir> golden                      write tests/jt9_golden.rs

<workdir> is the one harness/build.sh built ft8h in. Test slots are made by
ohsdigi's own deterministic generator (`dev gen`, WSJT-X simulator levels)
from fixed seeds, so every run sees the same audio. The ft8h binary runs in
the harness image (gfortran's runtime is not on the development machine); jt9 runs on
the development machine.

Tolerances are stated next to each comparison. The FFTs differ (FFTW vs
rustfft) and so do the order of some sums, so float stages are compared
within a relative tolerance and the decisions taken from them (peak bins,
time offsets, hard sync counts, decodes) are counted as agreeing or not.
"""
import os
import re
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CRATE = os.path.dirname(HERE)
TARGET = os.environ.get("CARGO_TARGET_DIR", os.path.join(os.path.dirname(CRATE), "target"))
DEV = os.path.join(TARGET, "release", "examples", "dev")
IMAGE = os.environ.get("HARNESS_IMAGE", "ohsdigi-harness:1")


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw)


def ft8h(work, *args):
    """Run the harness binary in its image, with <work> mounted at /w."""
    a = [x.replace(work, "/w") for x in args]
    run(["podman", "run", "--rm", "-v", f"{work}:/w:Z", IMAGE, "/w/ft8h", *a])


def gen(work, mode, name, seed, nsig, lo, hi, dtspread=0.5, drift=0.0, minsep=60.0):
    path = os.path.join(work, "slots", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = run([DEV, "gen", mode, path, str(seed), str(nsig), str(lo), str(hi), str(dtspread), str(drift), str(minsep)])
    sigs = [l.split()[1:] for l in out.stdout.splitlines() if l.startswith("SIG")]
    return path, sigs


def parse(path):
    d = {"CAND": [], "MET": {}, "LLR": {}, "BAIL": set(), "LDPC": [], "DEC": {}, "SBASE": []}
    cur = None
    for line in open(path):
        t = line.split()
        if not t:
            continue
        k = t[0]
        if k == "CAND":
            d["CAND"].append(tuple(float(x) for x in t[2:5]))
        elif k == "SBASE":
            d["SBASE"] = [float(x) for x in t[1:]]
        elif k == "MET":
            cur = int(t[1])
            d["MET"][cur] = [float(x) for x in t[2:]]
            d["LLR"][cur] = []
        elif k.startswith("LLR"):
            d["LLR"][cur].append([float(x) for x in t[1:]])
        elif k == "BAIL":
            d["BAIL"].add(int(t[1]))
        elif k == "LDPC":
            d["LDPC"].append(" ".join(t[1:5] + t[6:]) if False else (t[1], t[2], t[3], t[4], t[6] if len(t) > 6 else "", float(t[5])))
        elif k == "DEC":
            d["DEC"][int(t[1])] = t[-1]
    return d


def rel(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-30)


def cmd_stages(work, nslots=6, depth=1):
    tot = dict(slots=0, hc=0, rc=0, cand_same=0, cand_diff=0, sb=[], met=0, met_ib=0, met_df=0, met_ns=0,
               llr_rel=[], bail_agree=0, bail_dis=0, dec_h=0, dec_r=0, dec_both=0, ldpc=0, ldpc_eq=0, ldpc_dmin=[])
    for i in range(nslots):
        seed = 100 + i
        wav, _ = gen(work, "ft8", f"st{seed}.wav", seed, 18, -22, 2)
        h = os.path.join(work, f"st{seed}.h.txt")
        r = os.path.join(work, f"st{seed}.r.txt")
        ft8h(work, "stages", wav, str(depth), h)
        run([DEV, "stages", wav, str(depth), r])
        H, R = parse(h), parse(r)
        tot["slots"] += 1
        tot["hc"] += len(H["CAND"])
        tot["rc"] += len(R["CAND"])
        # Stage 1: candidate lists, position by position (order matters:
        # it decides subtraction order). Same = same frequency bin and DT
        # step, sync within 1e-3 relative.
        for a, b in zip(H["CAND"], R["CAND"]):
            if abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-4 and rel(a[2], b[2]) < 1e-3:
                tot["cand_same"] += 1
            else:
                tot["cand_diff"] += 1
        tot["cand_diff"] += abs(len(H["CAND"]) - len(R["CAND"]))
        hs = [x for x in H["SBASE"] if x != 0]
        rs = [x for x in R["SBASE"] if x != 0]
        if hs and len(hs) == len(rs):
            tot["sb"].append(max(abs(x - y) for x, y in zip(hs, rs)))
        # Stages 2-3 per candidate, where both lists agree on the candidate.
        n = min(len(H["CAND"]), len(R["CAND"]))
        for c in range(1, n + 1):
            hb, rb = c in H["BAIL"], c in R["BAIL"]
            if hb or rb:
                tot["bail_agree" if hb == rb else "bail_dis"] += 1
            if c in H["MET"] and c in R["MET"]:
                hm, rm = H["MET"][c], R["MET"][c]
                tot["met"] += 1
                tot["met_ib"] += int(hm[2]) == int(rm[2])
                tot["met_df"] += abs(hm[3] - rm[3]) < 1e-6
                tot["met_ns"] += int(hm[5]) == int(rm[5])
                if int(hm[2]) == int(rm[2]) and abs(hm[3] - rm[3]) < 1e-6:
                    for la, lb in zip(H["LLR"][c], R["LLR"][c]):
                        num = max(abs(x - y) for x, y in zip(la, lb))
                        den = max(abs(x) for x in la)
                        tot["llr_rel"].append(num / den)
        hd, rd = set(H["DEC"].values()), set(R["DEC"].values())
        tot["dec_h"] += len(hd)
        tot["dec_r"] += len(rd)
        tot["dec_both"] += len(hd & rd)
        # Stage 4 on its own: our LDPC on WSJT-X's LLRs.
        lr = os.path.join(work, f"st{seed}.ldpc.txt")
        run([DEV, "ldpc", h, lr])
        HL = [l.split() for l in open(h) if l.startswith("LDPC")]
        RL = [l.split() for l in open(lr) if l.startswith("LDPC")]
        for a, b in zip(HL, RL):
            tot["ldpc"] += 1
            same = a[1:5] == b[1:5] and a[6:] == b[6:]
            tot["ldpc_eq"] += same
            if same and int(a[3]) >= 0:
                tot["ldpc_dmin"].append(abs(float(a[5]) - float(b[5])))
    t = tot
    print(f"FT8 stages, depth {depth}, {t['slots']} slots of 18 signals at -22..+2 dB")
    print(f"  stage 1 sync8: candidates WSJT-X {t['hc']} ohsdigi {t['rc']}; same position+freq+dt+sync(1e-3): "
          f"{t['cand_same']}, different {t['cand_diff']}")
    if t["sb"]:
        print(f"  stage 1 baseline sbase: max |diff| {max(t['sb']):.2e} dB")
    print(f"  stage 2 fine sync on {t['met']} candidates: ibest equal {t['met_ib']}, delf equal {t['met_df']}, "
          f"nsync equal {t['met_ns']}; sync bail-outs agree {t['bail_agree']}, disagree {t['bail_dis']}")
    if t["llr_rel"]:
        q = sorted(t["llr_rel"])
        print(f"  stage 3 LLRs ({len(q)} sets): max|diff|/max|llr| median {statistics.median(q):.1e}, "
              f"99% {q[int(0.99 * (len(q) - 1))]:.1e}, max {q[-1]:.1e}")
    print(f"  stage 4 LDPC on WSJT-X's LLRs: {t['ldpc_eq']}/{t['ldpc']} results identical "
          f"(nharderror, ntype, 91 bits); dmin max |diff| {max(t['ldpc_dmin'] or [0]):.1e}")
    print(f"  per-candidate decodes (no subtraction, no AP): WSJT-X {t['dec_h']} ohsdigi {t['dec_r']} both {t['dec_both']}")


def cmd_subtract(work, nslots=4):
    import struct
    worst = []
    for i in range(nslots):
        seed = 300 + i
        wav, sigs = gen(work, "ft8", f"sub{seed}.wav", seed, 10, -12, 6)
        # Subtract every signal from its true parameters (tones from our
        # encoder via the harness's own genft8: the list carries tones), as
        # ft8_decode does: in order, the first half with DT refinement.
        lst = os.path.join(work, f"sub{seed}.lst")
        with open(lst, "w") as f:
            for k, s in enumerate(sigs):
                tones = run([DEV, "tones", s[0]]).stdout.split()
                f.write(f"{float(s[1])} {float(s[2]) + 0.5} {k % 2} {' '.join(tones)}\n")
        ho, ro = os.path.join(work, f"sub{seed}.h.f32"), os.path.join(work, f"sub{seed}.r.f32")
        ft8h(work, "subtract", wav, lst, ho)
        run([DEV, "subtract", wav, lst, ro])
        h = struct.unpack(f"<{180000}f", open(ho, "rb").read())
        r = struct.unpack(f"<{180000}f", open(ro, "rb").read())
        x = run([DEV, "rms", wav]).stdout.split()
        d = max(abs(a - b) for a, b in zip(h, r))
        rmsd = (sum((a - b) ** 2 for a, b in zip(h, r)) / len(h)) ** 0.5
        rmsh = (sum(a * a for a in h) / len(h)) ** 0.5
        worst.append((d, rmsd, rmsh, float(x[0])))
    print("FT8 stage 5 subtractft8 (10 signals a slot, alternate ones with DT refinement):")
    for d, rmsd, rmsh, rin in worst:
        print(f"  input rms {rin:.1f}, residual rms {rmsh:.2f}; ohsdigi vs WSJT-X: max |diff| {d:.3f}, rms diff {rmsd:.2e}")


def cmd_ft4(work, nslots=6, depth=1):
    tot = dict(h=0, r=0, same=0, bm=0, bm_eq=0, rel=[], dh=0, dr=0, both=0)
    for i in range(nslots):
        seed = 500 + i
        wav, _ = gen(work, "ft4", f"f4{seed}.wav", seed, 12, -18, 2, 0.4, 0.0, 100.0)
        h, r = os.path.join(work, f"f4{seed}.h.txt"), os.path.join(work, f"f4{seed}.r.txt")
        ft8h(work, "ft4", wav, str(depth), h)
        run([DEV, "ft4", wav, str(depth), r])

        def p(path):
            c, bm, bits, dec = [], {}, {}, set()
            last = None
            for l in open(path):
                t = l.split()
                if t[0] == "FT4CAND":
                    c.append((float(t[2]), float(t[3])))
                elif t[0] == "FT4BM":
                    last = (int(t[1]), int(t[2]))
                    bm[last] = (float(t[3]), int(t[4]), int(t[5]), float(t[6]))
                elif t[0] == "FT4BITS":
                    bits[last] = [float(x) for x in t[1:]]
                elif t[0] == "FT4DEC":
                    b = [x for x in t if re.fullmatch(r"[01]{77}", x)]
                    dec.add(b[0] if b else t[-1])
            return c, bm, bits, dec
        hc, hbm, hbits, hd = p(h)
        rc, rbm, rbits, rd = p(r)
        tot["h"] += len(hc)
        tot["r"] += len(rc)
        tot["same"] += sum(1 for a, b in zip(hc, rc) if abs(a[0] - b[0]) < 1e-2 and rel(a[1], b[1]) < 1e-3)
        for k in hbm:
            if k in rbm:
                tot["bm"] += 1
                a, b = hbm[k], rbm[k]
                if a[1] == b[1] and a[2] == b[2]:
                    tot["bm_eq"] += 1
                    if k in hbits and k in rbits:
                        num = max(abs(x - y) for x, y in zip(hbits[k], rbits[k]))
                        tot["rel"].append(num / max(abs(x) for x in hbits[k]))
        # WSJT-X's FT4 callback gives text, which the harness packs; ours
        # gives the payload: compare bit strings.
        tot["dh"] += len(hd)
        tot["dr"] += len(rd)
        tot["both"] += len(hd & rd)
    t = tot
    print(f"FT4, depth {depth}, {nslots} slots of 12 signals at -18..+2 dB")
    print(f"  candidates WSJT-X {t['h']} ohsdigi {t['r']}, same freq(0.01 Hz)+strength(1e-3) {t['same']}")
    print(f"  sync search: {t['bm_eq']}/{t['bm']} (candidate, segment) pairs with identical ibest and idf")
    if t["rel"]:
        q = sorted(t["rel"])
        print(f"  bit metrics: max|diff|/max median {statistics.median(q):.1e}, max {q[-1]:.1e}")
    print(f"  decodes WSJT-X {t['dh']} ohsdigi {t['dr']} both {t['both']}")


JT9_RE = re.compile(r"^\d{6}\s+(-?\d+)\s+(-?\d+\.\d)\s+(\d+)\s+[~+]\s+(.+?)\s*$")


def jt9_decode(wav, mode, depth, tmp):
    flag = "-8" if mode == "ft8" else "-5"
    per = "15" if mode == "ft8" else "7"
    t0 = time.perf_counter()
    out = run(["jt9", flag, "-p", per, "-d", str(depth), wav], cwd=tmp).stdout
    el = time.perf_counter() - t0
    texts = []
    for l in out.splitlines():
        m = JT9_RE.match(l.strip())
        if m:
            # jt9 appends "?" (low confidence) and/or "aN" (a-priori type).
            txt = re.sub(r"(\s+(a\d|\?))+\s*$", "", m.group(4)).strip()
            texts.append(txt)
    return texts, el


def pool_texts():
    """Payload hex -> the text WSJT-X decodes it to (ft8code's "Decoded"
    column: a message that does not pack as typed, such as a call with no
    standard form, comes back as free text, and that is what jt9 prints)."""
    pool = {}
    for l in open(os.path.join(CRATE, "src", "decode", "sim.rs")):
        m = re.match(r'\s+\("([^"]+)", "([0-9a-f]{20})"\),', l)
        if m:
            out = run(["ft8code", m.group(1)]).stdout
            d = re.search(r"^\s*1\.\s(.{37})\s(.{37})", out, re.M)
            pool[m.group(2)] = d.group(2).strip()
    return pool


def cmd_e2e(work, mode="ft8", per=10, depth=1):
    """Sensitivity: single-SNR slots, many signals each; how many of the
    transmitted messages each decoder recovers."""
    pool = pool_texts()
    tmp = os.path.join(work, "jt9tmp")
    os.makedirs(tmp, exist_ok=True)
    snrs = list(range(-24, 11, 2)) if mode == "ft8" else list(range(-20, 11, 2))
    nsig = 12 if mode == "ft8" else 8
    sep, dts = (60, 0.8) if mode == "ft8" else (100, 0.3)
    print(f"{mode.upper()} end to end, depth {depth}: {per} slots per SNR, {nsig} signals a slot "
          f"(distinct messages, >={sep} Hz apart, DT +-{dts} s{', drift +-0.1 Hz/s' if mode == 'ft8' else ''})")
    print(f"  {'SNR':>4} {'sent':>5} {'jt9':>5} {'ohsdigi':>6} {'both':>5} {'jt9 only':>8} {'ours only':>9} "
          f"{'false jt9':>9} {'false ours':>10}")
    for snr in snrs:
        sent = j = o = both = jo = oo = false = jfalse = 0
        for k in range(per):
            seed = 10000 + 100 * (snr + 30) + k
            wav, sigs = gen(work, mode, f"e2e_{mode}_{snr}_{k}.wav", seed, nsig, snr, snr,
                            0.8 if mode == "ft8" else 0.3, 0.1 if mode == "ft8" else 0.0, 60 if mode == "ft8" else 100)
            truth = {pool[s[0]] for s in sigs}
            sent += len(sigs)
            jt, _ = jt9_decode(wav, mode, depth, tmp)
            ours = run([DEV, "decode", mode, wav, str(depth)]).stdout.split("\n")
            ot = {pool.get(l.split()[0], "?" + l.split()[0]) for l in ours if l.strip()}
            js = set(jt)
            # Messages can repeat in a slot (pool of 30): count unique.
            j += len(js & truth)
            o += len(ot & truth)
            both += len(js & ot & truth)
            jo += len((js - ot) & truth)
            oo += len((ot - js) & truth)
            false += len(ot - truth)
            jfalse += len(js - truth)
        print(f"  {snr:>4} {sent:>5} {j:>5} {o:>6} {both:>5} {jo:>8} {oo:>9} {jfalse:>9} {false:>10}")


def cmd_e2e_nb(work, mode="ft8", per=6, depth=1):
    """As e2e, but the transmissions are rendered by NB's own FT8/FT4
    encoder (ohscore.modes.ft8: ft8code/ft4code tones, gen_ft8wave /
    gen_ft4wave in numpy), the one its simulator uses - a waveform ohsdigi's generator
    did not make. Same SNR convention (ft8sim's), same scale into 16 bits."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(CRATE)))
    import numpy as np
    from ohscore.modes import ft8 as nbft8
    pool = pool_texts()
    texts = sorted(set(pool.values()))
    codec = nbft8._FT8CODE if mode == "ft8" else nbft8._FT4CODE
    tones = {t: nbft8._channel_symbols(codec, t) for t in texts}
    n = 15 * 12000 if mode == "ft8" else 21 * 3456
    sym = 1920 if mode == "ft8" else 576
    tmp = os.path.join(work, "jt9tmp")
    os.makedirs(tmp, exist_ok=True)
    nsig = 12 if mode == "ft8" else 8
    print(f"{mode.upper()} end to end on NB's own encoder, depth {depth}: {per} slots per SNR, {nsig} signals a slot")
    print(f"  {'SNR':>4} {'sent':>5} {'jt9':>5} {'ohsdigi':>6} {'both':>5} {'jt9 only':>8} {'ours only':>9}")
    for snr in range(-24, 3, 2) if mode == "ft8" else range(-20, 3, 2):
        sent = j = o = both = jo = oo = 0
        for k in range(per):
            rng = np.random.default_rng(20000 + 100 * (snr + 30) + k)
            wave = np.zeros(n)
            chosen = list(rng.choice(texts, nsig, replace=False))
            freqs = []
            for t in chosen:
                while True:
                    f = rng.uniform(300, 2600)
                    if all(abs(f - g) > (60 if mode == "ft8" else 100) for g in freqs):
                        break
                freqs.append(f)
                a = nbft8._gfsk_audio(tones[t], mode, f).astype(np.float64)  # unit-amplitude sine
                start = int(round((0.5 + rng.uniform(-0.5, 0.5) * (1 if mode == "ft8" else 0.4)) * 12000))
                if mode == "ft4":
                    start -= sym  # the ramp symbol precedes the nominal start
                amp = np.sqrt(2 * 2500 / 6000) * 10 ** (0.05 * snr)
                seg = a[:max(0, min(len(a), n - start))]
                wave[start:start + len(seg)] += amp * seg
            wave += rng.normal(0, 1, n)
            ints = np.clip(np.round(100 * wave), -32767, 32767).astype("<i2")
            wav = os.path.join(work, "slots", f"nb_{mode}_{snr}_{k}.wav")
            import wave as wv
            with wv.open(wav, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(12000)
                w.writeframes(ints.tobytes())
            truth = set(chosen)
            sent += len(truth)
            jt, _ = jt9_decode(wav, mode, depth, tmp)
            ours = run([DEV, "decode", mode, wav, str(depth)]).stdout.split("\n")
            ot = {pool.get(l.split()[0], "?") for l in ours if l.strip()}
            js = set(jt)
            j += len(js & truth)
            o += len(ot & truth)
            both += len(js & ot & truth)
            jo += len((js - ot) & truth)
            oo += len((ot - js) & truth)
        print(f"  {snr:>4} {sent:>5} {j:>5} {o:>6} {both:>5} {jo:>8} {oo:>9}")


def cmd_ap(work, per=8):
    """Stage 6, a-priori decoding: weak signals carrying jt9's own dummy
    calls (K1ABC, W9XYZ) near 1500 Hz, where WSJT-X allows its DxCall AP
    types, decoded at every QSO-progress state (jt9 -Q) - which selects
    AP types 1-6 - by jt9 and by ohsdigi. Agreement is per message *and*
    per AP type (jt9's "aN" marker against ohsdigi's iaptype)."""
    pool = pool_texts()
    tmp = os.path.join(work, "jt9tmp")
    os.makedirs(tmp, exist_ok=True)
    print(f"FT8 a-priori decoding: {per} slots per (depth, QSO state, SNR), 3 signals within 1440-1560 Hz, "
          f"K1ABC/W9XYZ messages only")
    print(f"  {'depth':>5} {'Q':>2} {'SNR':>4} {'jt9':>4} {'ours':>4} {'both':>4} {'AP types jt9':>16} {'AP types ours':>16}")
    for depth in (1, 3):
        for q in range(6):
            for snr in (-24, -22, -20):
                j = o = b = 0
                jt_ap, our_ap = {}, {}
                for k in range(per):
                    seed = 40000 + 1000 * depth + 100 * q + 10 * (snr + 30) + k
                    path = os.path.join(work, "slots", f"ap_{depth}_{q}_{snr}_{k}.wav")
                    run([DEV, "gen", "ft8", path, str(seed), "3", str(snr), str(snr), "0.3", "0.0", "50",
                         "1440", "1560", "calls"])
                    out = run(["jt9", "-8", "-p", "15", "-d", str(depth), "-Q", str(q), path], cwd=tmp).stdout
                    js = {}
                    for l in out.splitlines():
                        m = JT9_RE.match(l.strip())
                        if m:
                            ap = re.search(r"\sa(\d)\s*$", m.group(4))
                            txt = re.sub(r"(\s+(a\d|\?))+\s*$", "", m.group(4)).strip()
                            js[txt] = int(ap.group(1)) if ap else 0
                    ours = {}
                    for l in run([DEV, "decode", "ft8", path, str(depth), f"q={q}"]).stdout.splitlines():
                        t = l.split()
                        ours[pool.get(t[0], "?" + t[0])] = int(t[4])
                    j += len(js)
                    o += len(ours)
                    b += sum(1 for t in js if t in ours and ours[t] == js[t])
                    for v in js.values():
                        jt_ap[v] = jt_ap.get(v, 0) + 1
                    for v in ours.values():
                        our_ap[v] = our_ap.get(v, 0) + 1
                fmt = lambda d: " ".join(f"a{k}:{d[k]}" for k in sorted(d)) or "-"
                print(f"  {depth:>5} {q:>2} {snr:>4} {j:>4} {o:>4} {b:>4} {fmt(jt_ap):>16} {fmt(our_ap):>16}")


def cmd_time(work, mode="ft8", n=10, depth=1):
    tmp = os.path.join(work, "jt9tmp")
    os.makedirs(tmp, exist_ok=True)
    wavs = []
    for k in range(n):
        wav, _ = gen(work, mode, f"time_{mode}_{k}.wav", 777 + k, 20 if mode == "ft8" else 10, -20, 5)
        wavs.append(wav)
    jt = []
    for w in wavs:
        jt9_decode(w, mode, depth, tmp)  # warm the FFTW wisdom
        jt.append(jt9_decode(w, mode, depth, tmp)[1])
    par = run([DEV, "time", mode, str(depth), *wavs]).stdout.splitlines()[-1].split()[1]
    ser = run([DEV, "time", mode, str(depth), *wavs], env={**os.environ, "OHSDIGI_SERIAL": "1"}).stdout.splitlines()[-1].split()[1]
    print(f"{mode.upper()} depth {depth}, {n} slots: jt9 {statistics.mean(jt):.3f} s/slot (process incl.), "
          f"ohsdigi one core {float(ser):.3f} s, all cores ({os.cpu_count()}) {float(par):.3f} s")


GOLDEN = [
    # mode, depth, seed, nsig, snr_lo, snr_hi, dt_spread, drift, min_sep
    ("ft8", 1, 41, 15, -21, -17, 0.6, 0.1, 60), ("ft8", 1, 42, 15, -20, -10, 0.6, 0.1, 60),
    ("ft8", 1, 43, 20, -18, 5, 0.8, 0.1, 50), ("ft8", 1, 44, 25, -15, 10, 0.5, 0.0, 40),
    ("ft8", 2, 45, 15, -21, -10, 0.6, 0.1, 60), ("ft8", 3, 46, 15, -22, -16, 0.6, 0.1, 60),
    ("ft8", 3, 47, 25, -20, 5, 0.8, 0.1, 40), ("ft4", 1, 48, 10, -17, -10, 0.3, 0.0, 100),
    ("ft4", 1, 49, 12, -15, 5, 0.3, 0.0, 90), ("ft4", 3, 50, 10, -17, -5, 0.3, 0.0, 100),
]


def cmd_golden(work):
    """Write tests/jt9_golden.rs: jt9's own decodes of fixed generated
    slots, so `cargo test` checks ohsdigi against jt9 without jt9."""
    pool = pool_texts()
    by_text = {v: k for k, v in pool.items()}
    tmp = os.path.join(work, "jt9tmp")
    os.makedirs(tmp, exist_ok=True)
    rows = []
    for mode, depth, seed, nsig, lo, hi, dts, drift, sep in GOLDEN:
        wav, _ = gen(work, mode, f"golden_{seed}.wav", seed, nsig, lo, hi, dts, drift, sep)
        texts, _ = jt9_decode(wav, mode, depth, tmp)
        hexes = sorted(by_text[t] for t in texts if t in by_text)
        stray = [t for t in texts if t not in by_text]
        if stray:
            print(f"seed {seed}: jt9 decoded text not in the pool (false decode?): {stray}", file=sys.stderr)
        rows.append((mode, depth, seed, nsig, lo, hi, dts, drift, sep, hexes, len(stray)))
    out = os.path.join(CRATE, "tests", "jt9_golden.rs")
    with open(out, "w") as f:
        f.write("//! ohsdigi against jt9 without jt9: each case is a generated slot (decode::sim,\n"
                "//! fixed seed) and the payloads /usr/bin/jt9 (WSJT-X 2.7.0, Debian) decoded\n"
                "//! from it, as `jt9 -8|-5 -p 15|7 -d <depth>` - NB's invocation plus the\n"
                "//! depth. Written by `harness/compare.py <work> golden`; regenerate rather\n"
                "//! than edit. ohsdigi must decode exactly the same set.\n\n"
                "use ohsdigi::decode::{ft4, ft8};\n"
                "use ohsdigi::decode::sim::bits77_to_hex;\nuse ohsdigi::msg77::CallHashes;\n"
                "use ohsdigi::decode::sim::{make_slot, payload_pool, random_signals, Mode};\n\n"
                "#[allow(clippy::type_complexity)]\n"
                "const CASES: &[(&str, i32, u64, usize, f64, f64, f64, f64, f64, &[&str])] = &[\n")
        for mode, depth, seed, nsig, lo, hi, dts, drift, sep, hexes, _ in rows:
            hx = ", ".join(f'"{h}"' for h in hexes)
            f.write(f'    ("{mode}", {depth}, {seed}, {nsig}, {float(lo)!r}, {float(hi)!r}, {float(dts)!r}, '
                    f'{float(drift)!r}, {float(sep)!r}, &[{hx}]),\n')
        f.write("];\n\n"
                "#[test]\n"
                "fn decodes_what_jt9_decodes() {\n"
                "    let pool = payload_pool();\n"
                "    let mut bad = vec![];\n"
                "    for &(mode, depth, seed, nsig, lo, hi, dts, drift, sep, want) in CASES {\n"
                "        let m = if mode == \"ft8\" { Mode::Ft8 } else { Mode::Ft4 };\n"
                "        let sigs = random_signals(m, &pool, nsig, lo, hi, dts, drift, sep, seed);\n"
                "        let x = make_slot(m, &sigs, seed, true);\n"
                "        let mut got: Vec<String> = if m == Mode::Ft8 {\n"
                "            let p = ft8::Ft8Params { ndepth: depth, threads: 2, ..ft8::Ft8Params::jt9() };\n"
                "            ft8::decode_slot(&x, &p, &mut CallHashes::new()).decodes.iter().map(|d| bits77_to_hex(&d.payload)).collect()\n"
                "        } else {\n"
                "            let p = ft4::Ft4Params { ndepth: depth, threads: 2, ..ft4::Ft4Params::jt9() };\n"
                "            ft4::decode_slot(&x, &p, &mut CallHashes::new()).0.iter().map(|d| bits77_to_hex(&d.payload)).collect()\n"
                "        };\n"
                "        got.sort();\n"
                "        let want: Vec<String> = want.iter().map(|s| s.to_string()).collect();\n"
                "        if got != want {\n"
                "            bad.push(format!(\"{} depth {} seed {}: jt9 {:?}, ohsdigi {:?}\", mode, depth, seed, want, got));\n"
                "        }\n"
                "    }\n"
                "    assert!(bad.is_empty(), \"{}\", bad.join(\"\\n\"));\n"
                "}\n")
    for r in rows:
        print(f"{r[0]} depth {r[1]} seed {r[2]}: jt9 decoded {len(r[9])} of {r[3]}")
    print(f"wrote {out}")


if __name__ == "__main__":
    work = os.path.abspath(sys.argv[1])
    cmd = sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "stages":
        cmd_stages(work, *(int(x) for x in rest))
    elif cmd == "subtract":
        cmd_subtract(work, *(int(x) for x in rest))
    elif cmd == "ft4":
        cmd_ft4(work, *(int(x) for x in rest))
    elif cmd == "e2e":
        cmd_e2e(work, rest[0], *(int(x) for x in rest[1:]))
    elif cmd == "time":
        cmd_time(work, rest[0], *(int(x) for x in rest[1:]))
    elif cmd == "e2e-nb":
        cmd_e2e_nb(work, rest[0], *(int(x) for x in rest[1:]))
    elif cmd == "ap":
        cmd_ap(work, *(int(x) for x in rest))
    elif cmd == "golden":
        cmd_golden(work)
