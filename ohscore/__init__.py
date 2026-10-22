"""ohscore: the radio engine, DSP, modes, devices and instrument UI that
QO-100 NB (ohsnb) and OpenHamShack Radio (ohsradio) share.

The one rule that keeps a shared core honest: nothing here imports ohsnb or
ohsradio. Anything that knows about QO-100 (beacons, the transponder, the
uplink) or about a terrestrial licence belongs to its app and reaches the
core as data or a hook the app supplies. tests/test_core_isolation.py
enforces this by importing every module here with both apps made
unimportable.

ohscore has no version and is not published on its own: each app's package
carries a private copy, cut from the same commit as the app
(docs/ham/DESIGN-HAM.md section 2.6).

Like ohsnb/__init__.py, importing the package has no side effects.
"""
