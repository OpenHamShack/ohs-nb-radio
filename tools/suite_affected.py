#!/usr/bin/env python3
"""The test modules near what changed since <base>: tools/suite-affected.sh's
list (that script's header says when to use it).

    python3 tools/suite_affected.py <base>      one module per line, then
                                                "# " lines saying what found nothing

Changed means the commits since the merge base with <base>, plus whatever
is uncommitted or untracked in the worktree now. A test module is near a
changed file when:

- it is the file (tests/test_*.py);
- its name has the changed module's name in it as whole words, or the
  name of the package folder it sits in below the top level (ohsradio/
  ais.py: test_ham_ais; ohscore/server/app.py: every test_server_*);
- it imports the changed module, or anything inside a changed package
  (`import ohscore.engine`, `from ohscore import engine`, `from
  ohscore.engine import Engine`), read with ast, so a comment naming it
  does not count;
- for anything that is not Python (a tool script, a data file), its text
  names the file (test_store_release runs tools/store-release.sh); a
  helper beside the tests (scratch_home.py) likewise.

Only direct importers: a test that reaches the module through another
(most of Radio's import ohsradio.radio, which imports nearly everything)
is the full run's to catch, at release. The point is a quick check before
a merge, not a proof; when in doubt a rule here takes more, not fewer.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# Names too common to pick tests by: every test would match.
GENERIC = {"__init__", "__main__", "test", "tests", "helpers", "util", "utils"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed(base: str) -> list[str]:
    files = set(git("diff", "--name-only", f"{base}...HEAD").split())
    files |= set(git("diff", "--name-only", "HEAD").split())
    files |= set(git("ls-files", "--others", "--exclude-standard").split())
    return sorted(files)


def imports(path: Path) -> set[str]:
    """Every module name a file imports, and for `from a import b` both a
    and a.b (b may be a module or a name in a; either way a test of a)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def module_name(path: str) -> str | None:
    """ohscore/server/app.py -> ohscore.server.app; a package's __init__ is
    the package. None for a file that is not in an importable package
    (tools/, tests/)."""
    p = Path(path)
    if p.suffix != ".py" or p.parts[0] in ("tests", "tools"):
        return None
    parts = list(p.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or None


def affected(base: str, root: Path) -> tuple[list[str], list[str]]:
    tests = sorted((root / "tests").glob("test_*.py"))
    names = {t.stem: "_" + t.stem[len("test_"):] + "_" for t in tests}
    imported = {t.stem: imports(t) for t in tests}
    texts = {t.stem: t.read_text(encoding="utf-8", errors="replace") for t in tests}
    chosen: set[str] = set()
    nothing: list[str] = []
    for f in changed(base):
        p = Path(f)
        hits: set[str] = set()
        if p.parts[0] == "tests":
            if p.name.startswith("test_") and p.suffix == ".py" and (root / p).exists():
                hits.add(p.stem)
            elif p.suffix == ".py":
                hits |= {t for t in texts if p.stem in imported[t] or p.stem in texts[t]}
            else:                       # fixtures: whoever names the file
                hits |= {t for t in texts if p.name in texts[t]}
        else:
            mod = module_name(f)
            words = {p.stem.replace("-", "_")} | set(p.parts[1:-1])
            words -= GENERIC
            # Whole words only: "ais" picks test_ham_ais, not test_ham_aisle.
            hits |= {t for t, n in names.items() if any(f"_{x}_" in n for x in words)}
            if mod:
                hits |= {t for t, imp in imported.items()
                         if mod in imp or any(i.startswith(mod + ".") for i in imp)}
            else:
                hits |= {t for t in texts if p.name in texts[t]}
        if hits:
            chosen |= hits
        elif p.suffix in (".py", ".sh") or p.parts[0] in ("ohscore", "ohsnb", "ohsradio", "tools"):
            nothing.append(f)
    # Any change can put a forbidden word into the published source, and
    # nothing maps a file to that check by name: beta.17's release found
    # three such lines that every scoped run had passed. So it always runs.
    if chosen or nothing:
        chosen.add("test_source_site")
    return sorted(chosen), nothing


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: suite_affected.py <base>", file=sys.stderr)
        return 2
    root = Path(git("rev-parse", "--show-toplevel").strip())
    try:
        git("rev-parse", "--verify", "-q", argv[0] + "^{commit}")
    except subprocess.CalledProcessError:
        print(f"suite_affected: {argv[0]} is not a commit", file=sys.stderr)
        return 2
    mods, nothing = affected(argv[0], root)
    for m in mods:
        print(m)
    for f in nothing:
        print(f"# no test found near {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
