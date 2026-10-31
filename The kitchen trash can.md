# The kitchen trash can (approved 30 October)

Oct 30, 2026 · @Qaruse

**The trash can becomes a container players can throw things into, fish things out of, and empty.** `/use trash can` moves things from your bag into it. Anyone can `/take` them back out. `/take trash can` takes the bag out to the curb: everything the house can make more of is gone for good, and anything one-of-a-kind finds its way back into the house somewhere else. Nothing here is in the files yet.

## Throwing things away: `/use trash can`

1. **Pick a thing.** The reply is private: a menu of everything in your bag that can be put down, with how many you have of each.
2. **Pick how many**, if you have more than one: **All** (with the count), or **Some**, which opens a box for a number.
3. **It goes in.** The things move from your inventory into the trash can, and the reply offers **Throw away something else**.

| When | Text |
| --- | --- |
| The menu | You step on the pedal and the lid swings up. What are you throwing away? |
| More than one | You're carrying 6. How many go in? |
| Number box title | Throw away: spice jar |
| Number box label | How many? (1 to 6) |
| Not a number you have | That isn't a number you can throw away. Try a number from 1 to 6. |
| Done | You drop 3 of them into the trash, and the lid swings shut. (One thing: "You drop the spice jar into the trash, and the lid swings shut.") |
| Done, to the room | {player} steps on the pedal and drops something in the trash. |
| Nothing in your bag to throw away | You step on the pedal. The lid swings up. You have nothing to throw away, so it swings shut again. |

The room line doesn't say what went in, so the only way to find out is to look. Changed 30 October when writing the files: the lines avoid plurals ("6 spice jars"), because the engine fills in a thing's name as written.

**What can't go in:**

- **Anything that can't be dropped** isn't in the menu: the skeleton key, the carving tools and the ghost's bedsheet.
- **The ladder** never gets that far, because carrying it already blocks `/use`.

## Looking and taking things out

**What's in the trash can shows in its Also here list**, the way the shipping box shows its spice jars. Anyone in the kitchen can `/take` from it like any other container, including things somebody else threw away.

| When | Text |
| --- | --- |
| `look` (replaces today's) | A tall kitchen trash can with a foot pedal, the lid not quite shut on whatever's inside. |
| Taking something out | You fish the spice jar out of the trash. It seems fine. Mostly. |
| Taking something out, to the room | {player} goes through the trash and comes out with something. |

The first thing a player takes out earns **Trash Panda**, which is waiting on this mechanic. Its unlock text already fits: "Went through the trash and came out with something."

## Taking out the trash: `/take trash can`

**The bag goes out to the curb, and the trash can is empty again.** The player stays in the kitchen. Two things happen to what was in it:

- **Things the house can make more of are deleted.** That's anything a source hands out, anything a restock places, and anything made from one of those. Examples: cat food, candy, spice jars, baby bottles (used or sanitized), diapers, toys, herbs, pieces of wasp nest.
- **One-of-a-kind things go back into the house.** Each is placed straight away in a random container somewhere else in the house. Today that's the cat collar, the music box, the silver baby spoon, the candle stub and the brass key.

| When | Text |
| --- | --- |
| The bag goes out | You lift the bag out, tie it off, and carry it out to the curb. When you come back, you put a fresh bag in the can. |
| Something one-of-a-kind was in it | Something in the bag clinks against the steps on the way out. When you look, you can't find what fell out. |
| It was empty | There's nothing in the bag but coffee grounds and a banana peel. You take it out anyway. Somebody has to. |
| To the room | {player} takes the trash out to the curb. |

The clink is the only hint that something has gone back into the house, and it doesn't say where.

**Curbside Pickup moves to this.** It's earned for taking the trash out on a Tuesday, Pacific time. Its trigger was `/use trash can`, which now opens the menu instead.

## A new achievement: carrying a diaper into the kitchen (approved)

**Earned on a player's first `/look` in the Kitchen, if they're carrying a dirty diaper.** Walking in doesn't print a room's description, so that first `/look` is when they first see the trash can. Diapers have been turning up since drop 3, and the carried diaper already says "You have started planning where to put it down." This pays that off.

| Field | Draft |
| --- | --- |
| `achievement_id` | `bin_looking_for_you` |
| `kind` | secret |
| `name` | **Bin Looking for You** (Previously considered options: *A Sight for Sore Noses*, *Bin There, Done That**)* |
| `unlock` | Walked into the kitchen with a dirty diaper in hand and found the trash can at last. |
| `since_drop` | 30, when the Kitchen opens |
| `sort_order` | 95, beside Trash Panda |

**One chance only.** The check runs only on a player's first `/look` in the Kitchen. Without a diaper in their bag then, they can never earn it, which is why it's secret.

**For the developer:** record a per-player "has looked at the Kitchen" flag on their first `/look` there. At that moment, if the player carries at least one `dirty_diaper`, award the achievement. Players who already looked at the Kitchen before this ships have used their chance.

## Changes to the files

| File | Change |
| --- | --- |
| `things.tsv`, `trash_can` | Add the aliases `trash bag` and `garbage bag`, so `/take trash bag` takes it out. Set `scatter_target` to no, so the bottle and diaper scatter never lands in it |
| `thing_text.tsv`, `trash_can` | The new `look` and the lines above. Its `use` and `take_fail` go, because both actions now do something |
| `defaults.tsv` | The menu, count, number-box, result and room lines, since they're shared by every thing that goes in or comes out |
| `achievements.tsv` | Trash Panda moves from 99 to drop 30 and loses its "Blocked" note. Curbside Pickup's trigger changes to `/take trash can` |

## For the developer

1. **The trash can holds things.** Items moved in become `room_contents` rows in the Kitchen with `container_id = trash_can`, the same way the shipping box holds its spice jars.
2. **`/use trash can`**: a private select menu of carried things that are droppable, with counts. Discord allows 25 options, so a bag with more kinds than that needs a second page. Then All or Some, with a number box for Some.
3. **`/take` from the trash can** works like any container and fires Trash Panda the first time.
4. **`/take trash can`** empties it. A thing counts as one-of-a-kind when no source yields it, no restock places it (including `type:` rows), it isn't a `transforms_to` result and it isn't another thing's `yields`. Everything else is deleted.
5. **Where one-of-a-kind things go:** a random container in a room open at the current drop, with `scatter_target` yes, that isn't the trash can and isn't in the Secret Library. The library is excluded because a player who hasn't found it could never get the thing back.
6. **The brass key is one-of-a-kind on purpose.** Before the front door opens, throwing away the only key would lock the server out until the cat bed drops the 24-hour spare.
7. **Curbside Pickup** fires on `/take trash can` on a Pacific Tuesday.

## Open questions

- [x] **Which drop?** The trash can arrives at drop 30, and so does Curbside Pickup with its old trigger. I'd ship this in the drop 30 work order so the achievement doesn't change trigger after launch. Decided 30 October: drop 30.
- [x] **Should the trash ever go out on its own?** No: things stay in the trash can until somebody takes it out, however long that is. Decided 30 October.
