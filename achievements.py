"""The achievement dispatcher: which conditions run, and when.

One dispatcher, registered by hook. Nothing re-evaluates thirty-five
conditions after every action - a hook runs only the predicates listening on
it, which for most hooks is a handful.

**The condition lives here, not in the content file.** `achievements.tsv`
carries the name and the unlock text, which is what a writer owns and can edit
without a deploy. It deliberately has no `trigger` column: the conditions
involve counts, time windows, sets and cross-table joins, and a
half-expressive mini-language in a spreadsheet cell would be worse than a
function per achievement.

Three rules the rest of the module exists to keep:

**A hook fires every predicate registered on it and does not stop at the
first match.** Carving a pumpkin on 15 October earns both *Gourd Job* and
*Green Thumb*, and that is intended. Ordering within a hook is undefined and
must stay that way - no predicate may depend on another having run first.

**A predicate checks; it never mutates.** The hook runs after the command has
committed its own change. A check that writes game state makes the same action
behave differently depending on what the player had already earned.

**A predicate that raises must not take down the command that fired it.** A
player who loses an achievement to an exception can earn it next time; a
player whose `/take` returns an error has lost the thing.

Nothing here imports discord. `fire` awards and reports what was earned; the
announcing - a public name in the Halloween channel, a private description to
the earner - is the caller's job, because how the description is delivered
depends on whether an interaction token is in hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable

import database
import resolve

log = logging.getLogger(__name__)

# Every hook an achievement may listen on. `on_cross` has no call site: the cat
# carrying things between dimensions is post-launch, so the three achievements
# waiting on it are registered and simply never fire. That is cheaper than
# maintaining a shipping subset, and it means crossing arriving later turns
# them on without reopening this phase.
HOOKS = (
    "on_take",
    "on_drop",
    "on_use",
    "on_move",
    "on_pet",
    "on_reaction",
    "on_message",
    "on_midnight",
    "on_cross",
)


@dataclass(frozen=True)
class Context:
    """Everything a predicate may read about the action that just happened.

    Deliberately wide and mostly empty. A narrow context would mean changing
    the signature every time an achievement needs one more fact, and every
    call site with it.

    `source_id` is the field *Green Thumb* shaped. Taking herbs from the herb
    garden is gardening; picking up a `herbs` somebody dropped in the Entryway
    is scavenging, and the Functional Spec has a source and its yield counting
    as one thing during resolution - so both paths hand the player an identical
    `herbs` and the thing id alone cannot tell them apart. It is a field on the
    hook rather than a special case in one predicate.
    """

    guild_id: int
    hook: str
    # None for a hook with no actor: the midnight job, and the group
    # achievements, which have no earner by design.
    user_id: int | None = None
    thing_id: str | None = None
    # The source a take resolved against, None when it came off the floor.
    source_id: str | None = None
    room_id: str | None = None
    # Passed in rather than read from the clock, so a date-gated achievement
    # can be tested at both edges of its window without faking a timezone.
    now: datetime | None = None
    extra: dict = field(default_factory=dict)

    @property
    def when(self) -> datetime:
        return self.now or database._utcnow()


Predicate = Callable[[Context], Awaitable[bool]]


@dataclass(frozen=True)
class Trigger:
    achievement_id: str
    hooks: frozenset[str]
    predicate: Predicate


@dataclass(frozen=True)
class Earned:
    """One award that this action actually created.

    Only ever built when the insert created a row, so a caller can announce
    whatever it is handed without asking whether the player already had it.
    """

    achievement_id: str
    kind: str
    name: str
    unlock: str
    # None for a group achievement, which has no earner and whose description
    # goes to nobody.
    user_id: int | None


_TRIGGERS: dict[str, Trigger] = {}
_BY_HOOK: dict[str, list[Trigger]] = {hook: [] for hook in HOOKS}


def register(achievement_id: str, hooks: str | tuple[str, ...], predicate: Predicate) -> None:
    """Register one achievement against one or more hooks.

    Several hooks is ordinary rather than a special case: *Green Thumb* listens
    on `on_use` for the watering can and the pumpkin and on `on_take` for the
    herbs, because there are three ways to notice the date and all of them
    should count.
    """
    wanted = (hooks,) if isinstance(hooks, str) else tuple(hooks)
    if not wanted:
        raise ValueError(f"{achievement_id} registered against no hook")
    for hook in wanted:
        if hook not in _BY_HOOK:
            raise ValueError(f"{achievement_id}: {hook!r} is not a hook")
    if achievement_id in _TRIGGERS:
        raise ValueError(f"{achievement_id} is registered twice")

    trigger = Trigger(achievement_id, frozenset(wanted), predicate)
    _TRIGGERS[achievement_id] = trigger
    for hook in wanted:
        _BY_HOOK[hook].append(trigger)


def trigger_for(achievement_id: str) -> Trigger | None:
    return _TRIGGERS.get(achievement_id)


def registered_ids() -> set[str]:
    return set(_TRIGGERS)


def listening_on(hook: str) -> list[str]:
    """Which achievements a hook would run. Reported by `/admin_config`."""
    return [t.achievement_id for t in _BY_HOOK.get(hook, ())]


def clear() -> None:
    """Forget every registration. For tests, which build their own."""
    _TRIGGERS.clear()
    for hook in _BY_HOOK:
        _BY_HOOK[hook] = []


def registration_problems(achievement_ids: set[str]) -> list[str]:
    """Both directions: every row wired up, and every trigger backed by a row.

    The check worth building carefully. It catches the day somebody adds a
    thirty-sixth achievement and never wires it up - a name in the file that
    can never be announced - and the day an id is renamed and half the awards
    quietly stop landing.

    Takes the ids rather than the parsed content so it can be asked about a
    subset, and so `content.py` stays free of anything that touches a database.
    """
    problems = []
    for achievement_id in sorted(achievement_ids - registered_ids()):
        problems.append(
            f"achievement {achievement_id} is in the file with no registered "
            "trigger, so nothing could ever award it"
        )
    for achievement_id in sorted(registered_ids() - achievement_ids):
        problems.append(
            f"a trigger is registered for {achievement_id}, which is not in "
            "achievements.tsv, so an award would have no name to announce"
        )
    return problems


async def fire(context: Context) -> list[Earned]:
    """Run every predicate listening on this hook and award what passed.

    Returns only what this call actually created, so a caller can announce the
    list without checking anything. An achievement whose drop has not arrived
    on this server is skipped: it does not exist there yet, and awarding it
    would announce a name nobody can read.
    """
    triggers = _BY_HOOK.get(context.hook)
    if not triggers:
        return []

    try:
        available = await resolve.achievements(context.guild_id)
    except Exception:
        # The hook is decoration on an action that has already committed.
        log.exception("Could not read achievements for guild %s", context.guild_id)
        return []

    earned = []
    for trigger in triggers:
        row = available.get(trigger.achievement_id)
        if row is None:
            continue
        try:
            if not await trigger.predicate(context):
                continue
            award = await _award(context, row)
        except Exception:
            # One bad predicate must not cost the player the other thirty-four,
            # nor the command that fired the hook.
            log.exception(
                "Achievement %s raised on %s in guild %s",
                trigger.achievement_id,
                context.hook,
                context.guild_id,
            )
            continue
        if award is not None:
            earned.append(award)
    return earned


async def _award(context: Context, row: resolve.AchievementRow) -> Earned | None:
    """Write the award. None when the player or server already had it."""
    if row.kind == "group":
        created = await database.award_server_achievement(
            context.guild_id, row.achievement_id
        )
        user_id = None
    else:
        if context.user_id is None:
            log.error(
                "%s is %s but fired on %s with no player",
                row.achievement_id,
                row.kind,
                context.hook,
            )
            return None
        created = await database.award_player_achievement(
            context.guild_id, context.user_id, row.achievement_id
        )
        user_id = context.user_id

    if not created:
        return None
    return Earned(row.achievement_id, row.kind, row.name, row.unlock, user_id)
