"""The smart speaker in every room.

Not a slash command: a message handler, because talking to a speaker by typing
`/use alexa` would be a strange way to talk to a speaker. Saying "alexa" gets
her stock non-answer; asking her to remind David about the delivery gets a real
one.

Nothing here stores a message. The handler reads what was typed, decides which
of two replies it earns, and forgets it.
"""

from __future__ import annotations

import re

# What she answers to. Matched at the start of the message, after normalising,
# so "Alexa, what's the weather" works and "ask alexa about it" does not - the
# second is people talking about her rather than to her.
WAKE_WORDS = ("alexa", "hey alexa", "ok alexa", "okay alexa")

# The two halves of the message David needs. Both must appear, in any order:
# "alexa remember to cancel the order" and "alexa the delivery, remind him"
# both count, because a player should not have to guess a phrasing.
#
# `remind` is a prefix of `reminder`, so testing for it covers both and the
# list needs only the two stems.
_ASKING = ("remind", "remember")
_ABOUT = ("delivery", "subscription", "subscribe", "order")

# Costco is deliberately absent. The standing order is no longer described as a
# Costco subscription anywhere in the content - Costco does not offer
# auto-delivery - so a player reading the to-do list has no reason to type it,
# and accepting it would reward a phrasing the game never suggests.

_PUNCTUATION = re.compile(r"[^\w\s]")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(_PUNCTUATION.sub(" ", text.casefold()).split())


def is_addressed(text: str) -> bool:
    """Whether this message is talking to Alexa rather than about her."""
    spoken = normalise(text)
    return any(
        spoken == wake or spoken.startswith(wake + " ") for wake in WAKE_WORDS
    )


def is_message_for_david(text: str) -> bool:
    """Whether this is the ask that gets a real answer.

    Both halves, any order, anywhere in the message after the wake word.
    """
    spoken = normalise(text)
    return any(word in spoken for word in _ASKING) and any(
        word in spoken for word in _ABOUT
    )
