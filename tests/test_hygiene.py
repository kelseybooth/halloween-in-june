"""Tripwires for things a reader cannot see.

Most bad code is visible: you read it, and it is wrong. This file is for the
other kind - bytes that render as nothing, or as something else, so that the
line looks correct in an editor, in a terminal and in a diff.

The one that prompted it: `test_scenery.py` guarded against the channel prose
spending the house reveal early, and the regex it searched with had two
literal backspace characters (0x08) where `\\b` word boundaries were meant.
No prose contains a backspace, so the search matched nothing, the assertion
was `assert not ...`, and the check passed on an empty result for as long as
it existed. It was read and reviewed; a terminal prints those bytes
invisibly, so there was nothing on the screen to notice.
"""

from pathlib import Path

# Tab, newline and carriage return are the three that belong in a text file.
# Everything else below 0x20 arrives by accident - a paste, an editor, an
# escape that was meant to reach the regex engine as two characters and
# reached it as one.
ALLOWED = {0x09, 0x0A, 0x0D}

# Checked out worktrees live under `.claude`, and each is a whole second copy
# of the repo. Scanning them doubles the work and reports another branch's
# problems as this one's.
SKIP_DIRS = {
    ".git",
    ".venv",
    ".claude",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}

TEXT_SUFFIXES = {
    ".py", ".tsv", ".csv", ".md", ".json",
    ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini", ".sh",
}

REPO = Path(__file__).resolve().parents[1]


def text_files():
    for path in REPO.rglob("*"):
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(REPO).parts):
            continue
        yield path


def test_no_stray_control_characters():
    """Every text file in the repo, content and code alike.

    Reported by line and by code point, because the whole difficulty is that
    the offending line looks fine when printed - the failure has to say where
    it is and what is in it rather than showing it.
    """
    problems = []
    for path in text_files():
        raw = path.read_bytes()
        if not any(b < 0x20 and b not in ALLOWED for b in raw):
            continue
        relative = path.relative_to(REPO).as_posix()
        for number, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
            found = sorted({c for c in line if ord(c) < 0x20 and ord(c) not in ALLOWED})
            if found:
                codes = ", ".join(f"0x{ord(c):02x}" for c in found)
                problems.append(f"{relative}:{number} contains {codes}")

    assert not problems, "stray control characters:\n  " + "\n  ".join(problems)


def test_the_scan_reaches_the_file_that_prompted_it():
    """A guard on the guard. A scanner whose walk silently matches nothing
    passes for the same reason the backspace regex did, and this file would
    then be decoration.
    """
    scanned = {path.relative_to(REPO).as_posix() for path in text_files()}

    assert "tests/test_scenery.py" in scanned
    assert "creative content/things.tsv" in scanned
    assert len(scanned) > 50
