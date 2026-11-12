# The ghost and the spirit board

Oct 30, 2026 · @Qaruse

**A daily guessing game: one player is secretly the ghost, haunts the house with anonymous whispers, and everyone else uses Elena's spirit board to work out who it is.** It builds on the Story Bible's ghost of the day and adds what makes it a game rather than a coin toss: the board spells out clues, one letter of the ghost's name per player per day, so players have to compare notes. Its lines and achievements are in the files as of 11 November. The bedsheet and spirit board rows go in with the Part 2 code (see the Drop 50 work order).

## How a day plays

1. **At the daily changeover**, the board reveals yesterday's ghost in the channel if they haunted at all, then one random active player becomes today's ghost and finds a bedsheet in their bag.
2. **The ghost haunts.** They pick a room and type a whisper, and it's posted there unsigned.
3. **Everyone else investigates.** Anyone who has found the Secret Library can ask the spirit board for one letter of the ghost's name a day, and name one suspect a day.
4. **The answer is private.** The board says YES or NO only to the player who asked.

## Who can be the ghost

- **Only active players.** The pick is from players who have entered the house and used any command on the day before, by the game's Pacific day. The Story Bible picked from anyone who had ever entered, but a ghost who has stopped playing makes the day impossible to guess.
- **Completely random**, as the Story Bible has it, so the same player can be the ghost two days running. The one exception is the first ghost, below.
- **At least 3 eligible players**, or there's no ghost that day (config `ghost_min_players`). With two, the guess answers itself.
- **The name is fixed at the pick.** The ghost's server display name is saved when they're chosen, and every clue comes from that saved name, so renaming yourself mid-day doesn't scramble the clues.
- **The changeover is the game's existing Pacific day**, the same one the daily cooldowns use.
- **The first ghost isn't random.** On the day somebody first finds the Secret Library, that player gets the bedsheet the moment they climb in, and keeps it until the changeover at midnight Pacific. The 3-player minimum doesn't apply to this pick. This is the only pick that isn't random, and random picks start at that changeover.

## The bedsheet (the ghost's side)

A new thing, `bedsheet`, placed in the ghost's inventory by code and removed at the next changeover. Inventories are private, so nobody else can tell who has it.

| When | Text |
| --- | --- |
| The ghost's next command after the pick | Something soft and faintly musty has appeared in your bag. It's a bedsheet with two eyeholes cut in it. You feel oddly… translucent. |
| The first ghost, added to the library discovery | As you climb in, something soft slides off a shelf and into your bag. It's a bedsheet with two eyeholes cut in it. You feel oddly… translucent. |
| `look_carried` | An old white bedsheet with two eyeholes cut in it, not quite level. It smells of cedar and something older. |
| `drop_fail` | The bedsheet clings to you. It isn't done with you yet. |
| `/use bedsheet` (room picker) | You pull the bedsheet over your head. Will anyone guess who you are? Which room will you haunt? Everyone there will see: A sheet-draped shape drifts through the door and whispers "…" (you'll write the whisper next). |
| Pop-up title | Haunt the [room name] |
| Text box label | What do you whisper? |
| Text box placeholder | Players will see: A sheet-draped shape drifts through the door and whispers "…" |
| Posted in the room | A sheet-draped shape drifts through the door and whispers "[the whisper]" |
| To the ghost, after posting | You drift into the [room name] and whisper "[the whisper]". |
| The old ghost's next command after the changeover | The bedsheet is gone from your bag. You feel a little more solid than you did yesterday. |

**Rules:**

- **Haunt as often as you like**, as in the Story Bible. The first haunting earns **Getting into the Spirit**.
- **Only rooms the ghost can reach** appear in the room picker: rooms open at the current drop, and the Secret Library only if the ghost has found it.
- **Whispers up to 300 characters** (config `haunt_max_chars`), so the frame stays readable in a thread. Discord itself would allow 4,000.
- **A whisper can't ping anyone.** It's posted with mentions turned off, so @everyone or a name in a whisper stays plain text.
- **Anonymous to players, not to admins.** Each haunting is logged in telemetry with its author, so an admin can find out who posted something unkind. The Story Bible said no moderation; this change was agreed 30 October.

## The spirit board (everyone else's side)

`/use spirit board` in the Secret Library replies privately with two buttons: **Ask the board** and **Name the ghost**. Each can be used once a day, separately.

### Ask the board: one letter a day

**The planchette circles the board once for each place in the name, then stops on a letter.** Circling three times and stopping on R means the third letter is R. The clues come only from the first word of the ghost's display name, and only its first 8 letters, so the planchette never circles more than eight times. Each player gets a place chosen from the day, the server and the player, so different players usually get different letters, and the name comes together when people compare notes.

| When | Text |
| --- | --- |
| A clue | You rest your fingertips on the planchette. It circles the board three times, slowly, then slides to R and stops. |
| The ghost asks | You rest your fingertips on the planchette. It slides to Y, then O, then U, and stops. You could swear the board is laughing. |
| The name has no letters in it | The planchette circles and circles and won't settle on anything. Whoever the ghost is today, their name doesn't spell. |
| Already asked today | The planchette won't move again. The board has said all it's going to say today. |
| No ghost today | The planchette rests on GOODBYE and won't move. The house is quiet today. |

**Which letters count.** Fold accented letters to plain ones (É is E). Skip anything that isn't A to Z until the first letter. The word then runs until a space or any other character that isn't a letter; hyphens and apostrophes are skipped without ending it. Only the first 8 letters of that word count. So "Kate (Ollie's mom)" gives KATE, "🌙 Jess | she/her" gives JESS, "Mary-Beth" gives MARYBETH and "O'Brien" gives OBRIEN. If the display name has no A to Z letters at all (all emoji, or a non-Latin script), use the ghost's Discord username the same way: usernames are only letters, numbers, dots and underscores, so "kate_s.92" gives KATE. Only if that has no letters either does the board give the won't-settle line. The count is written out: once, twice, three times, up to eight times. The reveal still shows the full display name.

### Name the ghost: one guess a day

The player picks a suspect from Discord's member picker.

| When | Text |
| --- | --- |
| Right | The planchette slides slowly across the board… and stops on YES. |
| Wrong | The planchette slides slowly across the board… and stops on NO. |
| Picked themselves | The planchette won't point back at you. Try someone else. |
| Picked someone who has never entered the house | The planchette doesn't move. That name means nothing to this house. |
| Already guessed today | The planchette won't move. The board seems tired. Try again tomorrow. |
| The ghost hasn't haunted yet today | You rest your fingers on the planchette, but it won't budge. Nothing has stirred in the house today. |
| No ghost today | The planchette rests on GOODBYE and won't move. The house is quiet today. |

Picking yourself or a non-player doesn't use up the day's guess, because Discord's picker can't hide those names. **Until the ghost has haunted at least once that day, Name the ghost refuses** with the won't-budge line before the picker opens, and the guess isn't used up, so a player who tries too early can come back later. Ask the board works all day either way. A right answer earns **Ghostbuster** the first time. It doesn't end the ghost's day: others can still guess, and the ghost keeps haunting.

### The board at drop 50

The new look and the two buttons replace the board's current drop 50 row, so its "isn't ready for you yet" use line goes:

- `look`: A varnished board printed with the alphabet, YES in one corner, NO in the other and GOODBYE along the bottom. The heart-shaped planchette never sits quite still.

## The reveal at changeover

**Decided 30 October:** before the new ghost is picked, the bot posts yesterday's ghost in the main channel, by display name, with no ping. **Amended 11 November:** a ghost who never haunted isn't named. The board posts the quiet-day line instead, so nobody is called out for a day they didn't play.

| When | Text |
| --- | --- |
| Someone named them | The planchette spells out a name: [name]. Yesterday's ghost has slipped out of their sheet. [n] of you named them. |
| Nobody named them | The planchette spells out a name: [name]. Yesterday's ghost has slipped out of their sheet, and nobody named them. |
| The ghost never haunted | Yesterday slipped by without a single haunting. The spirit board is keeping the name of whoever held the white sheet to itself. |

It gives each day an ending, lets players check their reasoning, and tells players who haven't found the library yet that there's a board to find.

## Achievements

- **Getting into the Spirit** (exists, moves from 99 to drop 50): haunt a room for the first time.
- **Ghostbuster** (exists, moves from 99 to drop 50): name the ghost correctly.
- **New, for the ghost who gets away with it**: *Boo Who?* Haunt at least 3 times in one day and have nobody name you. Unlock text: "Haunted the house all day, and nobody guessed it was you."

## For the developer

1. **Daily pick** at the Pacific changeover, after the reveal: store server, day, ghost, their saved display name and their username. Skip the day if fewer than `ghost_min_players` are eligible.
2. **The first ghost.** A server-level check alongside the per-player library discovery: has anyone on this server found the Secret Library yet? If not, the player climbing in becomes the ghost straight away, with no minimum player count, and the first-ghost line is added to their discovery text. They keep the bedsheet until the next changeover, when the reveal and the random picks begin.
3. **The bedsheet is placed and removed by code.** Add it to `PLACED_BY_CODE`. It's not droppable, `scatter_target` no, `cross_weight` 0, so the cat can't send it away and nobody can take it.
4. **`/use bedsheet`**: room picker, then pop-up, then the post in that room's thread with mentions turned off, capped at `haunt_max_chars`, logged in telemetry with the author.
5. **`/use spirit board`**: two buttons with separate once-a-day limits per player. The letter place comes from a fixed hash of day, server and player, so it can't be rerolled. Clues come from the first word of the saved display name, first 8 letters only, falling back to the username (rules under Ask the board). Name checks (self, non-player) happen before the guess is counted. Name the ghost refuses, without using the guess, until the ghost has haunted at least once that day.
6. **The reveal post** at changeover, before the new pick, with the count of correct guesses. If the ghost never haunted that day, post the quiet-day line instead, with no name.
7. **Achievement hooks**: first haunting, first correct naming, and Boo Who?, checked at changeover. Getting into the Spirit and Ghostbuster move from 99 to drop 50.
8. **New config**: `ghost_min_players` (3), `haunt_max_chars` (300).
9. **Raise the latest playable drop** to 50 in the drop 50 work order.

## Decisions

- [x] **Which drop?** 50.
- [x] **Allow the same ghost two days running?** Yes
- [x] **Post the reveal at changeover?** Yes
- [x] **A name for the new achievement**: Boo Who?, chosen 30 October.
- [x] **The 300-character cap and the admin log** both change the Story Bible's "no limit, no moderation". That's ok
