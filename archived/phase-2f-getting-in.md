# Phase 2f — Getting in, and the cat

## What 2f is

Two gaps that block launch, and one that does not.

**Nobody can get into the house.** Every room is a private thread the bot adds a player to on movement. A member standing in the Halloween channel is in no thread, has no player row, and has no command anyone has specified that would create one. `/initialize-haunted-house` builds the nine threads; nothing puts a person in the first one.

**Nobody knows the verbs.** There are three of them and no affordances. Discord will show a player that `/look`, `/take` and `/use` exist, but nothing tells them that `/use wide doorway` is how you walk, and that is the least guessable rule in the game.

**Ten illustrations exist and nothing points at them.** This part is not launch-blocking. It is in this work order because the delivery mechanism is a five-line decision that is annoying to retrofit and trivial to get right the first time.

**Two message shapes, added 28 September.** `/pet` and achievement unlocks both move to the same pattern: a private message carrying the detail, and a public one carrying the event. They are specified in their own sections below. Neither blocks launch in the way the first two gaps do, but both change strings the writers own, so they are cheaper to settle now than after the content is frozen.

### Prerequisites, all met

- The Halloween channel is recorded on the guild row at init — 2d
- Thread add/remove on movement, and the room `look` printed on arrival — 2c, shipped
- Per-player state written off a command branch — 2c.5, shipped. `tutorial_seen` is the same shape as `drawer_unjammed`
- Achievement embeds, which is what most of the art hangs on — 2d, in flight

## Getting in: `/enter`

**`/enter`, run in the Halloween channel.** Self-serve, so nobody has to be awake when a latecomer shows up on 14 October, and there is no reaction handler to build.

**This is a rename, not a new command.** `/enter-entryway` already exists, carried over from v1 and listed in the Functional Spec's command table as a player command whose only recorded change was that it no longer assigns a cohort. Nothing anywhere says what it does. So 2f does two things to it: shortens the name to `/enter`, and writes down the behavior below for the first time.

The shorter name is also the more accurate one now. `/enter-entryway` promises the Entryway every time, and the repair case below deliberately does not do that — an existing player lands back in whatever room they were in. A name that stops naming a room is the right name for a command that stops always going there.

What it does, for a member with no player row:

1. Create the player row. Current room `EN`, relationship 50, empty inventory.
2. Add them to the Entryway thread.
3. Print the Entryway `look` and its `Also here:` line in that thread — the existing arrival path, unchanged.
4. Post the tutorial (next section).
5. Reply in the Halloween channel, ephemerally, with a link to the thread.

For a member who **already has a player row**, `/enter` is a repair tool rather than an error: re-add them to their current room's thread, print that room, and say where they are. Someone will leave a thread by hand and need a way back, and this is cheaper than an admin command.

**"Their current room" can be empty, and this is the edge to get right.** `/pet` creates a player row for anyone who has never entered — v1 behavior, unchanged — so somebody can pet the cat in the Halloween channel, acquire a row and a relationship score, and still have never been in a room. When they later run `/enter`, the repair branch above has no room to send them back to. **Send them to the Entryway and run the full first-time path**: add them to the thread, print the room, fire the tutorial. The row already existing must not be read as "has already been inside".

Two refusals, both ephemeral: run outside the Halloween channel, point at the right one; run before `/initialize-haunted-house`, say the house is not open yet.

**Beside it, a pinned post** in the Halloween channel: what the house is, that `/enter` gets you in, and that everything after that happens in your own threads rather than in the channel. This is the only place a player reads anything before they are inside, so it is worth a writer's attention.

## First contact

Arrival already prints the room. What is new is one message after it, in the same thread, **once per player**, gated on a stored `tutorial_seen` flag.

It teaches three verbs with three examples, and every example must work on day 1 against the launch content:

- **`/look coat rack`** — look closely at anything the room mentions
- **`/take cat food`** — pick things up. The salmon stash behind the coat rack is the only takeable thing in the Entryway on day 1, and pointing at it early is not an accident
- **`/use wide doorway`** — how you walk. Use the exit's own name, which is what the listing shows; never the room it leads to

Three things the tutorial must not use as examples: the spice jar (arrives by restock on day 2), the main staircase (refuses until it is repaired), and anything the player has to already be carrying.

**The tutorial is not gated on petting the cat.** A tutorial a player only sees if they happen to find the cat is a tutorial some players never see. It also no longer needs to teach `/pet` at all. The public line the pet command now posts does that job by itself: the first time any player or admin pets the cat, everyone in the room reads that somebody did, and the command introduces itself. Eunoia still belongs in the welcome, but as the thing the art carries rather than as a fourth bullet.

## Eunoia is everywhere

Settled 28 September: **Eunoia is functionally omnipresent.** Every player has the cat with them in every room. This is the same shape as `alexa`, which already carries `room_id = ALL` in `things.tsv`.

Two consequences, both simplifying:

- `/pet` needs no location check and no roaming scheduler. It always resolves, in all nine rooms, including the Secret Library, and in the Halloween channel as well.
- Nothing about the cat has to be stored per room. The relationship meter is per player and that is the whole model.

**The bot is Black Cat.** Every message a player receives comes from her, under her name and her avatar. That is already true of the text the writers have produced — "You pick the bottle up. Somewhere, a cat is deprived of something to knock over" is the cat narrating you to yourself, and it reads correctly now that we know who is speaking. It also settles the tone of the welcome: the house is not introduced by a disembodied game, it is introduced by the cat who lives there. Nobody needs to explain why she is in every room at once; the pinned post can wave at it and move on.

**She has no row in `things.tsv` today.** Settled 28 September — add one: `room_id = ALL`, `type = fixture`, `takeable = no`, aliases `eunoia|cat|kitty|black cat`. It costs one line, gives the writers a `look` and a `use` they can write like any other thing, and makes `/look cat` work, which players will type within the first ten minutes.

### The row

| Column | Value |
| --- | --- |
| `thing_id` | `eunoia` |
| `name` | cat |
| `aliases` | `cat\|black cat\|kitty\|kitten\|eunoia` |
| `type` | `fixture` |
| `room_id` | `ALL` |
| `quantity` | 1 |
| `takeable` | no |
| `droppable` | yes (meaningless on a fixture; matches `alexa`) |
| `cross_weight` | 0 |
| `since_drop` | 1 |
| `sort_order` | 0 |

Everything else is blank. `alexa` is the existing precedent for `room_id = ALL` and the row should look like it.

**`room_id = ALL` means the `look` has to resolve in all nine rooms, not just the room the loader happens to place her in.** This is the part to watch: `alexa` is the only other `ALL` row and nobody has yet had to prove that resolution treats it as "everywhere" rather than as an unrecognised room id. `/look cat` must work in the Entryway, the Courtyard and the Secret Library alike, and so must `/pet`, which is the same lookup. If the loader currently drops rows whose `room_id` is not in `rooms.tsv`, `alexa` is already broken and nobody has noticed — worth checking before writing the row rather than after.

She is a fixture and so never appears in an `Also here:` line, which is correct: she is not a thing you find, she is a thing that is there.

### Prose

Three cells for `thing_text.tsv`, all on `state = default`, `since_drop = 1`. **Her name appears in none of them**, deliberately: the player learns it from the tag on the cat collar in the Bedroom, and a `look` that opened with "Eunoia" would spend that discovery on the first room anybody walks into.

The other constraint is the `ALL` placement. None of these can mention a floor, a rug, a chair or a window, because she reads the same in the Courtyard as in the Nursery.

**`look`**

> You look down to find a sleek black cat winding between your feet, rubbing on your legs with affection. She looks up at you with moonbright yellow eyes.

**`take_fail`**

> You get both hands under her. She becomes, in the way of cats, considerably longer and heavier than she looked, and is back where she started before you have finished deciding against it.

**`use_fail`**

> Whatever you were trying to do, it is not happening. You could always try petting her.

The `use_fail` is doing a second job. Since the tutorial no longer teaches `/pet`, this is the other way a player finds the command — they type `/use cat` because it is the verb they know, and the refusal hands them the right one. Worth keeping that last sentence even if the rest is rewritten.

The other half of the fiction — Eunoia in the far dimension, batting objects and notes across — is the cat crossing mechanic, and that is post-launch. Three achievements are blocked on it. Nothing in 2f builds it, but the welcome copy should leave room for it rather than describing a cat who is only ever here.

## Refining `/pet`

Settled 28 September. The response blurbs are already in the repo; what changes here is the shape of the reply, not that text.

**One command, two messages.** The private one is the interaction response, ephemeral, and carries the full blurb. The public one is a separate send into wherever the command was run — the player's current room thread, or the Halloween channel when they pet from there:

> `{player}` pets the cat. The cat seems to like it.

> `{player}` pets the cat. The cat does not seem pleased.

**Petting from the Halloween channel.** `/pet` resolves there as well as in the nine room threads, and that is what makes the discovery argument work: an admin can pet the cat in the channel on day 1, before a single player has run `/enter`, and everyone watching learns the command exists. The public line posts in the channel in that case rather than in a room.

Two things follow. **A member with no player row can run it.** v1 already creates the player row on a pet, and that behavior stands: the blurb fires, the public line posts, the relationship meter starts, and the pet counts. No change, and no nudge toward `/enter` is needed, because by then they are already a player. It does leave one edge the next section has to handle. **And once a player does have a row, a pet from the channel counts exactly like a pet from a room:** same meter, same tally toward *Making Friends*, same crowding window. One command should not mean two things in two places.

**The pet count comes out of the private reply.** Progress toward *Making Friends* lives in `/stats` and nowhere else. Two hundred is better as a surprise than as a countdown, and a visible counter turns petting a cat into filling a progress bar.

**Crowding.** Ten or more pets by the same player within a rolling ten minutes appends *Maybe you should give the cat some space* to the private reply. The public line is unchanged — the nudge is between that player and the cat, and broadcasting it would make it a scolding.

**Where the strings live.** Four new keys in `defaults.tsv`: `pet.public.positive`, `pet.public.negative`, `pet.public.continues`, `pet.crowding`. They use the existing `{player}` token, the same one `move.depart` and `move.arrive` already substitute — do not mint a second token for the same thing. The blurbs stay where they are in the repo, but pet text living half in `defaults.tsv` and half in code is worth revisiting after launch.

**What decides the public branch — needs a decision.** Recommend reading the relationship meter *after* the pet: above zero prints "seems to like it", zero or below prints "does not seem pleased". That is the boundary already settled for *Making Friends* and *Trying to Make Friends*, so the game has one rule instead of two. The alternative is to report whether this particular pet moved the meter up or down, which is a truer account of the moment but means a player deep in the positive can be publicly told the cat was displeased, which reads as a bug rather than as characterization.

**The volume problem.** *Making Friends* wants 200 pets. If every one posts publicly, a determined player puts 200 messages into a shared room thread, and the line is wallpaper by the twentieth. Settled 28 September, and the whole rule is three lines:

1. Rate-limit the public line to two per player, per room, per thirty minutes
2. The first public line in a window reads normally. The second reads only `{player}` continues to pet the cat.
3. After that, nothing in public until the window resets. The private blurb keeps firing and every pet still counts

**The window opens on the first public line, not on the first pet.** Two get through, the rest are silent, and thirty minutes after that first line the counter clears and the next pet is public again as a normal first line. Anchoring it to the first message rather than rolling it keeps the rule explainable and means a player can never be surprised by which line they get.

**The bucket is the member and the place.** Two people in the same room each get their own two. One person moving between rooms gets two in each, which is intended — they are different audiences. **The Halloween channel is its own bucket**, a tenth alongside the nine rooms.

**It does not touch the crowding nudge.** That is a separate window — ten pets in ten minutes, appended to the private reply — and the two should stay separate rather than being folded into one timer. They answer different questions: one is about noise in a shared room, the other is between a player and the cat.

A fourth string joins the three above: `pet.public.continues`, defaulting to `{player} continues to pet the cat.`

This is the same argument as the art section below, and it applies for the same reason: a message that fires constantly stops being content and becomes noise.

**New storage.** A rolling window of pet timestamps per player. That is the same shape as *A Little Bit Lost*, which already needs room-entry timestamps over a five-minute window, so the two can share one table rather than inventing a second.

## Announcing an achievement

Same two-message shape as `/pet`, and the same reason: the earner gets the detail, the server gets the event.

**Private, to the earner:**

> You earned **Found the Specs**: Find David's reading glasses in the desk

**Public, in the Halloween channel:**

> Qaruse earned **Found the Specs**

The public line prints the member's **display name as plain text and does not ping them**. Set `allowed_mentions` to parse nothing on that send, so a display name that happens to contain something mention-shaped cannot turn into a ping.

**The description always exists.** Every one of the thirty-five rows in `achievements.tsv` has an `unlock` string; that column is exactly this text. What varies is not whether there is a description but whether there is anywhere private to put it.

**Settled: secret achievements announce publicly like any other.** *Out on a Limb* in the Halloween channel tells the server there is a tree worth climbing, and that is wanted — the nudge is the feature. The public line carries the name only, never the description, so it points without explaining. Eighteen quiet hints spread across October, each one arriving because somebody actually found something.

### The three cases with nowhere private to reply

An ephemeral message needs an interaction to answer, and two achievements are not triggered by one:

| Achievement | Hook | Why there is no interaction |
| --- | --- | --- |
| *Met the Craving* | `on_reaction` | A reaction is not a command. Discord hands the bot an event, not a token to reply to |
| *Passing a Message to David* | `on_message` | A plain message in the channel, same problem |
| anything on `on_midnight` | scheduler | Fires on a timer, and the player is very likely offline |

**Settled 28 September: no DM. These get the public line only.** The private message is simply skipped when there is no interaction to answer, and nothing else changes — the public announcement posts in the Halloween channel exactly as it does for the other thirty-two.

This is the right trade. A bot DM needs a delivery path that can silently fail, a member setting nobody controls, and a second message format to maintain, all for two achievements. The cost is that *Met the Craving* and *Passing a Message to David* never show their earner the description — acceptable, since both are things the player just deliberately did, and the achievement name lands while they still remember doing it.

### The three group achievements have no earner

*Strength in Numbers*, *Making a Mess* and *The Feline Collection* are earned by the server, not a person, so "Qaruse earned" is the wrong sentence and there is nobody to send a private line to. Settled 28 September: a public line only, naming the server itself:

> Halloween in June earned **Making a Mess**: Amassed 200 things into a single room

The name substituted is the Discord server's own, via a `{server}` token — so the line reads differently on every server that runs the house, which is the point. And since there is no private message here, the group line is the one place the description belongs in public.

### Where the strings live

Three new keys in `defaults.tsv`, using the existing `{player}` token and three new ones — `{achievement}`, `{description}` and `{server}`, the Discord server's own name:

| Key | Default |
| --- | --- |
| `achievement.private` | You earned **{achievement}**: {description} |
| `achievement.public` | {player} earned **{achievement}** |
| `achievement.public.group` | {server} earned **{achievement}**: {description} |

## The art set

Ten images, one visual language: flat black cat, gold eyes, gold accent marks, transparent background. They read at Discord embed size, which is the test that matters.

**The rule the table follows, settled 28 September: art fires on things that happen, never on a state that can flip.** After the 28 September pass, that means achievements and almost nothing else: an achievement has a before and an after, and an image marks it once. A relationship score or a craving guess is a value that can go back the other way an hour later, and an image that blinks on and off with it stops reading as a reward and starts reading as a status bar. The crowding nudge is the one non-achievement trigger, and it qualifies on the same test: the player caused it, and it has a moment.

| `art_id` | What it shows | Where it goes |
| --- | --- | --- |
| `eunoia_icon` | Round face, two gold eyes, small fangs, level gaze | The bot's avatar. It is already beside every message she sends, so it is never also an embed image |
| `eunoia_alert` | Standing, narrowed eyes, tail curled up, one gold sparkle | The welcome message, and the first `/pet` |
| `eunoia_content` | Sitting, paw raised mid-groom, eyes shut, sparkle marks | Earning *Making Friends*; *Cat's Best Friend* |
| `eunoia_disdain` | Head tipped back, eyes slitted, pointedly looking away | Earning *Trying to Make Friends* |
| `eunoia_suspicious` | Glancing back over the shoulder, gold arrow | The crowding nudge — ten pets in ten minutes |
| `eunoia_happy_bowl` | Crouched at a green bowl, eyes closed in arcs, gold heart | Earning *Met the Craving* |
| `eunoia_gorging` | Face down in a heaped bowl, swirling eyes | The cat-food achievements: *Charcuterie Board*, *Bulk Buyer*, *The Feline Collection* |
| `eunoia_sniffing` | Crouched low over something pale, stink lines rising | Earning *Follow Your Nose*, and a player's first ever look at a dirty diaper |
| `eunoia_bottle` | A baby bottle knocked over between her paws, caught glaring | Earning *Catproof the House*; later, cat crossing |
| `eunoia_startled` | Arched back, spiked fur, huge round eyes, exclamation mark | Earning *Getting into the Spirit* |

`eunoia_icon` is the only one that is not a scene, and it is doing a different job from the other nine: it is Black Cat's face on every message in the game. Set it as the bot's avatar at install and never send it as an embed image — an avatar and a thumbnail of the same face, six pixels apart, looks like a mistake.

`eunoia_content` and `eunoia_disdain` are a matched pair and should be used as one. They are the two endings of the relationship arc and they read against each other. Settled 28 September: neither fires on the meter crossing zero. A score that can swing back and forth would make them blink on and off, and an image that comes and goes stops meaning anything. Both fire on their achievement and nowhere else, which is once per player, permanently.

`eunoia_suspicious` is the one image tied to something other than an achievement, and it is worth the exception: the over-the-shoulder look is exactly what *give the cat some space* means, and it fires on a condition the player caused and can stop causing. It rides the private reply, never the public line, for the same reason the crowding text does — the nudge is between that player and the cat.

`eunoia_sniffing` has the only trigger in the table that needs storage nobody has built: **a player's first `/look` at a dirty diaper**. Store it as a single named per-player flag, `diaper_seen`, the same shape as `tutorial_seen` and `library_found`. Do **not** build a general "has this player seen this thing" table — 2d deliberately dropped `player_thing_seen`, and one boolean for one image is not a reason to bring it back.

It fires on the look whether the diaper is on the floor or already in the player's bag, and it fires once, ever, not once per diaper. Eight diapers a day scatter across the house; the joke is only funny the first time.

**One image ships with nothing to fire on.** *Getting into the Spirit* is blocked on the ghost system, which is not built, so `eunoia_startled` has no live trigger in Release 1. Upload it at init with the rest and leave it unused rather than pulling it out of `art.tsv` — the row costs nothing and the image is there the day the ghosts land.

The cat's mood between those two endings is still visible — it lives in the public pet line, which reads *seems to like it* or *does not seem pleased* off the meter every time. Text can flicker with the score without costing anything. Art cannot.

## How images are delivered

**Upload once, reference by URL forever.**

At `/initialize-haunted-house`, the bot posts each of the ten files once — to the Halloween channel, or to a hidden assets channel if you would rather they not be visible — and records the returned CDN URL against its `art_id`. Every send afterwards sets `embed.image.url` (or `embed.thumbnail.url` for the icon) to the stored string. No re-upload, no attachment payload, no rate-limit cost per message.

This wants an eleventh content file, `art.tsv`: `art_id`, `file`, `alt`, `notes`. Structure rather than text, except `alt`, which is writers' work and which matters more than usual because a black cat on a transparent background is invisible to a screen reader and nearly invisible in some Discord themes.

Two rules for the send path: **one image per embed**, since Discord allows a single `image` plus a single `thumbnail`; and **a missing image degrades to text**. If a URL ever 404s, the message still sends. Nothing in the game is load-bearing on a picture.

## Where art must not appear

- Room `look` and the `Also here:` line
- Ordinary `/take`, `/drop` and `/use`
- Public movement lines in a room thread
- Any refusal, any cooldown message
- Every `/pet` — *Making Friends* wants 200 of them. The cat's art appears when an achievement lands, never on an ordinary pet

The reason is one sentence: an image seen twice a minute stops being a reward and becomes latency. The entire value of this set is that each one marks something, and that value is spent the moment the images become wallpaper.

## What 2f does not do

- **No cat crossing.** Eunoia is here, in all nine rooms. The far dimension is post-launch
- **No roaming.** She is everywhere, so there is nothing to schedule and no "where is the cat" state
- **No new art.** Ten images is the set for Release 1
- **No animated or per-flavor variants**
- **No change to thread membership.** `/enter` uses the existing add path
- No hint system beyond the one tutorial message. A player who never types `/look` is not rescued

## Definition of done

- The command is registered as `/enter`, and `/enter-entryway` no longer exists — one command, not two
- `/enter` in the Halloween channel puts a brand-new member in the Entryway thread, creates their player row, and prints the room
- `/enter` by an existing player re-adds them to their **current** room, not the Entryway, and says where they are
- `/enter` outside the Halloween channel refuses with a pointer to the right channel
- `/enter` before initialization refuses cleanly rather than erroring
- The tutorial fires exactly once per player and never again, including after a re-`/enter`
- All three tutorial examples work against the day-1 content, verified by running them
- `/pet` resolves in all nine rooms with no location check, Secret Library included
- `/look cat` prints something rather than falling through to `unknown.noun`
- All ten images upload once at init; no message re-uploads a file
- `eunoia_icon` is set as the bot's avatar, and appears nowhere else
- No image appears on a room look, a movement line, an ordinary verb, or a refusal
- A deliberately broken image URL still sends the message
- A player whose row was created by petting in the channel, and who has never been in a room, lands in the Entryway on `/enter` and gets the tutorial
- `/initialize-haunted-house` posts nothing in the channel; the welcome resolves from `defaults.tsv` and an admin posts it when the game opens
- `/enter` posts *{player} has discovered a house...and disappears inside* in the Halloween channel, display name as plain text, pinging nobody

And for `/pet`:

- The private reply carries the blurb, and no pet count appears anywhere in it
- One public line posts wherever the command was run — the room thread, or the Halloween channel — naming the player and the cat's reaction
- The tenth pet within ten minutes appends the crowding line, and so does the eleventh
- The crowding line never appears in the public message
- All three new strings resolve from `defaults.tsv` with `{player}` substituted, and none is hard-coded
- Two hundred pets still earn *Making Friends*, crowding nudges notwithstanding
- `/pet` works in the Halloween channel, and a member who has never run `/enter` gets a player row from it, exactly as in v1
- A third pet within thirty minutes in the same room posts nothing publicly, while its private reply still fires
- The second public line reads `{player} continues to pet the cat.` and nothing else
- Thirty minutes after the first public line, the next pet is public again as a normal first line
- Moving to another room gives that player a fresh two, and the Halloween channel is its own bucket
- Every public action line is present tense
- The crowding reply carries `eunoia_suspicious`, and that image appears nowhere else
- No image is attached to the relationship meter itself, in either direction

And for achievements:

- Earning one sends the earner a private line carrying both the name and the description from `achievements.tsv`
- The public line posts in the Halloween channel, prints the display name as plain text, and pings nobody
- A display name containing mention-shaped text still does not ping
- Achievements with no interaction to answer — the two named above, plus anything on `on_midnight` — post their public line, send no private message, and never attempt a DM
- The three group achievements announce publicly naming the server rather than a player, carry the description, and send no private line
- All four strings resolve from `defaults.tsv`
- `things.tsv` carries the `eunoia` row, and `/look cat` returns her `look` in all nine rooms — tested in the Entryway, the Courtyard and the Secret Library, not just one
- `/take cat` and `/use cat` return her own refusals rather than the house defaults
- No cat text anywhere names her, outside the collar's tag in the Bedroom

## Open questions

**Settled 29 September: no, `/initialize-haunted-house` does not post the pinned welcome.** Posting it automatically would guarantee it exists and is correct, but it puts writer copy inside an admin command where nobody would think to update it — and, more usefully, separating the two lets the house be built days before the game opens. The copy lives in `defaults.tsv` and an admin posts it when the game actually starts.

Two consequences worth writing down.

**Initializing is no longer the same as opening.** The admin can run `/initialize-haunted-house` on 29 September and post the welcome on 1 October, which is the point — but `/enter` works the moment the threads exist, so anyone who knows the command is in early. That is probably fine for a private server. What is not obviously fine is the clock: restocks are specified as *day 2, every third day after*, and drops key off the same calendar. Day 2 of what — initialization, or the welcome post? If it is initialization, a house built two days early has spice jars in the Amazon box before anyone walks in, and *Something's Cooking* is reachable on the real day one. Pick one and say so in `server_config`.

**The welcome copy will not fit a `defaults.tsv` cell comfortably.** Every value in that file today is a single line, and this one wants paragraphs — what the house is, that `/enter` gets you in, that the rest happens in your own threads. TSV cells do not hold newlines. Either the loader learns one escape (`\\n` expanded on read, documented in the Content Schema) or the copy is split across numbered keys (`welcome.1`, `welcome.2`, …) that the admin command joins. The escape is cleaner and will be wanted again the first time any other long text shows up.

**Settled 29 September: `/enter` announces publicly.** The line, posted in the Halloween channel: "{player} has discovered a house...and disappears inside." It builds the sense of a group going in together and gives latecomers a working example of the command, which is worth more than the quiet entry it costs.

**Owned 29 September: the nine scene images get checked on a phone during pre-launch testing.** The icon was drawn to work small. The other nine are full-body and go in the embed body, where they have room — but Discord will also show them scaled down on mobile, and the thin gold linework is the part most likely to disappear. It is on the test pass rather than the build, so nothing is blocked on it — but if the gold goes invisible at phone scale it is a redraw, not a code fix, which is why it wants looking at before 1 October rather than after.

**Settled 29 September: the crowding window nags and enforces nothing. Pets keep counting toward *Making Friends*.** It is a hint, not a limit: it exists to stop a player damaging their relationship with the cat without realising that is what rapid petting does. A hard stop would turn a 200-pet achievement into a scheduling exercise, and the mechanic it is warning about already supplies the consequence.

**That consequence is not written down anywhere.** The whole point of the nudge is that rapid petting costs a player relationship score, but the Functional Spec names the relationship meter exactly once, in a list of what persists, and states no rule for what moves it in either direction. It presumably lives in the v1 code. Somebody should confirm the penalty actually exists before launch, because a warning about a consequence the game does not apply is worse than no warning — and if it does exist, the rule belongs in the spec beside the meter.

**Does the public pet line need rate-limiting before launch?** Covered above. It is the one decision in this section that gets harder to change once players have seen the current behavior, because taking a public line away reads as a takeaway.

