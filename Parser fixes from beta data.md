# Parser fixes from beta data

*27 October. For the developer. These come from the beta interaction log, 23 to 27 October: 2,876 rows from 36 players. About 150 commands failed because the game didn't recognize the word the player typed. Most of those players were typing something they had just read.*

## 1. New aliases: content only, already done

These are added to `things.tsv` in creative content. No code is needed.

| Thing | Added | What players typed |
| --- | --- | --- |
| fence | `wire\|strands` | wire, 3 times |
| shelves | `chaff\|dried stem\|stem\|egg\|boards` | chaff, dried stem, egg, boards |
| firewood bin | `splinters\|splinter` | splinters |
| farm stand | `tin` | tin |
| branches | `trees\|tree` | trees |
| ditch | `water\|trickle` | water |
| fog | `middle distance` | middle distance, 4 times, after a toy refusal says the cat looks "at the middle distance" |
| cat | `paw\|paws\|eyes\|tail` | paw, eyes |
| cat bed | `catbed` | catbed, 4 times |
| feather wand | `featherwand\|ribbon\|stick` | featherwand, ribbon |
| coin slot | `coinslot` | coinslot |

None of these clash with an existing alias in the channel. `tree` and `water` also appear in the Entryway, on the coat tree and the cat bowl, but those are a different room.

## 2. Fuzzy matching for typos

About 15 failures were typos, including *crincle ball, crickle, crinkle vall, feather wamd, feathef, featehry, cat ber, car bed, roaf* and *rood*.

**Suggested rule:** when no thing in the player's room matches exactly, compare the typed noun with every name and alias of the things there. If exactly one is within an edit distance of 2, treat it as that thing.

- Apply it only to nouns of four letters or more, so short words don't jump to the wrong thing.
- If two or more things are equally close, fall back to the usual "don't see that" refusal. Don't guess.
- Log the match in `interaction_log` `detail`, for example `fuzzy=crincle ball→crinkle ball`, so we can check it isn't matching the wrong things.

## 3. `/look around`, `/look room` and `/look here`

Players tried *around*, *room*, *floor*, *under* and *behind*. Make `/look around`, `/look room` and `/look here` show the room's description, the same as a bare `/look`. This is the usual behavior in text games. *Under* and *behind* can keep the normal refusal.

## Acceptance tests

- `/look wire` on the road shows the fence. `/look middle distance` shows the fog. `/use catbed` fluffs the bed.
- `/take crincle ball` takes the crinkle ball, and the log shows the fuzzy match.
- `/look toi` gets the normal refusal, because it's too short to fuzzy-match.
- `/look around` shows the same text as `/look`.
