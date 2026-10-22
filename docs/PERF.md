# Engine performance

Measured 2026-10-04 on the development host, **not on a Raspberry Pi**: an
AMD Ryzen 9 6900HX (x86-64), Python 3.13, numpy 2.2.4, Debian 13. Re-measure
on the target with:

```
python3 -m ohsnb.bench                  # 1.2 MS/s
python3 -m ohsnb.bench --rate 600000
```

Figures are CPU time as a fraction of **one core**, per second of signal.

| | 1.2 MS/s | 600 kS/s |
| --- | --- | --- |
| Receive path (wide + zoom scopes at 20 lines/s, VFO channel + SSB demod + AGC, both beacon trackers, TX monitor channel) | **3.1 %** | 2.1 % |
| Beacon search (first second after start, or after losing lock) | ~6.7 % | — |
| Transmit path while keyed (SSB modulator + upconversion to fs) | 1.3 % | 0.9 % |
| TX monitor estimate while keyed (once a second) | 3.3 ms per estimate (~0.3 %) | — |
| Simulator generating the band | 4.1 % | 2.8 % |
| Whole process, real-time headless run on the simulator, all threads, a "UI" draining every feed at 30 Hz | **7.8 %** | 6.5 % |
| Whole process keyed on SSB with TX lock running (simulator, faster than real time) | 12.8 % | — |
| Simulator start-up (building the station templates) | 1.1 s | |

## What that means for a Pi 400

**Unverified estimate.** A Cortex-A72 at 1.8 GHz runs numpy's FFT-heavy code
roughly 6-10x slower per core than this host. On that basis, at 1.2 MS/s:

- receive path ~20-30 % of one core;
- with the simulator as the device, the whole engine ~50-80 % of one core;
- with a Pluto instead of the simulator, add the libiio transfer and int16
  conversion and subtract the simulator: probably ~30-40 % of one core;
- simulator start-up ~5-10 s (once, at start).

The Pi 400 has four cores and the engine's threads are mostly independent
(receive, transmit, decode, supervisor; numpy releases the GIL inside FFTs),
so this leaves room for the Qt UI and for jt9. If the Pi is short, 600 kS/s
cuts receive by about a third; the cost is that the top of the passband is
then near the edge of the SDR's filter, and transmit cannot reach
2400.210-2400.290 MHz without the LO in the passband (radio.plan_tx_lo).

## Where the time goes (receive, 1.2 MS/s)

From cProfile over 15 s of tracking, measured just before 0b4633c, which
then cut the channel-extraction share (receive total 3.7 % -> 3.1 %):

- **31 %** the filter bank's forward FFT (one 24 000-point complex FFT per
  15 ms frame - the one unavoidable full-rate operation);
- **24 %** channel extraction (five channels: slicing bins, small inverse
  FFTs, phase correction). Before the fix in 0b4633c, more than half of this
  was complex exponentials computed per output sample; now one per frame;
- **16 %** the scopes (windowed FFTs, 20 lines/s each, 2 averages);
- **12 %** TX monitor spectra (10 per second, 20 000 points) - kept running
  unkeyed so its baseline is ready before you key;
- **10 %** demod + AGC; the rest beacon tracking.

There are no per-sample Python loops on the RX or TX paths. Python-level
loops exist only per frame (66 per second), per channel and per scope line.

## Design choices made for speed

- One forward FFT serves every channel (overlap-save filter bank,
  `ohscore/dsp/bank.py`); decimation is free and channel filters are 6001 taps
  at no extra cost. The same bank, inverted, is the transmitter's and the
  simulator's upconverter.
- The AGC, speech compressor and ALC are vectorised over 2.5 ms chunks with a
  sliding max + cumulative max - no loop over chunks or samples.
- The simulator replays precomputed 12 kHz station loops and draws noise
  from a bank of pre-shaped spectra; FT8 slots are rendered a slot ahead on a
  worker thread.
- Audio callbacks only copy; resampling is on the engine side of the rings.

## Receive noise reduction (NR2)

`ohscore/dsp/nr.py` (WDSP's EMNR, ported) runs only while it is switched
on in a mode it applies to; off, it is an exact bypass and costs nothing.
Measured 2026-10-05 on the development host (Ryzen 9 6900HX, numpy 2.2.4,
load average ~6 from other sessions) by `tests/test_nr.py`'s
`Cost.test_time_per_block`, the median over 16 blocks of the engine's own
75 ms / 900-sample audio block:

| | per 75 ms block | of one core |
| --- | --- | --- |
| NR on (12 kHz audio, 720-point frames, 4x overlap: 5 frames a block) | **1.1-1.3 ms** | **1.4-1.7 %** |

Where it goes (cProfile): about 40 % WDSP's two table lookups per frame, 30 % the
minimum-statistics noise estimate, the rest the transforms and the
overlap-add. All of it is a few dozen numpy calls per frame on 361 bins,
so the cost is mostly numpy's per-call overhead rather than arithmetic -
which is the part a slower CPU slows most.

**On a Pi - unverified estimate**, at the 6-10x this page uses for a
Cortex-A72: 7-13 ms per block, **~10-17 % of one Pi 400 core** while NR is
on, and about half that on a Pi 500. It runs on the receive thread, so it
adds to the receive path's 20-30 % (above), still well inside one core.
The test fails only above 11 ms per block on the development host - a
gross regression (a per-sample loop, an FFT length numpy cannot factor),
not a busy machine. Re-measure on the Pi with
`python3 -m unittest discover -s tests -p test_nr.py -k time_per_block`.

## A Pluto whose firmware refuses the FIR

Some firmware will not load the AD9361's x4 FIR (seen on a Nano PlutoSDR,
Tezuka `tezuka-v0.3.21`), so the radio cannot run below 2.083 MS/s. The
Pluto device then runs it at 2.4 MS/s and converts in software
(`ohscore/dsp/multirate.py`; DESIGN.md "Devices"). That conversion is the one
thing in the program that works at more than the engine's rate, so it is
measured on its own by `python3 -m ohsnb.bench` (last line).

Measured 2026-10-04 with the bench on the laptop the nano is plugged into,
an Intel i5-1135G7 (x86-64, `powersave` governor), numpy 2.2.4, 10 s runs,
two runs agreeing to 0.1 %:

| | 1.2 MS/s (M = 2) | 600 kS/s (M = 4) |
| --- | --- | --- |
| Receive: int16 conversion + decimating 2.4 MS/s | **2.8 %** | 2.5 % |
| ... of which the int16 conversion at 2.4 MS/s | 1.0 % | 1.0 % |
| Transmit while keyed: interpolating to 2.4 MS/s + int16 conversion | **2.9 %** | 2.4 % |
| For scale, the engine's receive path on the same machine | 4.3 % | |

So on this firmware the receive thread does about 1.6x the work it does
with a Pluto that loads the FIR (whose own int16 conversion, at 1.2 MS/s,
is ~0.5 %). On the development host (Ryzen 9 6900HX) the same code measured
3.5 % / 2.1 % receive, but that host was carrying a load average of ~29 from
other work at the time, so the laptop's figures are the ones to trust.

The same receive path ran on the real nano for 8 s over USB (ip:192.168.2.1)
with the whole process, libiio included, at 9.6 % of one laptop core,
delivering 1 199 915 S/s of a nominal 1 200 000 - real time; and the
headless engine ran on it for 10 s at 1.2 MS/s and 5 s at 600 kS/s with its
own CPU meter at 6-8 %.

**On a Pi - unverified estimate.** At the 6-10x the section above assumes
for a Cortex-A72, the rate change adds roughly 15-30 % of one core on
receive, and as much again while keyed: receive thread ~35-60 % of one
core in all at 1.2 MS/s. That fits in a Pi 400's four cores but is the
largest single cost on this firmware; 600 kS/s saves little here, because
the radio still runs at 2.4 MS/s. A Pi 500 (Cortex-A76) should need about
half that. Re-measure with `python3 -m ohsnb.bench` on the Pi.

Why it is not cheaper: the forward FFT of the 2.4 MS/s stream is the
floor (about half of the decimation, by a per-step profile on the
development host); the decimator folds the spectrum before its inverse FFT
so the inverse runs at the low rate, and the interpolator's forward FFT
runs at the low rate. A direct polyphase form was not built: it would be
one numpy pass over the block per tap (73 taps at M = 2, 145 at M = 4),
against the FFT form's two transforms.
numpy 2.2's complex64 FFT is ~5x slower unscaled than with `norm="forward"`
- the filters use the scaled form; the engine's own filter bank
(`ohscore/dsp/bank.py`) does not yet, and may be worth the same change.

## The multimedia beacon receiver

Measured 2026-10-06 on the development host (Ryzen 9 6900HX, numpy 2.2.4,
load average under 1), the simulator in real time at 1.2 MS/s with its full
band, 40 s after a 3 s settle, two runs each way:

| | of one core |
| --- | --- |
| Whole process, beacon receiver off (`mmbDecode` false) | 9.3 / 9.6 % |
| Whole process, beacon receiver on | 10.1 / 10.2 % |
| ... of which its worker thread (ohsdigi's HSmodem receiver in Rust, the content layer in Python) | 0.6 % |
| ... and on the receive thread, its channel off the shared spectrum | within the receive thread's 4.2-4.4 %, not separable |

ohsdigi alone, offline: 23 s of 12 kHz IQ (resampling to 9600 S/s, AFC,
tracker, deframing) in 0.065 s, 0.3 % of one core. The rest of the worker's
0.6 % is Python: the content layer and the status updates.

**On a Pi - unverified estimate.** The Rust part does per-sample work and
should slow about as much as compiled code does on a Cortex-A72 (3-5x);
the Python part like numpy's (6-10x): roughly 3-6 % of one Pi 400 core in
all, on a thread of its own. `mmbDecode` turns it off; the worker reports
its own share as the `mmbCpu` status key, so a Pi measures itself.

## The scopes on a scaled screen

Seen 07/10 on the test laptop (i5-1135G7, `powersave`, KDE Wayland at
**105 %**), NB 0.1.7 on a LibreSDR at 1.2 MS/s: ~1.2 receive overruns and
~0.3 audio underruns a second, the status bar's engine figure at 41 %, and
the GUI thread at ~80 % of a core - where Ray's Windows machine at 100 %
showed no overruns at 12 %.

The cause, by py-spy (`--gil` too) on the running program: the GUI thread
held the GIL ~65 % of the time, almost all of it inside the scopes' two
`drawPolyline` calls (trace and peak ghost). Qt's raster engine takes its
fast antialiased-line path only for a pen at most one *device* pixel wide;
a 1 px pen on a 1.05 screen is 1.05 device pixels and goes to the general
stroker, ~50x slower on a noisy spectrum. PyQt keeps the GIL through the
call, so the receive thread waited: the engine's "cpu" is the receive
block's wall time, and it was inflated by that wait, not by DSP. The pens
are now cosmetic hairlines, widened by drawing again a device pixel over
(`ohscore/ui/scopelook.py` `_hairline`, `trace_passes`). At 100 % - a Pi on
an ordinary monitor - the pixels and the cost are exactly as before.

Measured on the laptop with the simulator in real time at 1.2 MS/s, the
live config (wide 2048 bins at 20 fps, zoom 1024, `mmbDecode` on), the
window 1417 px wide, two minutes each, alongside the real NB still running:

| | before | after |
| --- | --- | --- |
| Wide scope paint | 27 ms | 3.5 ms |
| Zoom scope paint | 6 ms | 1.7 ms |
| GUI thread (`top -H`) | 71 % | 17.5 % |
| GUI thread holding the GIL (py-spy `--gil`) | 69 % of samples | 11 % |
| Receive thread (`top -H`) | 18 % | 16 % |
| Engine "cpu" (receive block wall time) | 19-30 % | 7.3-8.8 % |
| Receive overruns / audio underruns in 2 min | 6 / 3 | 0 / 0 |

On a scaled screen, a renderer that strokes slowly costs receive too, for
as long as Python's GIL is shared by the window and the engine:
`tests/test_ui_scope.py` `ScaledScreen` fails if a 105 % paint costs more
than about twice a 100 % one.

## The band skimmer

`ohsnb/skimmer.py` (the work: `ohsnb/dsp/skim.py`). Its cost is a budget,
`skimBudget` per cent of one core (10 % by default): the worker charges the
CPU it uses against the signal it has heard, and a look at a voice - the
only costly part - starts only while the account is in credit. A slower
machine gets fewer looks a minute, not a slower receiver; the skimmer
reports its own share as `skimCpu` and its looks as `skimLooks`, so a Pi
measures itself.

Where the time goes, development host (Ryzen 9 6900HX, numpy 2.2.4 with
Debian's **reference BLAS**):

| | cost |
| --- | --- |
| Band spectrum (10 000 of the bank's bins a frame, Hann in the frequency domain, a line a second, floor, runs, tracks) | ~1.3 % of one core |
| A voice look: auto-tune's first look (`autotune.Listener`, 4 s) on a 12 kHz channel cut from the same spectra | **~0.4-0.5 s** of one core per look, almost all auto-tune's comb (`_comb_frames`: a frames x bins x 640-F0 matrix product) |
| A narrow look (2 s at 4 kHz: keying, line) | a few ms |

The comb's matrix product runs at ~2 GFLOP/s because Debian's `python3-numpy`
uses the reference BLAS unless an optimised one is installed
(`libopenblas0` provides the alternative); a pip/PyInstaller numpy with
OpenBLAS does the same product many times faster. Untested here: with it,
the same budget would buy many more looks.

Measured 2026-10-08 on the development host - **busy: load average 22-30
from other sessions**, so the absolute figures are high - the simulator in
real time at 1.2 MS/s with its full band, a "UI" draining every feed at
30 Hz, 40 s after a 5 s settle:

| | whole process, of one core | `skimCpu` | looks a minute | receive-thread `cpu` | blocks dropped |
| --- | --- | --- | --- | --- | --- |
| skimmer off | 14.3 % | - | - | 5.7 % | - |
| on, budget 5 % | 21.7 % | 7.9 % | 11 | 5.3 % | 0 |
| on, budget 10 % (default) | 28.4 % | 12.4 % | 16 | 5.9 % | 0 |

The receive thread's own figure did not move: the skimmer's work is on its
own thread, and only a reference to each block's spectra crosses. Over a
40 s window `skimCpu` runs over the budget by the look in progress (a look
starts in credit and is paid for after); over the 3-hour recording run
offline at 5 % and 10 % (tools/skimmer_eval.py) the means were 4.8 % and
8.1 %, with 7 and 16 looks a minute.

**On a Pi - unverified estimate.** At the 6-10x this page uses for a
Cortex-A72, a voice look costs 3-5 s of a core; at the default 10 % budget
that is one or two voice looks a minute, so dials are measured slowly but
the list and its names (spectrum, narrow looks: under 1 % of a core here)
keep up. The budget, not the machine, sets the cost.
