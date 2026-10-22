"""The instrument UI both apps are built from: theme, hand-painted
controls, meters, the scope's waterfall core, the bridge between window and
engine, window preferences. Each app's own window composes these
(ohsnb/ui/ for QO-100 NB).

Like the rest of ohscore, nothing here imports an app; what is particular to
one (its shortcut list, its status-strip items, its state registry through
the engine) is passed in. Importing the package has no side effects.
"""
