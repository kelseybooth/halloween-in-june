# Room text rewrite (drops 30–50)

Oct 30, 2026 · @Qaruse

Shorter descriptions for the eight rooms after the Entryway, at about four fifths of today's length on average. The four drop 30 rooms (Dining Room, Kitchen, Courtyard, Living Room) were approved and written to the files on 30 October, and split across two drops on 31 October: the Dining Room and the Kitchen open at **25**, the Courtyard and the Living Room at 30. The other four are still drafts. Each one still names everything the engine won't list, and all eight pass the developer's content checker.

## The drafts

**Bold shows exactly what the engine would bold**, simulated with the developer's own marking code at the drop each room opens. A bold word is a thing a player can type and use. Everything plain is scenery in the prose only. Revised 30 October: each room's way out is now a glimpse of what's beyond it, like the Entryway's doorways, instead of a label.

| Room | Opens | Draft, as the engine would bold it | Length vs today |
| --- | --- | --- | --- |
| Dining Room | **25** | Two **dining chairs** are pushed back from a **long table**, with a **high chair** beside. A **candy bowl** and a **vase of flowers** stand on the **sideboard**, under **tall windows** onto an overgrown garden. Through the **arched doorway** you can see a crowded coat tree, and a **swinging door** lets through the hum of a fridge. | 82% |
| Kitchen | **25** + 30 | A big old-fashioned kitchen. A **pasta pot** sits on the **cast-iron stove**, a **drying rack** stands empty by the **kitchen sink**, and a **Keurig** waits with a clean mug. The **fridge-freezer** hums beside the **trash can**, a **cake box** sits at the end of the **counter**, and the **pantry** door is ajar. A **swinging door** shows a sliver of a long table each time it moves. *[fragment 1, drop 30:]* Through the glazed **back door** there are steps, then tangled green. | 61% |
| Courtyard | 30 | An overgrown sunken courtyard. **Ivy** swallows the side of the house, and a **stone wall** enclosed **herb garden** has run wild beside a **watering can**. A **picnic blanket** is spread over a **stone bench**. In the middle, a **stone circle** holds the last of a chalk diagram. An autumn-bronzed **oak tree** crowds the far wing of the house. **Pumpkins** wait by the kitchen steps next to a **cat bowl**, and at the top, the **back door** glows warm and smells faintly of coffee. | 85% |
| Living Room | 30 | A room for long evenings: a deep **sofa** with a **baby blanket**, two **armchairs****,**** b****ookshe****l****v****e****s** and a **fireplace** full of cold ash. One armchair has been turned to face a **bare patch of wall**. A stack of **board books** sits on the **rug**. A tall **curiosity cabinet** stands in the corner. Through the **wide doorway** you can see the foot of a staircase and a pile of shoes. | 91% |
| Upstairs Hallway | 40 | A long hallway hung with **faded portraits** of nobody who lives here. A **roll-top desk** stands half closed and beside it looms an **oak wardrobe**, with a **small crowbar** on the floor. **Baby clothes** are drying over the railing, and a **cat bowl** sits at the top of the **g****r****and ****staircase**, which sweeps down to the front door far below. A **paneled door** stands half open on the corner of an unmade bed, and a **sage door** hums softly with white noise. A bad smell lingers in the air. | 70% |
| Bedroom | 40 | The main bedroom: an **unmade bed**, a **dresser** with its drawers half open, and a **tall mirror** above it that catches the light at odd angles. A **bottle warmer** sits on the **nightstand**. In the corner, a **moving box** labeled HALLOWEEN overflows with a **welcome mat** and a tangle of **fake spider web**. A **tin of graphite powder** sits open by the **window**. The **paneled door** stands half open on a row of faded portraits. | 89% |
| Nursery | 40 | A small, warm room painted sage green. The **crib** is made up under a slowly turning **mobile**, with a **shelf** above it, out of reach of anybody small. On the **changing table**, a **baby monitor** crackles with faint, happy sounds, though the crib is empty. Through the **sage door**, open a crack, you can see baby clothes drying over a railing. | 73% |
| Secret Library | 50 | A close little library with packed **library shelves**. A **scorch circle** is burned into the floorboards, with a **coil of copper wire** among the things scattered around it, and a **spirit board** lies just outside it. An **empty cat bed** sits in the corner. The air feels charged, like the moment before a storm. The back of a **heavy cabinet** fills one wall, a keyhole set at waist height, and behind the shelves a shaded **library window** stands open a crack. | 80% |

**How to read the plain words:**

- **Glimpses through doors stay plain** because the thing belongs to the next room: the coat tree from the Dining Room, the long table from the Kitchen, the unmade bed from the hallway.
- **Both secret ways in are bold from drop 30.** Changed 30 October: the *curiosity cabinet* and the *oak tree* now exist as things from drop 30, so the engine bolds them from the start. Until drop 50 the cabinet answers "Locked." and the oak refuses with a new line: "You get a hand on the lowest branch and pull. It creaks, and so do you. You let go and decide the oak can keep its secrets for now."
- **A second mention stays plain:** "the crib is empty", "one armchair".
- **The name wins over its own alias:** the Kitchen bolds **pantry**, not "pantry door".
- **Words with no thing behind them stay plain:** the garden view, the railing, the papers, the chalk diagram, the white noise.

**One content change these need:** the upstairs bedroom door's two exits need the alias `paneled door`, in American spelling. The bedroom's exit has `panelled door` today, and the hallway's exit has neither.

**Done 30 October:** both exits now answer to `paneled door` in `things.tsv`. The bedroom's exit keeps `panelled door` too, for anyone who types it that way.

Back stairs deleted 30 October, so the Upstairs Hallway draft needs no back-stairs sentence and no unrepaired version. All eight still pass the developer's content checker, with and without the back stairs.

## Board books in place of the soft blocks (draft)

**The board books replace the soft blocks in the Living Room.** The lines name real board book classics and describe reading them, but don't quote them: *Goodnight Moon* and *Little Blue Truck* are still under copyright, so their text can't go in the game. The soft blocks carried one story clue, the baby's name spelled out as MARCUS. That moves to the inside cover of the top book.

| Field | Draft |
| --- | --- |
| `thing_id`, name | `board_books`, board books (replacing `soft_blocks`) |
| aliases | board books, board book, baby books, picture books, stack of books. Not "books" on its own: the bookshelves already answer to it, so a player typing "books" would be asked which one |
| `look` | A stack of chunky board books on the rug, their corners soft from chewing. *Goodnight Moon* is on top, then *Little Blue Truck*, then *The Very Hungry Caterpillar*, with a single-toothed bite mark on it that no caterpillar made. Inside the front cover of the top one: "For Marcus, June 2026". |
| `use` | You pick up *Goodnight Moon* and open it to the first page. Before the end of the first line you're reading in the slow, hushed voice it seems to ask for. You close it gently and put it back on top. |
| `take_fail` | You could tuck one under your arm, but they belong here, in a heap within reach of somebody small. |

**More `use` lines, if the engine can rotate them.** Today a thing has one `use` line. The toys already rotate through numbered lines, so the same could work here:

1. You open *Little Blue Truck* and start reading aloud. You get as far as the first beep before you realize you've done the sound effect yourself, to an empty room. The cat looks impressed, or possibly concerned.
2. You open *The Very Hungry Caterpillar*. The holes in the pages have been widened by small fingers, and one by something with sharper teeth. You read the first page and put it back.
3. You pick up *Brown Bear, Brown Bear, What Do You See?* and read the first page out loud. The rhythm settles into your head and stays there for the rest of the afternoon.
4. You find *Guess How Much I Love You* at the bottom of the stack and read the first page before you have to stop and put it down for a minute.

**Elsewhere it touches:**

- **Living Room draft:** "**Soft blocks** are scattered across the **rug**" becomes "A stack of **board books** **sits on the rug", or any wording** that says *board books*.
- **Ladder, Living Room climb:** "the soft blocks on the rug spelling out their half a word" becomes "the board books in a heap on the rug".

## What the drafts keep

- **Every fixture is still named.** The loader fails if a fixture isn't named somewhere in its room. A few minor ones were already named in another thing's look, so the drafts drop them from the room text: the legal pad, the cookie cutters, the laptop, the pacifier, the door-hardware manual and the cracked mirrors.
- **Names that bold.** Each thing appears under its `things.tsv` name or a multi-word alias, so the engine bolds it. Examples: *candy bowl*, *fridge-freezer*, *tall mirror*, *moving box*.
- **Hidden things stay hidden.** The cat food stashes, the to-do list, the journal page and the chocolate book are named in the looks of what holds them, not in the room text.
- **No loose objects.** Things players can carry, like the silver spoon, the candle stub, the cat collar and the music box, show in the Also here list instead.
- **The detail moved, not lost.** Story detail such as the high chair's dried sweet potato and the Keurig's pods still lives in each thing's own look. The nursery's white-noise hum moved into the hallway text, where it's the glimpse of the nursery door.
- **Checked.** All eight drafts pass the developer's content checker, with and without the back stairs.

## Deleting the kitchen back stairs

**It's a small cut, and it makes the repaired grand staircase the only way upstairs.** Today the back stairs (`KH` and `HK`) open at drop 40 and run from behind the pantry door to the Upstairs Hallway. Deleting them changes:

| What | Change |
| --- | --- |
| `things.tsv`, `thing_text.tsv` | Remove the `KH` and `HK` rows |
| Kitchen room text | The current text mentions "a narrow back staircase" behind the pantry door. The draft above already leaves it out |
| Upstairs Hallway room text | Its "default" version describes the main staircase as still broken. Upstairs is only reachable before the repair through the back stairs, so without them that version can never be seen. Keep only the repaired version, which the draft above replaces |
| `HE` (main staircase, from upstairs) | Its default row ("Not this way. Not yet.") becomes unreachable for the same reason. Keep only its repaired row |
| `drops.tsv` | Drop 40's notes mention "the stairs and back stairs" |
| Story Bible | Its staircase section says players reach upstairs by the back stairs until the repair, and warns that a small server might never finish the repair. The kitchen and hallway sketches and their exit lists also name the back stairs |

**What players notice:** getting from the kitchen to the upstairs takes three moves (kitchen, dining room, Entryway, then up) instead of one. No achievement, quest or restock uses the back stairs. The real cost is the Story Bible's original reason for them: without them, a server that never finishes the repair never gets upstairs. Since drop 40 already waits for the repair and an admin, and staircase\_planks can be lowered for a small server, that safety net is already covered.

**One cleanup either way:** the staircase is called *grand staircase* in the Entryway but *main staircase* from upstairs. Renaming `HE` to "grand staircase" would make the same thing answer to the same name on both floors.

## The new cat bowls

**Added 30 October:** a cat bowl in the Courtyard (drop 30) and one in the Upstairs Hallway (drop 40). They're in `things.tsv` and `thing_text.tsv` now. Until the room text above is approved, each room's current text ends with one sentence naming its bowl, so the loader passes.

| Bowl | Look (approved) | Take refusal (approved) |
| --- | --- | --- |
| Courtyard | A tin bowl at the foot of the kitchen steps, rained in and dried out more than once. Somebody keeps it clean anyway. | It is hers, it lives out here, and she would notice. |
| Upstairs Hallway | A small blue enamel bowl at the top of the stairs, set on a folded towel to keep it off the floorboards. | It is hers, it lives on this floor, and she would notice. |

**Feeding doesn't work at them yet.** Every cat food's `requires` names the Entryway bowl's id, `cat_bowl`. The developer needs to let any cat bowl meet that requirement, for example by matching on the name "cat bowl". Otherwise a player in the courtyard with salmon still hears that they need a bowl.

## The bedroom window and the ivy (approved 30 October)

**Graphite unsticks the bedroom window, and the ivy outside becomes a way between the bedroom and the courtyard.** The tin on the sill is the hint and the fix in one: take some powder, use the window, and it slides up. After that the ivy works in both directions for that player. Approved and written to the files on 30 October.

### The window (`bedroom_window`, drop 40)

The window gets `requires graphite_powder`, so without powder the player hears the `use_fail` and with it the `use`.

| State | Field | Draft |
| --- | --- | --- |
| default | `use_fail` (no powder) | You try the sash. It rises about half an inch, sticks, and settles back down as though it never moved. The runners look like they need something to help them along. |
| default | `use` (with powder) | You rub graphite into the runners and try the sash again. This time it slides up smoothly, all the way, and cool air comes in off the courtyard. You lean out. The ivy has climbed right up to the sill here, thick as rope and woven tight against the wall, all the way down to the grass below. It looks quite strong, but are you really considering it? |
| window\_open | `look` | The sash window, pushed all the way up, with the courtyard below and the ivy thick around the sill. |
| window\_open | `use` and `use_fail` | You lean out over the courtyard again. The ivy below the sill is thick enough to climb. |

The default `look` and `take_fail` stay as approved. The `use_fail` is today's use line with "a centimeter" changed to "half an inch", plus a nudge toward the runners. The open window's line goes in both `use` and `use_fail` so it reads the same with or without powder in hand.

### The ivy from the bedroom (new exit `BC`, drop 40)

Name **ivy**, aliases ivy, vines, creeper. Room BE, destination CO.

| State | Field | Draft |
| --- | --- | --- |
| default | `look` | Ivy, pressed against the outside of the glass. |
| default | `use_fail` | The ivy is outside, and the window between you is stuck shut. |
| window\_open | `look` | Ivy as thick as rope, climbing right up to the open sill. |
| window\_open | `use` | You swing a leg over the sill, find the ivy with your foot, and climb down hand over hand to the courtyard. It holds the whole way. |
| window\_open | `move_depart` | {player} climbs out of the bedroom window and down the ivy. |
| window\_open | `move_arrive` | {player} climbs down the ivy from the bedroom window above. |
| default | `take_fail` | It's holding up half the wall. Leave it be. |

### The ivy from the courtyard (`ivy` becomes an exit)

The courtyard's `ivy` changes from a fixture to an exit with destination BE. It keeps its look and take\_fail. Its current use line (pulling the ivy back to find the corner of a window frame) is replaced, but that hint at the library window still lives in the ivy's look and the oak's look.

| State | Drop | Field | Draft |
| --- | --- | --- | --- |
| default | 30 | `use_fail` (before the grand staircase is repaired) | You get a hand and a foot into the ivy, and it holds, mostly. Then a whole curtain of it peels away from the wall and sets you back down on the grass, quite gently. Not this way. Not yet. |
| stairs\_repaired | 40 | `use_fail` (window still shut) | You climb the ivy as far as the bedroom window. It's shut, and there's no way to open it from out here. You climb back down. |
| window\_open | 40 | `use` | You grab two fistfuls of ivy and climb, hand over hand, up to the open bedroom window, and haul yourself in over the sill. |
| window\_open | 40 | `move_depart` | {player} climbs the ivy and disappears in through the bedroom window. |
| window\_open | 40 | `move_arrive` | {player} climbs in through the window, bringing a few ivy leaves with them. |

**Not with the ladder.** Climbing ivy while carrying the ladder should be refused on both sides: "Not with a ladder. You'd need a third hand, and possibly a fourth."

### For the developer

1. **Opening the window is code, like the drawer.** A successful use of `bedroom_window` sets a per-player state `window_open`. Per player, because the discovery is the content, the same reason the drawer is per player. Decided 30 October.
2. **Both ivy exits are refused unless the player holds `window_open`**, the same way the cabinet and the passage are gated in `exit_refused_by`. Their text is chosen by state, so `window_open` (a player state) has to win over `stairs_repaired` (a server state) when both are held.
3. **The courtyard ivy is an exit from drop 30 to a room that opens at drop 40.** It's always refused until then, with the drop 30 line. Check the loader accepts an exit whose destination opens at a later drop.
4. **The trigger is `/use window` while carrying powder.** `/use graphite` in the bedroom would be ambiguous, because both the tin and the powder answer to "graphite" and "graphite powder". The powder isn't used up: `requires` only checks it's in hand, and the tin is right there anyway.
5. **Which drop it ships in:** the courtyard ivy's change to an exit and its drop 30 refusal belong in the drop 30 work order. Everything else is drop 40.

## Open questions

- [ ] **Approve or edit the remaining four drafts.** The four drop 30 rooms are approved and in the files. The Upstairs Hallway, Bedroom, Nursery and Secret Library are still waiting, and the Upstairs Hallway's interim bowl sentence comes out when its draft goes in.
- [ ] **Delete the back stairs?** If yes, I'll make the cuts listed above and keep only the repaired Upstairs Hallway text.
- [ ] **Rename the upstairs end of the staircase** to "grand staircase"?
- [x] **One paragraph or fragments?** ~~These drafts are single paragraphs.~~ **Answered for the Kitchen on 31 October**, and in the direction the Entryway already went: the back-door clause became fragment 1 at drop 30 so the Kitchen could open at 25 without a way out into the Courtyard. It cost nothing, because the clause was already the last thing in the paragraph. The question stands open for every other room — these are still single paragraphs, and the Kitchen is a split made for a drop boundary rather than for pacing.
