"""The cat is "she", and stays "she".

Settled in the POC copy deck: female pronouns throughout, never *it*. The
sweep that settled it found the player-facing text already converted, which
is the good outcome and also the fragile one - there is nothing left to
show for it, so the next line written about her has nothing to copy from.

**This does not look for "it".** Prose about a house full of objects is
made of "it", and a check that flagged the word would be turned off within
a week. It looks for "it" doing something only a cat does, or owning a part
only a cat has. *The cat puts a paw on the toy and leaves it there* passes.
*The cat washes its paw* does not.
"""

import csv
import io
import re

import pytest

import bot
import content as content_module


# Verbs a cat is the subject of, and parts a cat has. Deliberately narrow:
# a miss is a line somebody fixes in review, a false positive is a check
# somebody deletes.
FELINE = (
    r"purrs?|purring|meows?|miaows?|pounces?|prowls?|slinks?|stalks?|grooms?"
    r"|naps?|curls? up|winds? (?:between|around)|rubs? (?:against|on)"
    r"|headbutts?|kneads?|hisses|yowls?|chirrups?|trills?"
)
PARTS = r"tail|whiskers?|paws?|ears?|fur|claws?|haunches"

AS_SUBJECT = re.compile(r"\bit\s+(?:" + FELINE + r")\b", re.I)
AS_OWNER = re.compile(r"\bits\s+(?:" + PARTS + r")\b", re.I)

COLUMNS = {
    "defaults.tsv": ["text"],
    "thing_text.tsv": [
        "look", "look_carried", "use", "take", "drop",
        "use_fail", "take_fail", "drop_fail", "move_depart", "move_arrive",
    ],
    "room_text.tsv": ["fragment", "look"],
    "achievements.tsv": ["name", "unlock"],
    "art.tsv": ["alt"],
}


def strings():
    """Every player-facing string in the content files, with its address."""
    for name, columns in COLUMNS.items():
        path = content_module.CONTENT_DIR / name
        with io.open(path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        head = set(rows[0].keys())
        key = next(c for c in rows[0] if c.endswith("_id") or c == "key")
        for row in rows:
            for column in [c for c in columns if c in head]:
                value = row.get(column) or ""
                if value.strip():
                    yield f"{name} [{row[key]}].{column}", value


def offences(text):
    return [m.group(0) for p in (AS_SUBJECT, AS_OWNER) for m in p.finditer(text)]


def test_the_cat_is_never_an_it():
    """Every string in the content files."""
    guilty = [
        f"{where}: {' / '.join(found)}"
        for where, value in strings()
        if (found := offences(value))
    ]

    assert guilty == []


def test_the_pet_blurbs_are_never_an_it():
    """**In code, not in a file**, which is why the sweep nearly missed
    them: six lines of the cat's own voice living in `bot.py` rather than
    in `defaults.tsv` with everything else she says."""
    guilty = [line for line in bot.PET_RESPONSES if offences(line)]

    assert guilty == []


@pytest.mark.parametrize(
    "line",
    [
        "It purrs and winds between your ankles.",
        "The cat stretches, and its tail flicks once.",
        "It meows at you and rubs against your leg.",
        "The cat washes its paw.",
    ],
)
def test_the_guard_catches_a_relapse(line):
    """The half of a guard that is worth more than the guard: proof it
    fires. A check that has never failed is a check nobody has tested."""
    assert offences(line)


@pytest.mark.parametrize(
    "line",
    [
        "You give it a gentle spin and watch the cat chase the moons.",
        "The cat is on it before it stops, skids past, and bats it under something.",
        "A round cat bed in the corner. There's no fur on it at all.",
        "It makes an outsized noise for its size, which is the entire point of it.",
        "It's heavier than it looks, and there are plenty more where it came from.",
        "The cat puts one paw on the {name} and leaves it there.",
        "She flattens her ears and slides out from under your hand.",
    ],
)
def test_the_guard_leaves_objects_alone(line):
    """The other half, and the reason the pattern is this narrow. Six of
    these are real lines out of the shipped content; a guard that flagged
    any of them would be switched off by the end of the week."""
    assert not offences(line)
