"""The two emoji TSVs are built from the writers' catalogue, not typed.

`emoji-catalogue-v18.csv` is a spreadsheet the writers edit: 1,927 rows, one
per emoji. The game loads TSVs, so the TSVs are derived - and the failure
mode of a derived file is silent. A hand-edit to one of them loads perfectly
well and survives exactly until the next export, at which point it is gone
and nobody can say which row changed back.

So the test that matters most here is the dull one: **the files in the repo
are what the catalogue makes**. The rest check the two derivations that are
not a straight copy - which emoji the cat may crave, and the join between
the writers' display Types and the slugs the game branches on.
"""

import csv
import io

import pytest

import content as content_module
import generate_emoji_files as gen


@pytest.fixture(scope="module")
def catalogue():
    return gen.read_catalogue()


# --------------------------------------------------------------------------
# The files on disk
# --------------------------------------------------------------------------


def test_the_shipped_files_are_what_the_catalogue_makes():
    """**The whole point of the script.** This is the same check the
    pre-push hook runs, and the only moment anybody finds out that a TSV
    was edited by hand."""
    assert gen.main(["--check"]) == 0


def test_a_hand_edited_file_is_caught(tmp_path, monkeypatch, capsys):
    """And the complaint names the line, because "the TSVs are stale" is
    not something anybody can act on."""
    mangled = tmp_path / "emoji_groups.tsv"
    # Universal newlines on the way in and out. Split on a hard-coded
    # CRLF this found one line on a Linux checkout and raised IndexError
    # instead of testing anything.
    with io.open(gen.GROUPS, encoding="utf-8", newline=None) as handle:
        rows = handle.read().splitlines()
    rows[3] = rows[3].replace("\tMisc\t", "\tFood\t")
    with io.open(mangled, "w", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")
    monkeypatch.setattr(gen, "GROUPS", mangled)

    assert gen.main(["--check"]) == 1

    complaint = capsys.readouterr().err
    assert "line 4" in complaint
    assert "generate_emoji_files.py" in complaint


def test_a_missing_file_is_caught(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gen, "GROUPS", tmp_path / "gone.tsv")

    assert gen.main(["--check"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_writing_is_what_fixes_it(tmp_path, monkeypatch):
    groups, reactions = tmp_path / "groups.tsv", tmp_path / "reactions.tsv"
    monkeypatch.setattr(gen, "GROUPS", groups)
    monkeypatch.setattr(gen, "REACTIONS", reactions)

    assert gen.main([]) == 0
    assert gen.main(["--check"]) == 0


# --------------------------------------------------------------------------
# What the cat may crave
# --------------------------------------------------------------------------


def test_only_food_and_prey_are_drawable(catalogue):
    """Adjacent and Toy are real game categories that can earn a 😼, and
    a cat who wants a mug is a strange day."""
    drawable = {row["Category"] for row in catalogue if gen.is_drawable(row)}

    assert drawable == {"Food", "Prey"}


def test_an_emoji_new_in_this_unicode_release_is_not_drawable(catalogue):
    """**Derived from the ⊛ Unicode puts on a new name, not from a list of
    two.** Discord's picker lags the standard by months, and a craving
    nobody can type is unwinnable - with no way for the player to tell
    that apart from being wrong. Written out, the exclusion would be right
    today and silently wrong the week the writers paste in a 19.0 export.
    """
    new = [row for row in catalogue if row["CLDR short name"].startswith("⊛")]

    assert new, "the catalogue marks nothing as new; has the ⊛ convention changed?"
    assert not any(gen.is_drawable(row) for row in new)


def test_the_four_that_lose_out_and_why(catalogue):
    """Named here rather than in the script, so the derivations above are
    checked against the answer they are meant to produce today - and so
    the two reasons stay distinguishable. A pickle is out because Discord
    may not have it; a mouse face is out because it is already in the
    pool, as a mouse."""
    lost = {
        row["CLDR short name"]
        for row in catalogue
        if row["Category"] in gen.CRAVABLE and not gen.is_drawable(row)
    }

    assert lost == {
        "⊛ pickle",
        "⊛ monarch butterfly",
        "mouse face",
        "rabbit face",
    }


def test_an_alias_resolves_to_the_emoji_it_answers_for(catalogue):
    """The catalogue names the pair by code, because a code survives a
    spreadsheet and a paste where an emoji may not. The game compares
    emoji, so the generator resolves it once instead of every guess."""
    resolved = gen.canonical_emoji(catalogue)

    assert resolved["U+1F42D"] == chr(0x1F401)
    assert resolved["U+1F430"] == chr(0x1F407)


def test_an_alias_pointing_at_a_code_that_is_not_there_is_an_error(catalogue):
    bent = [dict(row) for row in catalogue]
    next(r for r in bent if r["code"] == "U+1F42D")["Same As"] = "U+NOPE"

    with pytest.raises(gen.Stale, match="not a code in the catalogue"):
        gen.canonical_emoji(bent)


def test_the_root_vegetable_survives(catalogue):
    """Unicode 16.0, and Discord's picker has it. The one that proves the
    rule is about this release rather than about recency in general."""
    row = next(r for r in catalogue if r["CLDR short name"] == "root vegetable")

    assert gen.is_drawable(row)


def test_the_count_the_spec_asks_for(catalogue):
    """136 in the spec, less the two face/body pairs folded together."""
    assert sum(1 for row in catalogue if gen.is_drawable(row)) == 134


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


def test_every_outcome_the_game_branches_on_has_a_row(catalogue):
    built = {row[0] for row in gen.reaction_rows(catalogue)}

    assert built == set(content_module.CRAVING_OUTCOMES)


def test_the_rows_come_out_in_ladder_order(catalogue):
    built = gen.reaction_rows(catalogue)

    assert [row[0] for row in built] == list(content_module.CRAVING_OUTCOMES)


def test_a_bot_row_the_game_has_no_branch_for_is_an_error(catalogue):
    """The writers own the Type column, and the game owns the slugs. A new
    Type is a new outcome, which needs code - so it stops here rather than
    producing a file with a seventh row nothing reads."""
    invented = [dict(row) for row in catalogue]
    next(r for r in invented if r["Category"] == "Bot")["Type"] = "Somewhat Right"

    with pytest.raises(gen.Stale, match="not.*one of the six outcomes"):
        gen.reaction_rows(invented)


def test_a_missing_bot_row_is_an_error(catalogue):
    kept = [row for row in catalogue if row["Type"] != "Win"]

    with pytest.raises(gen.Stale, match="no Bot row for win"):
        gen.reaction_rows(kept)


def test_the_prose_column_is_carried_over_rather_than_invented(catalogue):
    """`when` is a sentence for the writers, and the catalogue has no
    column for it. Regenerating has to keep it, or every export would
    blank the one part of the file a person wrote."""
    built = {row[0]: row[5] for row in gen.reaction_rows(catalogue)}

    assert "Misc or Cat" in built["greeting"]


# --------------------------------------------------------------------------
# The TSV itself
# --------------------------------------------------------------------------


def test_the_order_is_the_catalogues_own(catalogue):
    """A diff against the last export is how a writer checks their own
    change, and a re-sort would make every row look edited."""
    built = gen.group_rows(catalogue)

    assert [row[0] for row in built] == [row["emoji"] for row in catalogue]


def test_a_cell_with_a_tab_in_it_is_refused():
    """Written by hand rather than through `csv.writer` so that this
    raises here instead of being quoted into a row the loader then splits
    in the wrong place."""
    with pytest.raises(gen.Stale, match="tab or a newline"):
        gen.render(("a",), [("has\there",)])


def test_the_check_does_not_care_which_line_endings_are_on_disk(tmp_path, monkeypatch):
    """**The bug that only showed up in CI.** `.gitattributes` says
    `text=auto`, so these files are CRLF in a Windows working tree and LF
    in a Linux one, for the same content. Comparing whole strings passed
    on the machine that wrote the file and failed on the other, with the
    complaint that it "has 1928 lines; the catalogue makes 1928".
    """
    catalogue = gen.read_catalogue()
    lines = gen.render(gen.GROUP_COLUMNS, gen.group_rows(catalogue))

    for ending in ("\n", "\r\n"):
        path = tmp_path / f"groups{len(ending)}.tsv"
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(ending.join(lines) + ending)
        gen.check(path, lines)  # must not raise, either way


def test_a_missing_row_is_reported_as_a_missing_row(tmp_path, monkeypatch, capsys):
    """The length mismatch used to print both counts as the same number,
    which told nobody anything."""
    catalogue = gen.read_catalogue()
    lines = gen.render(gen.GROUP_COLUMNS, gen.group_rows(catalogue))
    short = tmp_path / "short.tsv"
    with io.open(short, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines[:-3]) + "\n")

    with pytest.raises(gen.Stale, match="the catalogue has 3 more than on disk"):
        gen.check(short, lines)


def test_the_file_the_loader_reads_agrees_with_the_catalogue(catalogue):
    """End to end: the parser's view of a row and the catalogue's row."""
    parsed = {row.emoji: row for row in content_module.load_files().emoji_groups}

    for row in catalogue:
        entry = parsed[content_module.normalise_emoji(row["emoji"])]
        assert entry.category == row["Category"]
        assert entry.type == row["Type"]
        assert entry.drawable == gen.is_drawable(row)


def test_nothing_is_both_excluded_and_drawable(catalogue):
    """The craving must never be an emoji the bot refuses to judge."""
    for row in gen.group_rows(catalogue):
        assert not (row[5] == "yes" and row[6] == "yes"), row


def test_the_faces_the_bot_answers_with_are_all_excluded(catalogue):
    built = {row[0]: row for row in csv.reader(
        gen.render(gen.GROUP_COLUMNS, gen.group_rows(catalogue))[1:],
        delimiter="\t",
    )}
    for row in gen.reaction_rows(catalogue):
        assert built[row[2]][6] == "yes", row[0]
