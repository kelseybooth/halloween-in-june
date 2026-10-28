"""Which commands a server can see, and therefore which exist in it.

**A command a player cannot use is not in their slash menu at all.** It is
not registered, so it cannot be typed, guessed, or half-learned from the
autocomplete. That is the whole point: the overwhelm the testers hit came
from a menu full of verbs with nothing to use them on, and a refusal is
still a verb - it teaches the player the command exists and that they got
it wrong, which is worse than silence.

So registration is per guild rather than global. Guild registration is
what lets two servers sit on different drops at once, and guild command
updates propagate in seconds where global ones can take an hour.

The tables below are keyed by the drop that *introduces* a set, and a
server uses the highest entry at or below its own drop. Writing each set
out in full rather than as a diff from the one before is deliberate: the
question anybody ever asks of this file is "what can a player see at drop
N", and a list of additions makes that a calculation.
"""

from __future__ import annotations

# What players get.
PLAYER_COMMANDS: dict[int, tuple[str, ...]] = {
    0: ("pet", "stats"),
    1: ("pet", "stats", "look", "use"),
    # Drop 2 is the toys, and the drop that teaches carrying things.
    2: ("pet", "stats", "look", "use", "take", "drop", "inventory"),
    # **Drop 3 is deliberately absent.** The craving game is played with
    # emoji reactions and adds no verb, so a server there keeps drop 2's
    # seven and the table says so by saying nothing. An entry repeating
    # drop 2's list would read as a drop that changed something.
    #
    # The house. Was keyed at 3 until the 26 October renumbering moved it
    # to 10; a server on 3 with a way in would have been a nine-room house
    # whose rooms do not exist yet. Phase 3b owns making this list honest.
    #
    # **`/go` in place of `/enter`.** Going into the house is ordinary
    # movement now - the road has a house across it and the house has a
    # front door back out - so the command that arrives here is the one
    # that moves a player anywhere, and the one that only ever went one
    # way is gone.
    10: ("pet", "stats", "look", "use", "take", "drop", "inventory", "go"),
}

# What admins get. Separate because it does not follow the player ladder:
# an admin needs `/start-game` in a server that has no game at all, which
# is the one state where players get nothing.
ADMIN_COMMANDS: dict[int, tuple[str, ...]] = {
    0: ("start-game", "advance-game", "admin_config", "reset-haunted-house"),
    # 10, with the house: `/initialize-haunted-house` seeds rooms.
    10: (
        "start-game",
        "advance-game",
        "admin_config",
        "reset-haunted-house",
        "initialize-haunted-house",
    ),
}

# Before `/start-game`. No game, so no player commands - a member of a
# server the bot was invited to and never set up sees nothing from it.
NO_GAME_COMMANDS: tuple[str, ...] = ADMIN_COMMANDS[0]

# The QA tools, registered only in the two test servers. Not in the
# tables above because they do not belong to a drop: a test server has
# them at every drop, and the live server has them at none - which is
# the first and strongest of the three gates on them, because a command
# that is not registered cannot be found by a curious member.
QA_COMMANDS: tuple[str, ...] = (
    "qa-drop",
    "qa-reset-player",
    "qa-relationship",
    "qa-clock",
    "qa-midnight",
    "qa-cooldown",
    "qa-inspect",
    # Drop 2: the ramp is the mechanic, and twenty-five successful
    # plays is four hours of cooldowns without a way to set it.
    "qa-state",
    "qa-spawn",
    # Undoes a launch, which no admin command can: `/reset-haunted-house`
    # writes the drop and the channel straight back on purpose, and its
    # `back_to_drop` floors at drop 0 because no drop number means "not
    # started". Testing the first five minutes needs the state before
    # them, and that state was reachable exactly once per server.
    "qa-reset-server",
)


def _highest_at_or_below(table: dict[int, tuple[str, ...]], drop: int) -> tuple[str, ...]:
    keys = [k for k in table if k <= drop]
    if not keys:
        # A drop below every entry. Cannot happen while 0 is the first one,
        # and returning nothing is the safe answer if that ever changes.
        return ()
    return table[max(keys)]


def commands_for(drop: int | None, *, qa: bool = False) -> set[str]:
    """Every command registered in a server sitting on this drop.

    `None` is a server whose game has not been started, which is not the
    same as drop 0: drop 0 is a channel with a cat in it, and `None` is a
    server where there is not yet anywhere for the cat to be.

    `qa` adds the test tools, and is true for exactly two servers. They
    are outside the drop tables on purpose - a test server has them at
    every drop, including before the game starts, because resetting a
    player is most useful when there is nothing to reset.
    """
    if drop is None:
        found = set(NO_GAME_COMMANDS)
    else:
        found = set(_highest_at_or_below(PLAYER_COMMANDS, drop)) | set(
            _highest_at_or_below(ADMIN_COMMANDS, drop)
        )
    return found | set(QA_COMMANDS) if qa else found


def player_commands_for(drop: int | None) -> set[str]:
    """The player half, for saying what a drop opened without listing the
    admin commands nobody but an admin can see anyway."""
    if drop is None:
        return set()
    return set(_highest_at_or_below(PLAYER_COMMANDS, drop))


def arrivals(previous: int | None, current: int | None) -> set[str]:
    """Which player commands a move between two drops just turned on."""
    return player_commands_for(current) - player_commands_for(previous)
