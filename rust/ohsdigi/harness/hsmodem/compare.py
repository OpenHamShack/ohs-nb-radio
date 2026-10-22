#!/usr/bin/env python3
"""Hold ohsdigi's HSmodem port against HSmodem's own code, stage by stage.

    compare.py <workdir> frames  [nspec]        Pack(): frames byte for byte; symbols; TX audio
    compare.py <workdir> rs      [ncw]          RS decoder vs Schifra on random error patterns
    compare.py <workdir> stages  [seconds]      receive, audio path: every stage, SNRs x offsets
    compare.py <workdir> iq      [seconds]      receive, IQ path (the tracker on complex baseband)
    compare.py <workdir> corpus  <outdir>       write the compact test corpus (testdata/hsmodem)
    compare.py <workdir> speeds  [seconds]      station to station at every speed mode, both ways:
                                                HSmodem's TX -> NB's receiver, NB's TX -> HSmodem's receiver
                                                (HSH_MARKER=1: HSmodem's TX with its 100 Hz tuning marker,
                                                its program's default)
    compare.py <workdir> corpus4 <outdir>       a file transfer from HSmodem's TX at speed 4 (the default)

<workdir> is the one harness/hsmodem/build.sh built hsh and hsh_ams in.
hsdev (rust/ohsdigi/examples/hsdev.rs) is built here with cargo --release.
Every test signal is made by HSmodem's own transmitter (hsh tx), from
fixed seeds; noise and frequency offsets are added here, identically for
both receivers. The binaries run on the development machine (they need
only libfftw3f, which it has).

Tolerances are stated beside each comparison. liquid is compiled C with
its own summation order and libm; ohsdigi is Rust in the same single
precision, so float stages are compared to a tolerance and the decisions
taken from them (hard symbols, frames) are counted as agreeing or not.
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CRATE = os.path.dirname(os.path.dirname(HERE))
TARGET = os.environ.get("CARGO_TARGET_DIR", os.path.join(os.path.dirname(CRATE), "target"))
HSDEV = os.path.join(TARGET, "release", "examples", "hsdev")
CARGO = os.path.expanduser("~/.cargo/bin/cargo")
PAYLOAD = 219


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw)


def build_hsdev():
    run([CARGO, "build", "--release", "--example", "hsdev"], cwd=CRATE,
        env={**os.environ, "CARGO_TARGET_DIR": TARGET})


def spec(rng, nfiles=3, ext=12):
    """Records as Pack() is called for the beacon: files (first/next/last,
    each frame once, a repeat now and then), type-8 external frames between."""
    recs = []
    for _ in range(nfiles):
        n = int(rng.integers(2, 9))
        t = int(rng.choice([2, 3, 4, 5]))
        for i in range(n):
            st = 0 if i == 0 else 2 if i == n - 1 else 1
            recs.append(bytes([t, st, 0]) + rng.integers(0, 256, PAYLOAD, dtype=np.uint8).tobytes())
            if rng.random() < 0.2:
                recs.append(bytes([t, st, 1]) + recs[-1][3:])
        for _ in range(int(rng.integers(0, ext))):
            recs.append(bytes([8, 3, 1]) + rng.integers(0, 256, PAYLOAD, dtype=np.uint8).tobytes())
    return b"".join(recs)


def cmd_frames(work, nspec=20):
    ok = 0
    worst_pts = worst_audio = 0.0
    for seed in range(nspec):
        rng = np.random.default_rng(1000 + seed)
        p = os.path.join(work, "c_spec.bin")
        open(p, "wb").write(spec(rng))
        run([os.path.join(work, "hsh"), "tx", p, f"{work}/c_hf.bin", f"{work}/c_ha.f32"], cwd=work)
        run([os.path.join(work, "hsh_ams"), "tx", p, f"{work}/c_hf2.bin", f"{work}/c_hp.c64"], cwd=work)
        run([HSDEV, "tx", p, f"{work}/c_rf.bin", f"{work}/c_ra.f32"])
        run([HSDEV, "points", p, f"{work}/c_rf2.bin", f"{work}/c_rp.c64"])
        hf, rf = open(f"{work}/c_hf.bin", "rb").read(), open(f"{work}/c_rf.bin", "rb").read()
        ok += hf == rf
        hp, rp = np.fromfile(f"{work}/c_hp.c64", np.complex64), np.fromfile(f"{work}/c_rp.c64", np.complex64)
        ha, ra = np.fromfile(f"{work}/c_ha.f32", np.float32), np.fromfile(f"{work}/c_ra.f32", np.float32)
        assert len(hp) == len(rp) and len(ha) == len(ra), (len(hp), len(rp), len(ha), len(ra))
        worst_pts = max(worst_pts, float(np.abs(hp - rp).max()))
        worst_audio = max(worst_audio, float(np.abs(ha - ra).max() / np.abs(ha).max()))
    print(f"frames: {ok}/{nspec} specs byte-identical (header, counter, CRC, Schifra's parity, scrambling)")
    print(f"symbols (beacon build, one complex point per symbol): max |difference| {worst_pts:.2e}")
    print(f"TX audio 48 kHz (RRC interpolator, 1500 Hz NCO): max |difference| / peak {worst_audio:.2e}")


def cmd_rs(work, ncw=4000):
    rng = np.random.default_rng(7)
    # Codewords from real frames (HSmodem's encoder), errors added here.
    p = os.path.join(work, "c_spec.bin")
    open(p, "wb").write(b"".join(bytes([3, 1, 0]) + rng.integers(0, 256, PAYLOAD, dtype=np.uint8).tobytes()
                                 for _ in range(ncw)))
    run([os.path.join(work, "hsh_ams"), "tx", p, f"{work}/c_hf.bin", f"{work}/c_hp.c64"], cwd=work)
    fr = np.frombuffer(open(f"{work}/c_hf.bin", "rb").read(), np.uint8).reshape(-1, 258)
    scr = np.frombuffer(bytes(_scramble_table()), np.uint8)
    cws = fr[:, 3:] ^ scr
    nerr = np.zeros(ncw, int)
    out = cws.copy()
    for i in range(ncw):
        k = int(rng.integers(0, 25))
        pos = rng.choice(255, k, replace=False)
        out[i, pos] ^= rng.integers(1, 256, k, dtype=np.uint8)
        nerr[i] = k
    out.tofile(f"{work}/c_cw.bin")
    run([os.path.join(work, "hsh"), "rs", f"{work}/c_cw.bin", f"{work}/c_hr.bin"], cwd=work)
    run([HSDEV, "rs", f"{work}/c_cw.bin", f"{work}/c_rr.bin"])
    h = np.fromfile(f"{work}/c_hr.bin", np.uint8).reshape(-1, 224)
    r = np.fromfile(f"{work}/c_rr.bin", np.uint8).reshape(-1, 224)
    same_ok = (h[:, 0] == r[:, 0])
    both = (h[:, 0] == 1) & (r[:, 0] == 1)
    same_data = np.all(h[both, 1:] == r[both, 1:], axis=1)
    print(f"RS: {ncw} codewords with 0-24 byte errors")
    for k in (0, 8, 16, 17, 20, 24):
        m = nerr == k
        print(f"  {k:2d} errors: Schifra corrected {int(h[m, 0].sum())}/{int(m.sum())}, ohsdigi {int(r[m, 0].sum())}/{int(m.sum())}")
    print(f"  same success/failure on {int(same_ok.sum())}/{ncw}; same data where both decoded: "
          f"{int(same_data.sum())}/{int(both.sum())}")
    good = (nerr <= 16)
    print(f"  <=16 errors: both corrected and right: {int(np.all(r[good, 1:] == cws[good, :223], axis=1).sum())}/{int(good.sum())}")


def _scramble_table():
    seq = [130, 239, 223, 19, 146, 254, 12, 86, 106, 68, 77, 213, 243, 216, 102, 227, 108, 113, 229, 89, 26, 64, 138,
           216, 225, 121, 194, 137, 152, 64, 51, 175, 68, 200, 37, 104, 247, 68, 193, 50, 19, 14, 196, 81, 4, 236, 191,
           249, 83, 25, 161, 171, 167, 29, 33, 139, 7, 152, 230, 144, 125, 206, 34, 236, 112, 78, 219, 34, 181, 161,
           7, 45, 198, 235, 62, 115, 194, 100, 209, 95, 186, 161, 53, 10, 110, 246, 122, 246, 207, 194, 178, 63, 232,
           93, 158, 234, 231, 73, 214, 64]
    return [seq[i % 100] for i in range(255)]


def beacon_audio(work, seconds, seed):
    """HSmodem's own transmitter: spec -> hsh tx -> 48 kHz audio."""
    rng = np.random.default_rng(seed)
    nframes = int(seconds * 7200 / (258 * 8)) + 2
    recs = []
    n = 0
    while n < nframes:
        recs.append(spec(rng, nfiles=1, ext=4))
        n = sum(len(r) for r in recs) // 222
    p = os.path.join(work, "c_spec.bin")
    open(p, "wb").write(b"".join(recs))
    run([os.path.join(work, "hsh"), "tx", p, f"{work}/c_hf.bin", f"{work}/c_ha.f32"], cwd=work)
    a = np.fromfile(f"{work}/c_ha.f32", np.float32)
    return a, np.frombuffer(open(f"{work}/c_hf.bin", "rb").read(), np.uint8).reshape(-1, 258)


def shift_real(a, hz, fs=48000.0):
    """Move a real signal up by hz (analytic signal, mix, real part)."""
    n = len(a)
    A = np.fft.fft(a)
    A[n // 2 + 1:] = 0
    A[1:(n + 1) // 2] *= 2
    z = np.fft.ifft(A) * np.exp(2j * np.pi * hz * np.arange(n) / fs)
    return z.real.astype(np.float32)


def add_noise(a, snr_db, rng, bw=2400.0, fs=48000.0):
    """Noise for an SNR in the symbol-rate bandwidth (2400 Hz): Es/N0."""
    p = float(np.mean(a.astype(np.float64) ** 2))
    n0 = p / 10 ** (snr_db / 10) / bw          # per Hz, one-sided real
    sigma = np.sqrt(n0 * fs / 2)
    return (a + rng.normal(0, sigma, len(a))).astype(np.float32)


def read_stages(path):
    return np.fromfile(path, np.float32).reshape(-1, 8)


def read_frames(path):
    out = {}
    for line in open(path):
        sym, hexs = line.split()
        out[int(sym)] = (hexs[:2] + hexs[4:8], hexs[20:])     # type, counter, payload
    return out


def compare_rx(work, tag, hsh_args, dev_args):
    run(hsh_args, cwd=work)
    run(dev_args)
    h, r = read_stages(f"{work}/c_hs.f32"), read_stages(f"{work}/c_rs.f32")
    hf, rf = read_frames(f"{work}/c_hfr.txt"), read_frames(f"{work}/c_rfr.txt")
    n = min(len(h), len(r))
    sym_agree = float(np.mean(h[:n, 2] == r[:n, 2])) if n else 0.0
    d = np.abs((h[:n, 0] + 1j * h[:n, 1]) - (r[:n, 0] + 1j * r[:n, 1]))
    # tau is a fraction of a sample that wraps at 1: compare on the circle.
    tau = np.abs((h[:n, 3] - r[:n, 3] + 0.5) % 1.0 - 0.5)
    fr = np.abs(h[:n, 4] - r[:n, 4]) * 4800 / np.pi / 2       # rad/sample at 2 samples/symbol -> Hz
    gain = np.abs(h[:n, 6] - r[:n, 6]) / np.maximum(np.abs(h[:n, 6]), 1e-9)
    hs, rs_ = set(hf.items()), set(rf.items())
    print(f"{tag}: symbols {len(h)}/{len(r)}; hard symbols agree {100 * sym_agree:.3f} %; "
          f"soft symbol |diff| median {np.median(d) if n else 0:.1e} max {d.max() if n else 0:.1e}; "
          f"tau max diff {tau.max() if n else 0:.1e}; carrier max diff {fr.max() if n else 0:.2e} Hz; "
          f"AGC gain max rel diff {gain.max() if n else 0:.1e}; "
          f"frames HSmodem {len(hf)} ohsdigi {len(rf)} same {len(hs & rs_)}; "
          f"header hits ok/fec/crc HSmodem {int((h[:, 7] == 1).sum())}/{int((h[:, 7] == -1).sum())}/{int((h[:, 7] == -2).sum())} "
          f"ohsdigi {int((r[:, 7] == 1).sum())}/{int((r[:, 7] == -1).sum())}/{int((r[:, 7] == -2).sum())}")
    return len(hf), len(rf), len(hs & rs_), sym_agree


def cmd_stages(work, seconds=20.0):
    a0, frames = beacon_audio(work, seconds, 42)
    print(f"test signal: {len(frames)} frames from HSmodem's transmitter, {len(a0) / 48000:.1f} s at 48 kHz")
    for off in (0.0, 3.0, -5.0):
        for snr in (30, 20, 16, 14, 12, 10):
            rng = np.random.default_rng(int(snr * 10 + off))
            a = add_noise(shift_real(a0, off) if off else a0, snr, rng)
            a.tofile(f"{work}/c_in.f32")
            compare_rx(work, f"audio  offset {off:+4.1f} Hz  Es/N0 {snr:2d} dB",
                       [os.path.join(work, "hsh"), "rx", f"{work}/c_in.f32", f"{work}/c_hs.f32", f"{work}/c_hfr.txt"],
                       [HSDEV, "rx", f"{work}/c_in.f32", f"{work}/c_rs.f32", f"{work}/c_rfr.txt"])


def audio_to_iq(a, fs=48000.0, centre=1500.0, out=9600.0):
    """HSmodem's audio as complex baseband at 9600 S/s: analytic signal,
    mixed down from 1500 Hz, low-passed and decimated by 5."""
    n = len(a)
    A = np.fft.fft(a)
    A[n // 2 + 1:] = 0
    A[1:(n + 1) // 2] *= 2
    f = np.fft.fftfreq(n, 1 / fs)
    A[np.abs(f - centre) > 2400] = 0
    z = np.fft.ifft(A) * np.exp(-2j * np.pi * centre * np.arange(n) / fs)
    return z[:: int(fs / out)].astype(np.complex64)


def cmd_iq(work, seconds=20.0):
    a0, frames = beacon_audio(work, seconds, 43)
    for off in (0.0, 3.0):
        for snr in (30, 16, 12, 10):
            rng = np.random.default_rng(int(snr * 10 + off) + 1)
            a = add_noise(shift_real(a0, off) if off else a0, snr, rng)
            audio_to_iq(a).tofile(f"{work}/c_in.c64")
            compare_rx(work, f"IQ     offset {off:+4.1f} Hz  Es/N0 {snr:2d} dB",
                       [os.path.join(work, "hsh"), "rxiq", f"{work}/c_in.c64", f"{work}/c_hs.f32", f"{work}/c_hfr.txt"],
                       [HSDEV, "rxiq", f"{work}/c_in.c64", f"{work}/c_rs.f32", f"{work}/c_rfr.txt"])


# hsmodem.cpp sr[]: audio rate, TX interpolation, bits a symbol, bit/s.
SR = [(48000, 40, 1, 1200), (48000, 20, 1, 2400), (48000, 32, 2, 3000), (48000, 24, 2, 4000), (44100, 20, 2, 4410),
      (48000, 20, 2, 4800), (44100, 24, 3, 5500), (48000, 24, 3, 6000), (44100, 20, 3, 6600), (48000, 20, 3, 7200)]


def transfer_spec(rng, nframes, ftype=5, first_repeats=3, last_repeats=2):
    """A file as HSmodem's GUI sends it (ArraySend.cs, hsmodem.cpp): the
    first frame and its repeats (the preamble: repeat=1 records, which
    Pack() gives the same counter), then next frames once, the last one
    repeated."""
    first = rng.integers(0, 256, PAYLOAD, dtype=np.uint8).tobytes()
    recs = [bytes([ftype, 0, 0]) + first] + [bytes([ftype, 0, 1]) + first] * first_repeats
    for i in range(1, nframes):
        st = 2 if i == nframes - 1 else 1
        recs.append(bytes([ftype, st, 0]) + rng.integers(0, 256, PAYLOAD, dtype=np.uint8).tobytes())
    recs += [bytes([ftype, 2, 1]) + recs[-1][3:]] * last_repeats
    return b"".join(recs)


def payload_set(frames_path):
    return {h for _, (_, h) in read_frames(frames_path).items()}


def cmd_speeds(work, seconds=6.0):
    """Both directions at every speed: HSmodem's own transmitter (hsh tx at
    that mode, its sound-card audio) into NB's receiver (hsdev ssbrx:
    resampled to 12 kHz, Receiver::ssb, AFC on), and NB's transmitter
    (hsdev ssbtx: 12 kHz SSB audio, resampled to the mode's sound-card
    rate) into HSmodem's own receiver (hsh rx at that mode). Clean, then
    with noise and a mistuning HSmodem's own receiver has no AFC for."""
    print("mode  bit/s  frames  HSmodem->NB clean / noisy+offset   NB->HSmodem clean / noisy   Pack() same")
    for m, (rate, k, bits, bps) in enumerate(SR):
        rs = rate / k
        rng = np.random.default_rng(300 + m)
        n = int(seconds * bps / 8 / 258) + 2
        sp = transfer_spec(rng, n)
        want = {bytes(sp[i + 3:i + 222]).hex() for i in range(0, len(sp), 222)}
        open(f"{work}/c_spec.bin", "wb").write(sp)
        env = {**os.environ, "HSH_SPEED": str(m)}
        run([os.path.join(work, "hsh"), "tx", f"{work}/c_spec.bin", f"{work}/c_hf.bin", f"{work}/c_ha.f32"],
            cwd=work, env=env)
        a0 = np.fromfile(f"{work}/c_ha.f32", np.float32)
        snr = {1: 10, 2: 13, 3: 19}[bits]
        res = []
        # "Clean" is Es/N0 60 dB rather than no noise at all, as through
        # any radio. (Found on the way: NB's signal with 200 symbols of
        # digital silence in front reached HSmodem's receiver clean and it
        # locked only after its 5 s watchdog reset - frames from symbol
        # 12615 instead of 1062 at mode 4; with any noise, or with no
        # lead-in, at once. NB sends no lead-in; HSmodem sends none either.)
        for tag, a in (("clean", add_noise(a0, 60, np.random.default_rng(900 + m), bw=rs, fs=rate)), ("noisy", add_noise(shift_real(a0, 0.3 * rs / {1: 2, 2: 4, 3: 7}[bits], rate), snr,
                                                       np.random.default_rng(m), bw=rs, fs=rate))):
            a.astype(np.float32).tofile(f"{work}/c_in.f32")
            run([HSDEV, "ssbrx", f"{work}/c_in.f32", str(rate), str(m), f"{work}/c_rfr.txt"])
            got = payload_set(f"{work}/c_rfr.txt")
            res.append(f"{len(got & want)}/{len(want)}{'' if got <= want else ' +junk'}")
        run([HSDEV, "ssbtx", f"{work}/c_spec.bin", str(m), f"{work}/c_rf.bin", f"{work}/c_ra.f32", str(rate)])
        same_pack = open(f"{work}/c_hf.bin", "rb").read() == open(f"{work}/c_rf.bin", "rb").read()
        b0 = np.fromfile(f"{work}/c_ra.f32", np.float32)
        for tag, b in (("clean", add_noise(b0, 60, np.random.default_rng(950 + m), bw=rs, fs=rate)), ("noisy", add_noise(b0, snr + 3, np.random.default_rng(50 + m), bw=rs,
                                                          fs=rate))):
            b.astype(np.float32).tofile(f"{work}/c_in.f32")
            run([os.path.join(work, "hsh"), "rx", f"{work}/c_in.f32", f"{work}/c_hs.f32", f"{work}/c_hfr.txt"],
                cwd=work, env=env)
            got = payload_set(f"{work}/c_hfr.txt")
            res.append(f"{len(got & want)}/{len(want)}{'' if got <= want else ' +junk'}")
        print(f"{m:4d}  {bps:5d}  {len(sp) // 222:6d}  {res[0]:>9} / {res[1]:<20}  {res[2]:>9} / {res[3]:<12}  "
              f"{same_pack}")
    print("clean: Es/N0 60 dB; noisy: Es/N0 10 (BPSK), 13 (QPSK), 19 (8APSK) dB, HSmodem's signal 0.3 of NB's AFC span off tune "
          "(HSmodem's receiver has no AFC, so NB's signal reaches it on tune, 3 dB stronger)")


def cmd_corpus4(work, outdir):
    """Speed mode 4 (QPSK, 4410 bit/s, 44.1 kHz audio - HSmodem's "QO-100
    Standard" and NB's default): HSmodem's own sound-card audio for a short
    file transfer (int16, gzipped) and the payloads it carried, so
    tests/hsmodem.rs can hold NB's receive path against HSmodem's
    transmitter on every cargo test."""
    import gzip
    outdir = os.path.abspath(outdir)
    rng = np.random.default_rng(404)
    # Kept short (2.3 s, ~200 kB): the first frame twice, as a preamble,
    # and the last twice (a receiver needs the filter delay past a frame).
    sp = transfer_spec(rng, 3, first_repeats=1, last_repeats=1)
    open(f"{work}/c_spec.bin", "wb").write(sp)
    run([os.path.join(work, "hsh"), "tx", f"{work}/c_spec.bin", f"{work}/c_hf.bin", f"{work}/c_ha.f32"],
        cwd=work, env={**os.environ, "HSH_SPEED": "4"})
    a = np.fromfile(f"{work}/c_ha.f32", np.float32)
    scale = 16000.0 / float(np.abs(a).max())
    q = np.round(a * scale).astype(np.int16)
    with gzip.open(os.path.join(outdir, "speed4-audio-44100.s16.gz"), "wb", compresslevel=9) as f:
        f.write(q.tobytes())
    payloads = sorted({bytes(sp[i + 3:i + 222]).hex() for i in range(0, len(sp), 222)})
    with open(os.path.join(outdir, "speed4-payloads.txt"), "w") as f:
        f.write("\n".join(payloads) + "\n")
    # HSmodem's own receiver on the quantised audio: the frames it found.
    (q.astype(np.float32) / np.float32(scale)).tofile(f"{work}/c_in.f32")
    run([os.path.join(work, "hsh"), "rx", f"{work}/c_in.f32", f"{work}/c_hs.f32", f"{work}/c_hfr.txt"],
        cwd=work, env={**os.environ, "HSH_SPEED": "4"})
    print("corpus4:", len(q) / 44100, "s,", len(payloads), "payloads; HSmodem's receiver found",
          len(payload_set(f"{work}/c_hfr.txt")))


def cmd_corpus(work, outdir):
    """A compact corpus for tests/hsmodem_corpus.rs: IQ made from HSmodem's
    own transmitter (int16, gzipped), what HSmodem's receiver did with it
    (hard symbols, frames), and HSmodem's frames for a set of specs."""
    import gzip
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    a0, _ = beacon_audio(work, 4.0, 44)
    rng = np.random.default_rng(5)
    a = add_noise(shift_real(a0, 2.0), 16, rng)
    iq = audio_to_iq(a)
    scale = 16000.0 / float(np.abs(np.concatenate([iq.real, iq.imag])).max())
    q = np.empty(2 * len(iq), np.int16)
    q[0::2] = np.round(iq.real * scale)
    q[1::2] = np.round(iq.imag * scale)
    with gzip.open(os.path.join(outdir, "beacon-iq-9600.s16.gz"), "wb", compresslevel=9) as f:
        f.write(q.tobytes())
    with open(os.path.join(outdir, "beacon-iq-9600.scale"), "w") as f:
        f.write(f"{scale!r}\n")
    # HSmodem's receiver on exactly those (quantised) samples.
    (q.astype(np.float32) / np.float32(scale)).view(np.complex64).tofile(f"{work}/c_in.c64")
    run([os.path.join(work, "hsh"), "rxiq", f"{work}/c_in.c64", f"{work}/c_hs.f32", f"{work}/c_hfr.txt"], cwd=work)
    h = read_stages(f"{work}/c_hs.f32")
    with gzip.open(os.path.join(outdir, "beacon-iq-9600.hsmodem-symbols.gz"), "wb", compresslevel=9) as f:
        f.write(h[:, 2].astype(np.uint8).tobytes())
    with open(os.path.join(outdir, "beacon-iq-9600.hsmodem-frames.txt"), "w") as f:
        f.write(open(f"{work}/c_hfr.txt").read())
    # Pack() on a spec: frames byte for byte.
    rng = np.random.default_rng(9)
    sp = spec(rng, nfiles=2, ext=3)
    open(os.path.join(outdir, "pack.spec"), "wb").write(sp)
    open(f"{work}/c_spec.bin", "wb").write(sp)
    run([os.path.join(work, "hsh_ams"), "tx", f"{work}/c_spec.bin", os.path.join(outdir, "pack.frames"),
         f"{work}/c_hp.c64"], cwd=work)
    print("corpus in", outdir, sorted(os.listdir(outdir)), "scale", scale)


def main():
    work = os.path.abspath(sys.argv[1])
    what = sys.argv[2]
    build_hsdev()
    if what == "frames":
        cmd_frames(work, *map(int, sys.argv[3:4]))
    elif what == "rs":
        cmd_rs(work, *map(int, sys.argv[3:4]))
    elif what == "stages":
        cmd_stages(work, *map(float, sys.argv[3:4]))
    elif what == "iq":
        cmd_iq(work, *map(float, sys.argv[3:4]))
    elif what == "corpus":
        cmd_corpus(work, sys.argv[3])
    elif what == "speeds":
        cmd_speeds(work, *map(float, sys.argv[3:4]))
    elif what == "corpus4":
        cmd_corpus4(work, sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
