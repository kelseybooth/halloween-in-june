"""The leaderboard: who the cat likes best, and what was earned lately.

**Raw scores, not bands.** `/stats` gives a player a sentence because a
sentence is what one person's relationship means to them; a ranking is a
comparison, and a comparison needs the number. The two readings coexist.

Reached by a button under `/stats` rather than by a command of its own,
so it adds nothing to the slash menu and nothing to the gating table.

This module knows how to turn rows into lines. The buttons that carry a
player between the two views live in `bot`, because they need both.
"""

from __future__ import annotations

import database
import phrasing
import resolve

# One page of the ranking. Ten is what fits beside the viewer's own block
# without the embed needing to be read in two sittings.
PAGE = 10

# How many players either side of the viewer to show when they are off
# the first page. One each way is enough to answer "who do I have to
# catch" and "who is catching me", which is the whole question.
NEIGHBOURS = 1

# Below this, a leaderboard is a list of two people and reads as a bug
# rather than as a standing. Say so instead.
MINIMUM = 3

# The recent-achievements section. Held to drop 1 and later: at drop 0
# the only thing anybody can earn is the first pet, so five rows of it
# would be a list of who has played at all.
RECENT = 5
RECENT_FROM_DROP = 1

# How deep to read the award history to fill the recent list, given that
# some of it belongs to people who have since left. Five rows of five
# departures is the pathological case and this covers it; if it ever
# does not, the section is short by a line rather than wrong.
RECENT_DEPTH = 5


async def standings(guild) -> list[tuple[int, int]]:
    """(player, score) for everyone currently here who has met the cat.

    **People who have left the server are dropped, not shown greyed.**
    A leaderboard is a thing people read every day, and a standing row
    for somebody who has gone makes every reader notice the leaving. The
    cost is that the numbers below them shift, which is the right trade:
    nobody is owed a permanent rank, and nobody should be reminded.

    Membership is the guild's answer, not the database's, which is why
    this filter lives here and not in the query.
    """
    return [
        (user_id, score)
        for user_id, score in await database.relationship_ranking(guild.id)
        if guild.get_member(user_id) is not None
    ]


async def rank_of(guild, user_id: int) -> int | None:
    """Where this player sits, or None if they are not in the standings.

    Shared with `/stats @somebody` so the two can never disagree. A rank
    computed off the unfiltered query would count departed players and
    put everybody one or two lower than the board says they are.
    """
    return next(
        (
            n
            for n, (who, _) in enumerate(await standings(guild), start=1)
            if who == user_id
        ),
        None,
    )


async def pages(guild) -> int:
    """How many pages the ranking fills. At least one, even when empty."""
    return max(1, -(-len(await standings(guild)) // PAGE))


async def lines(guild, viewer_id: int, page: int = 0) -> list[str]:
    """The whole leaderboard for one viewer, as embed lines.

    `guild` is passed rather than its id because the names are the
    point and only the guild knows them. Duck-typed: anything with
    `id` and `get_member` will do, which is what the tests hand it.
    """
    here = await standings(guild)

    if len(here) < MINIMUM:
        return [await phrasing.default_say("leaderboard.too_few")]

    body = [f"**{await phrasing.default_say('leaderboard.header.top')}**"]
    body += await _standings(guild, here, viewer_id, page)

    recent = await _recent(guild, page)
    if recent:
        body += ["", f"**{await phrasing.default_say('leaderboard.header.recent')}**"]
        body += recent
    return body


async def _standings(guild, standings, viewer_id: int, page: int) -> list[str]:
    """One page of the ranking, plus where the viewer sits if they are off it.

    **The own-rank block is the first page's alone.** Somebody paging
    through the middle of the table is reading other people's
    standings; repeating theirs under every page is the kind of thing
    that makes a list feel like an interface. One click returns them.
    """
    start = page * PAGE
    window = standings[start:start + PAGE]
    body = [
        await _entry(guild, rank, user_id, score, viewer_id)
        for rank, (user_id, score) in enumerate(window, start=start + 1)
    ]

    if page:
        return body

    here = next(
        (n for n, (user_id, _) in enumerate(standings) if user_id == viewer_id),
        None,
    )
    if here is None or here < PAGE:
        return body

    # Their own rank with one player either side, so the number has
    # somebody on it rather than standing alone.
    low = max(PAGE, here - NEIGHBOURS)
    body.append(await phrasing.default_say("leaderboard.separator"))
    body += [
        await _entry(guild, rank, user_id, score, viewer_id)
        for rank, (user_id, score) in enumerate(
            standings[low:here + NEIGHBOURS + 1], start=low + 1
        )
    ]
    return body


async def _entry(guild, rank: int, user_id: int, score: int, viewer_id: int) -> str:
    key = "leaderboard.entry.you" if user_id == viewer_id else "leaderboard.entry"
    return await phrasing.default_say(
        key, rank=rank, name=await _name(guild, user_id), score=score
    )


async def _recent(guild, page: int) -> list[str]:
    """The last few achievements earned here, newest first.

    **Names only, no blurbs.** The bot already posts every achievement's
    name to the channel as it is earned, secrets included - a secret's
    name going up is itself the hint that there is something to find -
    so a name beside a player discloses nothing the room has not
    already seen. What must stay hidden is *progress* toward one, and
    none of that is here.
    """
    if page:
        return []
    guild_id = guild.id
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop < RECENT_FROM_DROP:
        return []

    available = await resolve.achievements(guild_id)
    body = []
    for achievement_id, user_id, _ in await database.recent_achievements(
        guild_id, RECENT * RECENT_DEPTH
    ):
        row = available.get(achievement_id)
        if row is None:
            # Earned under a drop that has since been rolled back, or an
            # id the files no longer carry. Nothing to name it with.
            continue
        if user_id is not None and guild.get_member(user_id) is None:
            # Same rule as the standings: somebody who has left is not
            # news, and naming them here would say they have gone.
            continue
        key = "leaderboard.recent" if user_id else "leaderboard.recent.server"
        body.append(
            await phrasing.default_say(
                key, name=row.name, player=await _name(guild, user_id)
            )
        )
        if len(body) == RECENT:
            break
    return body


async def _name(guild, user_id: int | None) -> str:
    """What to call a player. Only ever called for one who is still here.

    `None` is a server achievement, which has no earner by design -
    nobody is credited and everybody holds it.
    """
    if user_id is None:
        return ""
    member = guild.get_member(user_id)
    return member.display_name if member else ""
