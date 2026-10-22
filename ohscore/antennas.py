"""Antenna labels: the operator's own name for each input a receiver
reports ("Antenna C" -> "80 m dipole"), shown beside the driver's bare
name everywhere one is named - the Settings drop-down, the status line,
and the API.

Stored in one setting, `soapyAntennaLabels`, because an app setting
reaches a store container one variable per line (GUIDE.md "Apps"): a
label containing a line break would corrupt that line and the one after
it, so the value kept on disk is always a single line. JSON is used
rather than a hand-rolled comma/equals grammar because `json.dumps`
already escapes a newline, a comma or an "=" inside a label (and reads
them back) without this module inventing and testing its own escaping -
the one thing it must still guard is a stored value that is not valid
JSON, or not a flat object of strings, which `parse_labels` treats as no
labels rather than raising into Settings or the API.
"""
from __future__ import annotations

import json


def parse_labels(raw: str) -> dict[str, str]:
    """The labels `format_labels` wrote, or {} for empty, corrupt JSON, or
    anything that is not a flat string-to-string object - a damaged
    setting (hand-edited, or from an older format) loses its labels
    rather than breaking the page that reads it."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def format_labels(labels: dict[str, str]) -> str:
    """The single-line form stored in `soapyAntennaLabels`. `ensure_ascii`
    is off so a non-ASCII label (a Cyrillic or accented name) is kept
    readable rather than escaped, and the line still has no line break of
    its own since json.dumps escapes one inside a string. An empty label
    is dropped, so clearing one in the table removes it rather than
    saving ""; an empty result is the empty string, not "{}", to match
    the setting's own default."""
    clean = {k: v for k, v in labels.items() if v}
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":")) if clean else ""


def display_name(antenna: str, labels: dict[str, str]) -> str:
    """"Antenna C", or "Antenna C — 80 m dipole" where a label is set."""
    label = labels.get(antenna, "")
    return f"{antenna} — {label}" if label else antenna
