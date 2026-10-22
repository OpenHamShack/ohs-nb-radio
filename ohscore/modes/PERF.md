# Mode decoder performance

Measured on this host (x86_64, AMD Ryzen 9 6900HX, one core -- every
decoder here is single-threaded Python/numpy) by feeding each decoder a
realistic message through its `feed()` in 100 ms (1200-sample) blocks, the
same block size the real RX thread hands modes, and timing wall-clock
decode against the audio's own duration:

RTF = (seconds of audio) / (seconds spent decoding it)

An RTF above 1x means the decoder keeps up in real time with room to
spare; below 1x means it falls behind. A Raspberry Pi 400 is roughly
4-6x slower per core than this host for ordinary numpy-bound work, so the
"Pi 400 (est., /6)" column is the measured figure divided by 6 -- the
pessimistic end of that range, not a measurement on the actual hardware.

| mode | measured RTF | Pi 400 (est., /6) | notes |
| --- | --- | --- | --- |
| CW | 2835x | 472x | Goertzel per 5 ms frame + a run-length walk; trivial cost |
| RTTY | 3590x | 598x | two Goertzels per quarter-bit, each bit read from two of them, a squelch per candidate frame; still the cheapest mode here |
| PSK31 | 197x | 33x | matched/zero-forcing FIR (6 symbols long) evaluated only at the decimated outputs, coarse FFT AFC every 8 symbols, per-symbol timing and fine AFC. Ten times the cost of the integrate-and-dump it replaced, which could not copy a signal in modest noise |
| PSK63/125 | 138x / 85x | 23x / 14x | same machinery; the Python loop runs per symbol, so faster modes cost more |
| FreeDV 1600 | 174x | 29x | codec2's own C cost dominates, not the resampler |
| FreeDV 700D | 229x | 38x | likewise; 700D's LDPC is costlier per frame than 1600's but still fine |
| SSTV (Robot36) | 320x | 53x | the short FIR demod, a 1200 Hz matched detector around each sync, pixel means from one cumulative sum (the per-pixel Python loop that cost the old 65x is gone); 3.3 samples/pixel |
| SSTV (Martin M1) | 550x | 92x | slower scan (5.5 samples/pixel), cheaper per second of audio |
| SSTV (Scottie S1) | 550x | 92x | similar scan rate to Martin M1 |
| SSTV (PD120) | 410x | 68x | 640 px wide at 2.3 samples/pixel |
| FT8 (one 15 s slot) | 24.8x | 4.1x | **not this module's own cost** -- this is jt9's wall time (WAV write + decode), run on its own worker thread so it never blocks the RX thread regardless |
| FT4 (one 7.5 s slot) | 25.5x | 4.2x | same caveat as FT8 |

Caveats worth keeping in mind rather than just trusting the table:

- The FT8/FT4 figures time an external binary (`jt9`), not Python/numpy --
  the x86-to-Pi ratio for a separately-compiled, FFTW-using C++ program
  doesn't necessarily track this host's numpy slowdown factor the way the
  other rows do. It is however the one mode DESIGN.md already requires to
  run off the RX thread on its own worker, specifically because a whole
  slot's decode is expected to take over a second -- so even if a Pi's jt9
  turns out slower than this estimate, it costs latency before the next
  slot's result, not a dropped sample on the live RX/TX path.
- Every other row *is* this module's own code and does sit on data arriving
  continuously from the RX thread, so those margins are the ones that
  matter for "never falls behind." All are comfortably above 1x even at
  the pessimistic /6 estimate. The narrowest is now PSK125 (14x): its
  Python loop runs once per symbol, 125 times a second. SSTV's PD120 held
  that place (9x) until its per-pixel Python loop was replaced by one
  cumulative sum per line.
- These are single-message measurements on an otherwise idle core, not a
  worst case with several modes or several browsers' audio streams
  running at once; DESIGN.md's RX thread runs every consumer on every
  block, so real headroom on a Pi 400 is this table's numbers for
  whichever modes are actually active simultaneously, not a guarantee
  that running all of them at once still clears 1x by the same margin.
