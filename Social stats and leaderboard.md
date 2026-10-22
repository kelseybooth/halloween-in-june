# Social stats and the leaderboard

*Specified 21 October with the day's decisions folded in. Ships with drop 0 to the beta server.*

## Decisions, 21 October

- **The leaderboard is a button** at the bottom of `/stats`, and the leaderboard has a **See my stats** button at its bottom that returns to the clicker's own `/stats`.
- **Raw scores**, not relationship tiers.
- **The cat is always in the player's room.**
- **A status line under the relationship prose in `/stats`**, specified below.
- **The last five achievements: the developer finds a way.** An `earned_at` column may not be needed.

## The flow

`/stats` → **Leaderboard** → leaderboard → **See my stats** → the clicker's own `/stats`.

- **Edit the message in place.** Each click answers by updating the same ephemeral message rather than sending a new one, so going back and forth never stacks replies.
- **Buttons need a component-interaction handler**, which the bot does not have yet. Route on the button's `custom_id`, and keep the handler persistent: an ephemeral `/stats` can sit open for hours, and a click after a restart still has to work.
- **Answer within three seconds.** Discord drops an interaction left unanswered that long; if the leaderboard query can be slow, defer first.
- **`/stats @player` gets the same footer.** Its Leaderboard button behaves the same way, and See my stats from there returns to the clicker's stats, not the viewed player's.

## The leaderboard

### Top players by relationship

- **Raw score.** Negative scores show as negative; the floor is −100.
- **Top ten, a separator, then the viewer's own rank with one player either side.** Someone sitting 34th sees exactly where they stand without paging.
- **Ties** sort by score descending, then earliest first interaction, so equal scores do not shuffle between views.
- **Exclude players with no recorded interaction**, or day one is a wall of zeroes in membership order. Below three qualifying players, say so rather than render a stub.
- **Finding a specific person is `/stats @player`**, using Discord's `USER` option type: the client's member picker searches the whole server, and there is no name matching to get wrong.

### Five most recent achievements

- **Achievement name and player only** — no blurb, no context.
- **Developer ask: find a way to list the last five.** An `earned_at` column may not be necessary. One caveat if insertion order is the answer: anything awarded by recomputation rather than in the moment — *Making Friends* and *Trying to Make Friends* can be recomputed from `relationship_at_pet` — would appear as "recent" on the day it was recomputed.

### Why this does not spoil secrets

The bot already posts every achievement's name in the channel as it is earned, secrets included; per the Achievement Trigger Spec, a secret's name going up is itself the hint that something is there to find. So names are safe. The only genuinely new disclosure is pairing a name with a player. What must stay hidden is **progress** toward a secret — *3 of 5 baby bottles* is a spoiler in a way that *Trash Panda* is not.

## `/stats` — the status line

One line directly under the prose description of the relationship. Private view only.

| Expectant | Hungry | Crowded | Line |
| --- | --- | --- | --- |
| yes | no | no | The cat looks at you expectantly. |
| no | yes | no | The cat looks at you with hunger in her eyes. |
| yes | yes | no | The cat looks at you expectantly with hunger in her eyes. |
| — | no | yes | You've pet the cat a lot recently. |
| — | yes | yes | The cat looks at you with hunger in her eyes. You've pet the cat a lot recently. |
| no | no | no | *no line* |

**Expectant:** the current pet success chance is above 50%. Exactly 50% counts as not expectant.

**Hungry:** the cat can be fed — eight hours since this player's last successful feed, or never fed — **and the server is at drop 3 or later.** Without the drop gate, every player at drops 0 to 2 counts as never fed, and `/stats` would tell all of them the cat is hungry in a game with no food in it yet.

**Crowded:** the current pet success chance is below 50%. The chance depends only on pets in the last ten minutes — never on relationship score — so below 50% always means the player has petted a lot recently, and it can never coincide with *expectant*. At exactly 50% neither pet line shows; use *50% or lower* here if the warning should start one pet sooner.

**The hunger line doubles as the tutorial reminder.** From drop 3, an un-graduated player who opens `/stats` is told the cat is hungry right beside the open quest, which is the job the follow-the-player nudge would have done.

**Copy notes.** No comma after *expectantly*: two short modifiers on one verb, nothing to disambiguate. And *pet* versus *petted* — the standard American past participle is *petted*, and *pet* reads as casual speech. Either fits this voice; flagged rather than changed.

## The public view, `/stats @player`

| Shown | Hidden |
| --- | --- |
| Raw relationship score and its prose description | The status line above |
| Names of achievements earned | Open quests |
| Count earned, out of the number available at the current drop | `unlock` blurbs |
| Leaderboard rank | Counters toward unearned achievements, and per-player mechanics — toy ramp, cooldowns, last-fed time |

## Decided 21 October, second round

- **Previous and Next buttons on the leaderboard**, beside See my stats. Pages of ten, with the viewer's own-rank block on the first page. Carry the page number in each button's `custom_id`, so a click needs no stored state and still works after a restart.
- **The recent-achievements section is held to drop 1.** At drop 0 it would be five copies of the one achievement anyone can earn. Gate it on the server's current drop rather than switching it on by hand.
