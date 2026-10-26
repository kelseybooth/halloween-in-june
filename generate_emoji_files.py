"""Build the two craving content files from the writers' emoji catalogue.

`creative content/emoji-catalogue-v18.csv` is the source of truth for which
emoji belongs where. It is a spreadsheet the writers edit directly: 1,927
rows, one per emoji, with a Category and a Type for each. The two TSVs the
game loads are derived from it and must never be edited by hand - a
hand-edit survives exactly until the next export of the catalogue, and then
disappears without anybody noticing which row changed back.

So this script, and `--check` in the pre-push hook and CI, which rebuilds
both files in memory and fails if what is on disk differs. The failure names
the file and the first row that disagrees, because "the TSVs are stale" is
not a thing anybody can act on.

    python generate_emoji_files.py            # write both files
    python generate_emoji_files.py --check    # fail if they are stale

**What is derived and what is not.** Category, Type and Game Exclusion are
copied straight across. `drawable` is computed here, because the catalogue
has no column for it. Everything else about a row belongs to the writers.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

CONTENT = Path(__file__).parent / "creative content"
CATALOGUE = CONTENT / "emoji-catalogue-v18.csv"
GROUPS = CONTENT / "emoji_groups.tsv"
REACTIONS = CONTENT / "craving_reactions.tsv"

# The two categories today's craving can be drawn from. Adjacent and Toy are
# real game categories - they earn a 😼 - but the cat never wants a mug.
CRAVABLE = ("Food", "Prey")

# Unicode marks an emoji new in the current release by prefixing its CLDR
# short name with this. Discord's picker lags the standard by months, so a
# craving nobody can type is unwinnable - and a player who cannot produce the
# answer has no way to tell that from being wrong.
#
# **Derived rather than listed.** Writing out the two that are new in 18.0
# would be correct today and silently wrong the week Discord ships 19.0 and
# the writers paste in a fresh catalogue.
NEW_IN_THIS_UNICODE = "\N{CIRCLED ASTERISK OPERATOR}"

GROUP_COLUMNS = ("emoji", "code", "name", "category", "type", "drawable", "excluded")
REACTION_COLUMNS = ("outcome", "progression", "emoji", "code", "meaning", "when")

# The catalogue's Type is display text the writers own; the game needs a
# stable key. This is the join between them, and the only place the two
# vocabularies meet. A Bot row whose Type is not in here is an error rather
# than a seventh outcome, because the code has a branch per outcome.
OUTCOME_FOR_TYPE = {
    "Non-Game Category": "greeting",
    "Game Category": "wrong_category",
    "Right Category": "right_category",
    "Right Type": "right_type",
    "Win": "win",
    "Out of Guesses": "out_of_guesses",
}


class Stale(Exception):
    """A generated file on disk does not match what the catalogue says."""


def read_catalogue() -> list[dict[str, str]]:
    # utf-8-sig: the catalogue comes out of a spreadsheet with a BOM, and
    # without this the first column's name is "﻿number" and the lookup
    # below misses with a KeyError nobody can read.
    with io.open(CATALOGUE, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_drawable(row: dict[str, str]) -> bool:
    return row["Category"] in CRAVABLE and not row["CLDR short name"].startswith(
        NEW_IN_THIS_UNICODE
    )


def group_rows(catalogue: list[dict[str, str]]) -> list[tuple[str, ...]]:
    """`emoji_groups.tsv`, in the catalogue's own order.

    The order carries no meaning to the loader, which keys on the emoji. It
    is kept because a diff against the previous export is how a writer checks
    their own change, and a re-sort would make every row look edited.
    """
    return [
        (
            row["emoji"],
            row["code"],
            row["CLDR short name"],
            row["Category"],
            row["Type"],
            yes_no(is_drawable(row)),
            yes_no(row["Game Exclusion"].strip().upper() == "TRUE"),
        )
        for row in catalogue
    ]


def reaction_rows(catalogue: list[dict[str, str]]) -> list[tuple[str, ...]]:
    """`craving_reactions.tsv`: the six emoji the bot answers with.

    Ordered by the ladder rather than by the catalogue, because that is the
    order the file is read in by a person. `out_of_guesses` has no rung - it
    is not a better answer, it is the end of the message - so it sorts last.

    The `when` column is prose, and prose is not in the catalogue. It is
    carried over from the file already on disk, keyed on the outcome. A new
    outcome therefore arrives with an empty sentence rather than a wrong one.
    """
    prose = existing_prose()
    rows = []
    for row in catalogue:
        if row["Category"] != "Bot":
            continue
        outcome = OUTCOME_FOR_TYPE.get(row["Type"])
        if outcome is None:
            raise Stale(
                f"the catalogue has a Bot row typed {row['Type']!r}, which is not "
                f"one of the six outcomes. Add it to OUTCOME_FOR_TYPE and give "
                f"the game a branch for it, or fix the Type."
            )
        rows.append(
            (
                outcome,
                row["Progression"].strip(),
                row["emoji"],
                row["code"],
                row["Type"],
                prose.get(outcome, ""),
            )
        )

    missing = set(OUTCOME_FOR_TYPE.values()) - {row[0] for row in rows}
    if missing:
        raise Stale(
            f"the catalogue has no Bot row for {', '.join(sorted(missing))}. "
            f"Every outcome needs an emoji to answer with."
        )

    # Blank progression sorts after 5 rather than before 1.
    return sorted(rows, key=lambda row: int(row[1]) if row[1] else 99)


def existing_prose() -> dict[str, str]:
    if not REACTIONS.exists():
        return {}
    with io.open(REACTIONS, encoding="utf-8", newline="") as handle:
        return {
            row["outcome"]: row.get("when") or ""
            for row in csv.DictReader(handle, delimiter="\t")
        }


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def render(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """A TSV as the loader reads it: tab separated, CRLF, no quoting.

    Written by hand rather than through `csv.writer` so that a tab or a
    newline inside a cell raises here instead of being quoted into a row the
    loader then splits in the wrong place.
    """
    lines = ["\t".join(columns)]
    for row in rows:
        for cell in row:
            if "\t" in cell or "\n" in cell or "\r" in cell:
                raise Stale(f"cell {cell!r} contains a tab or a newline")
        lines.append("\t".join(row))
    return "\r\n".join(lines) + "\r\n"


def write(path: Path, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def check(path: Path, text: str) -> None:
    if not path.exists():
        raise Stale(f"{path.name} does not exist; run this script without --check")

    with io.open(path, encoding="utf-8", newline="") as handle:
        on_disk = handle.read()
    if on_disk == text:
        return

    want = text.splitlines()
    have = on_disk.splitlines()
    for number, (left, right) in enumerate(zip(want, have), start=1):
        if left != right:
            raise Stale(
                f"{path.name} line {number} does not match the catalogue\n"
                f"  on disk:        {right}\n"
                f"  from catalogue: {left}"
            )
    raise Stale(
        f"{path.name} has {len(have)} lines; the catalogue makes {len(want)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the files on disk are not what the catalogue makes",
    )
    args = parser.parse_args(argv)

    catalogue = read_catalogue()
    work = ((GROUPS, GROUP_COLUMNS, group_rows), (REACTIONS, REACTION_COLUMNS, reaction_rows))

    try:
        built = [(path, render(columns, build(catalogue))) for path, columns, build in work]
    except Stale as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    for path, text in built:
        try:
            check(path, text) if args.check else write(path, text)
        except Stale as problem:
            print(f"error: {problem}", file=sys.stderr)
            print(
                "\nThe emoji TSVs are built from emoji-catalogue-v18.csv.\n"
                "Run: python generate_emoji_files.py",
                file=sys.stderr,
            )
            return 1

    drawable = sum(1 for row in catalogue if is_drawable(row))
    verb = "checked" if args.check else "wrote"
    print(
        f"{verb} {GROUPS.name} ({len(catalogue)} emoji, {drawable} drawable) "
        f"and {REACTIONS.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
