"""Entry point PyInstaller freezes into openhamshack-nb.exe and
openhamshack-nb-console.exe - the same `python -m ohsnb` main(), so the Windows
build takes exactly the command-line options the .deb's launcher does.
The macOS build (packaging/macos/openhamshack-nb.spec) freezes this same file.

freeze_support() first: `--analyse --jobs N` (ohsnb/analyse_parallel.py)
starts its workers with multiprocessing's "spawn", which in a frozen app
re-runs this executable with multiprocessing's own arguments. Without
the call each worker would start a second copy of OpenHamShack QO-100 NB instead of
a worker, and the analysis would never finish. It goes before the app's
own import so a worker does not load the radio's modules only to throw
them away."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from ohsnb.__main__ import main
    sys.exit(main())
