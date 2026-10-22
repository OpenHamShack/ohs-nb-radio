"""Entry point PyInstaller freezes into openhamshack-radio.exe and
openhamshack-radio-console.exe - the same `python -m ohsradio` main(), so the Windows
build takes exactly the command-line options the .deb's launcher does."""
import sys

from ohsradio.__main__ import main

if __name__ == "__main__":
    # First, before anything else runs: the CW skimmer's worker process is
    # this .exe started again by multiprocessing (spawn), and freeze_support
    # makes that run the worker and exit instead of opening a second Radio
    # (ohsradio/cwskim.py; --cw-skim-selftest proves it in the build).
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
