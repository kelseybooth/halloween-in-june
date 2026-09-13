# Halloween Discord Bot - Phase 2: Haunted House Exploration

## Overview

Phase 2 transforms the bot into a haunted house exploration experience. Players are assigned to one of two cohorts (A or B), balanced so each server's two groups stay the same size, and explore a 9-room haunted house through private Discord threads. Each room has two versions (with and without an article) so mods can distinguish cohorts, but players don't explicitly know they're in different versions.

This phase focuses on infrastructure: room creation, thread management, navigation, and entry/exit mechanics. Phase 3+ will add puzzle content within rooms.

---

## Room Structure

### The 9 Rooms

1. Dining Room
2. Entryway
3. Living Room
4. Kitchen
5. Courtyard
6. Secret Library
7. Upstairs Hallway
8. Bedroom
9. Nursery

### Room Naming Convention

**Cohort A (No Article):**
- Dining Room
- Entryway
- Living Room
- Kitchen
- Courtyard
- Secret Library
- Upstairs Hallway
- Bedroom
- Nursery

**Cohort B (With Article):**
- The Dining Room
- The Entryway
- The Living Room
- The Kitchen
- The Courtyard
- The Secret Library
- The Upstairs Hallway
- The Bedroom
- The Nursery

**Why:** Mods can easily see which cohort a thread belongs to. Players likely won't notice, or if they do, they might not realize it's systematic (could be flavor text).

---

## Navigation Graph

All exits are bidirectional (players can navigate back through the same door). The "Secret Staircase" is flavor text on the Kitchen→Upstairs Hallway exit, not a room itself.

```
Dining Room
├─ Kitchen (exit code: DK)
└─ Entryway (exit code: DE)

Entryway
├─ Dining Room (exit code: ED)
├─ Living Room (exit code: EL)
└─ Upstairs Hallway (exit code: EH)

Living Room
├─ Entryway (exit code: LE)
└─ Secret Library (exit code: LS)

Kitchen
├─ Dining Room (exit code: KD)
├─ Upstairs Hallway (exit code: KH) [via Secret Staircase]
└─ Courtyard (exit code: KC)

Courtyard
├─ Kitchen (exit code: CK)
└─ Secret Library (exit code: CS)

Secret Library
├─ Living Room (exit code: SL)
└─ Courtyard (exit code: SC)

Upstairs Hallway
├─ Kitchen (exit code: HK) [via Secret Staircase]
├─ Bedroom (exit code: HB)
├─ Nursery (exit code: HN)
└─ Entryway (exit code: HE)

Bedroom
└─ Upstairs Hallway (exit code: BH)

Nursery
└─ Upstairs Hallway (exit code: NH)
```

**Every exit has two names.** The codes above (DK, DE, …) are each exit's
`thing_ID`: a stable identifier that code and tests refer to and that never
changes. Separately, each exit has a `thing` — the description players see and
can type. For now every description is the placeholder `<thing_ID>_desc` (so EL's
description is `EL_desc`); Phase 3 replaces each with real copy such as "blue
door" or "ornate doorway", and *only the description changes*. The `/use` command
accepts the `thing_ID`, the description, or the destination room name.

**Where descriptions come from long term:** the content file described in
`LOOK_COMMAND_SPEC.md` (*Content Loading*). It supplies every server's exit
descriptions, room descriptions and things, so all servers present the same world
and mechanics can rely on specific exits and objects existing. The graph in code
then carries structure only - `thing_ID`s and destinations - and the `thing=`
placeholder mechanism is superseded.

---

## Database Schema

### Multi-Server Isolation (applies to every table)

The bot can be installed in more than one Discord server at once. **Nothing
leaks between servers.** Every table is keyed by `(user_id, guild_id)`, and every
query filters on both. The same player in two servers is, as far as the data is
concerned, two unrelated players:

- Same player on Server 1: `user_id=123, guild_id=456` → Cohort A, Living Room, 47 pets, relationship -95
- Same player on Server 2: `user_id=123, guild_id=789` → Cohort B, Entryway, 2 pets, relationship 50

This covers the cat as well as the house. **Each server has its own cat**: pet
counts, mood windows, relationship scores and the nightly decay are all
per-server. A player who annoys the cat in one server meets a friendly cat in
another.

Threads are naturally per-server already — each server has its own `#halloween`
and its own 18 threads — so only the database needed changing to achieve this.

Because every command needs a server to scope to, **all commands are
guild-only** and do not appear in DMs.

### Update to Users Table

Keep all existing columns: `id`, `pet_count`, `relationship`, `last_decay_date`,
`created_at`, `updated_at`. Add `guild_id BIGINT NOT NULL`, and change the primary
key from `id` to the composite `(id, guild_id)`. `pet_events` likewise gains
`guild_id`. The relationship meter and its nightly decay (see the Phase 1 spec)
otherwise work unchanged, now once per server.

**Migration note:** adding a column to a primary key cannot be done with
`ALTER TABLE` on SQLite, and there is no correct `guild_id` to backfill for rows
that predate this change — the database never recorded which server a pet
happened in. The bot therefore **refuses to start** against a pre-multi-server
database, with a message pointing to `reset_db.py --yes --fresh`. All such data is
test data, and the SQLite file is backed up before it is rebuilt.

### New Table: Player Game State

```sql
CREATE TABLE player_game_state (
  user_id BIGINT NOT NULL,
  guild_id BIGINT NOT NULL,
  room_version_assignment CHAR(1) CHECK (room_version_assignment IN ('A', 'B')),
  current_room VARCHAR(50),
  rooms_unlocked JSON, -- JSON array of room names player has visited/unlocked
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, guild_id),
  FOREIGN KEY (user_id, guild_id) REFERENCES users(id, guild_id)
);
```

**Ordering requirement (important):** a `users` row is created only on a player's
first `/pet` *in that server* — nothing else creates one. A player who starts the
haunted house in a server without ever petting the cat there has no `users` row
for that server, and inserting their `player_game_state` row would violate this
foreign key. (Having petted the cat in a *different* server does not help: the key
is per-server.)

Game start must **ensure the `users` row exists before** inserting into
`player_game_state`. Creating it there is harmless: `pet_count` stays 0 until they
actually pet, and `relationship` takes its usual starting value, which suits a game
whose opening line has the cat appearing at the player's side.

The alternative — dropping the foreign key — is not recommended: it would let game
state exist for players the rest of the bot knows nothing about, and the nightly
relationship drift iterates `users`, so such a player would silently never drift.

**Schema Details:**
- `user_id` (BIGINT, NOT NULL): Discord user ID
- `guild_id` (BIGINT, NOT NULL): Discord server ID — what makes every row server-specific
- `PRIMARY KEY (user_id, guild_id)`: one row per player *per server*
- `room_version_assignment` (CHAR(1)): 'A' or 'B', assigned **per server** on first game start there so that server's two groups stay balanced
- `current_room` (VARCHAR(50)): Name of the room player is currently in (e.g., "Entryway")
- `rooms_unlocked` (JSON): JSON array of room names the player has unlocked/visited
  - **Not `TEXT[]`.** PostgreSQL array types have no SQLite equivalent, and the bot
    falls back to SQLite whenever `DATABASE_URL` is unset — which is how it runs
    locally. A JSON column behaves the same on both, so the table builds and the
    same code reads it either way.
  - Initially: `["Entryway"]` (only starting room)
  - All other rooms in testing phase: starts unlocked via `/initialize-haunted-house` setup
- `created_at`, `updated_at`: Timestamps

---

## Discord Setup

### Channel Structure

- **#halloween** channel: Contains all 18 thread (9 rooms × 2 versions)
- Threads are **private** (invitation-only)
- Threads are kept permanently un-archived by a daily sweep, so a room that
  goes untouched for weeks is still there when a player returns
- Thread names follow naming convention above

### Thread Permissions

- **By default:** Threads are empty with no members (except bot)
- **When player enters room:** Bot adds player to correct version thread
- **When player leaves room:** Bot removes player from thread
- **Reinit behavior:** `/initialize-haunted-house` deletes/recreates all threads but **preserves player permissions**
  - If a player was in "Entryway", they remain in "Entryway" (or "The Entryway" for cohort B)
  - Their `rooms_unlocked` list is preserved

---

## Commands

### 1. `/initialize-haunted-house` (Admin Only)

**Purpose:** Create/recreate all haunted house threads **for the current server** and initialize game state.

**Behavior:**
1. Take the server (guild) ID from the command context
2. Check if `#halloween` channel exists in this server (must exist before running command)
3. Delete all existing threads in this server's `#halloween` (if any)
4. Create 18 threads (9 rooms × 2 versions) in this server:
   - Thread names follow naming convention (no article / with article)
   - Threads are set to **private** with no initial members
   - Set auto-archive to 7 days, Discord's maximum (it accepts only 1 hour,
     1 day, 3 days or 7 days)
   - **Rooms must never actually archive.** Since no auto-archive setting is
     long enough to express that, a daily background sweep un-archives every
     house thread, keeping all 18 permanently open regardless of how long a
     room sits idle. The 7-day setting is only a backstop.
5. Log completion: "Haunted House initialized with 18 threads in [Server Name]"
6. Provide confirmation in Discord, naming the server

**Multi-Server Behavior:**
- Each server gets its own set of 18 threads
- Running `/initialize-haunted-house` on Server 1 does NOT affect Server 2's threads or players
- Player restoration reads only *this server's* rows from `player_game_state` (filtered by `guild_id`)

**Important:** This command should be **rerunnable**. If run multiple times:
- First run: Creates all threads
- Subsequent runs: Deletes existing threads and recreates them
- **Preserves player permissions:** If player A was in "Entryway" on Server 1, they remain invited after recreation
- Use database as source of truth for who should have access to which threads (filtered by `guild_id`)

**Error Handling:**
- If `#halloween` channel doesn't exist, inform admin to create it first
- If thread creation fails, log specific errors
- Provide meaningful error messages

---

### 2. `/enter-entryway` (Player Command - Temporary Testing Only)

**Purpose:** Initialize a new player into the game and place them in the Entryway **for the current server**.

**Note:** This is a temporary testing command. In Phase 3, this will be replaced with a proper game start flow/mechanism.

**Behavior:**
1. Take the server (guild) ID from the command context
2. Check if player already has an entry in `player_game_state` **for this server**
   - Query: `WHERE user_id = <player_id> AND guild_id = <guild_id>`
3. If YES: Respond "You're already in the haunted house!" (stop here)
4. If NO, proceed:
   - Ensure a `users` row exists for this player *in this server* (create it if
     they have never petted the cat here) so the `player_game_state` foreign key
     is satisfied
   - Assign cohort to keep this server balanced: whichever of A or B currently
     has **fewer players** (counting everyone ever enrolled in this server); a
     coin flip when they are level. Independent 50/50 rolls were replaced because
     they only balance at scale — a four-player server had a 1-in-8 chance of
     landing everyone in the same cohort. The groups now never differ by more
     than one player. The tie-break keeps any individual's cohort unpredictable.
   - Two players enrolling in the same instant can both read the same counts and
     land on the same side; this is harmless, since the next enrolment goes to
     the smaller cohort and corrects it.
   - Set `current_room = "Entryway"`
   - Set `rooms_unlocked = ["Entryway", "Dining Room", "Living Room", "Kitchen", "Courtyard", "Secret Library", "Upstairs Hallway", "Bedroom", "Nursery"]` (all rooms for testing phase)
   - Insert new record into `player_game_state` table with `guild_id`
   - Determine correct Entryway thread based on cohort (Entryway for A, The Entryway for B)
   - Add player to the correct Entryway thread **in this server**
   - Send welcome message in Entryway thread: `Welcome, @<username>! You arrive at the entrance to the haunted house. The cat appears at your side.` (placeholder text)
   - Respond to player's `/enter-entryway` command: "You've entered the haunted house! Check #halloween for the Entryway thread."

**Multi-Server Behavior:**
- The same player can run `/enter-entryway` on Server 1 and be assigned Cohort A
- The same player can run `/enter-entryway` on Server 2 and be assigned Cohort B
- The two game states are completely independent

**Error Handling:**
- If database insert fails, inform player: "An error occurred. Try again."
- Log all errors for debugging

**Testing Note:** This command allows testers to self-onboard without admin help. Remove or replace in Phase 3 when proper game start flow exists.

---

### 3. `/use [thing]` (Player Command)

**Purpose:** Navigate between rooms by using an exit, **in the current server**.

**As shown in Discord:**
- Command description: *Attempt to use an object or exit.*
- Option `thing`: *The object or exit to use.*

The wording is deliberately broader than exits alone: Phase 3 adds objects
players can interact with, and the same command will handle both.

**Behavior:**
0. Take the server (guild) ID from the command context; every read and write below
   is scoped by `user_id AND guild_id`

1. **Input parsing:**
   - Accept any string with spaces (e.g., `/use SL`, `/use secret library`, `/use blue door`)
   - Convert input to lowercase for matching
   - Look up exit in navigation graph (match against configured exit labels)

2. **Validation:**
   - Check if the exit label exists from current room
   - If not found, respond: "You don't see that exit here."
   - If player is not in a room (edge case), inform them to enter a room first

3. **Room access:**
   - Check if destination room is in player's `rooms_unlocked` list
   - If NOT unlocked, respond: "You can't access that room yet." (stop here - don't move them)
   - If unlocked, proceed to step 4

4. **Exit message:**
   - Send exit message in current room thread
   - Format: `@<username> exits via <thing>.` — the exit's **description**, never its ID
   - Example: `@Alice exits via EL_desc.` (Phase 3: `@Alice exits via blue door.`)
   - The description comes from the navigation graph, not from what the player
     typed: `/use EL`, `/use el_desc` and `/use living room` all announce
     `exits via EL_desc.`
   - No link to the destination thread. The player who moved gets a private
     "You head to <room>" reply with the link; onlookers in the room they left
     see only which exit was taken.

5. **Remove player from current room:**
   - Bot removes player from current room thread

6. **Add player to destination room:**
   - Bot adds player to destination room thread (correct version for their cohort)

7. **Entry message:**
   - Send entry message in destination thread
   - Format: `@<username> enters <room name>`
   - Example: `@Alice enters Living Room`

8. **Update database (guild-scoped):**
   - Update: `WHERE user_id = <player_id> AND guild_id = <guild_id>`
   - Set `current_room = <destination_room_name>`
   - Update `updated_at` timestamp

**Multi-Server Behavior:**
- A player navigates independently in each server
- Threads, cohort assignments and current rooms are all per-server
- Moving in one server has no effect on the player's position in another

**Error Handling:**
- If thread operations fail, inform player: "An error occurred while moving between rooms. Try again."
- Log all errors for debugging
- Ensure player state stays consistent (if add fails, don't remove from old room, etc.)

**Case Insensitivity Example:**
```
Player types: /use SL
Player types: /use sl
Player types: /use Sl
Player types: /use secret library
All resolve to the same exit (Living Room from Secret Library)
```

---

## Initial Game Start

When a player first joins the game (separate mechanism for starting the game):

1. Check if player exists in `player_game_state` table **for this server**
2. If NOT found:
   - **Ensure a `users` row exists for this player in this server, creating one if
     needed** — the foreign key requires it, and a player who has never petted the
     cat here has no row yet
   - Assign cohort: whichever of A or B has fewer players in this server, random on a tie
   - Set `current_room = "Entryway"`
   - Set `rooms_unlocked = ["Entryway"]`
   - Insert into `player_game_state`
3. Add player to appropriate Entryway thread (Entryway for A, The Entryway for B)
4. Send welcome message in thread

**For this testing phase:** All rooms are unlocked, so effectively `rooms_unlocked` starts with all 9 rooms. In future phases, only "Entryway" will be unlocked initially, and puzzles unlock other rooms.

---

## Room Entry/Exit Messages

### Exit Message Format

**In the room player is leaving:**
```
@<username> exits via <thing>.
```

`<thing>` is the exit's description from the navigation graph (`EL_desc` now,
"blue door" after Phase 3), regardless of how the player referred to it. There is
no link to the destination: the mover receives that privately, and the room they
left learns only which exit they took.

**Example in Discord:**
```
@Alice exits via EL_desc.
```

### Entry Message Format

**In the room player is entering:**
```
@<username> enters <room name>
```

**Example in Discord:**
```
@Bob enters Living Room
```

**Note:** These are temporary placeholder messages. Phase 3 will replace with flavor text provided by writers.

---

## Data Model: Navigation Graph (In Code)

The navigation graph should be structured in code for easy updates. Suggested structure:

```python
class Exit(NamedTuple):
    thing_id: str      # stable identifier: "EL". Never changes.
    thing: str         # what players see and can type: "EL_desc" now, "blue door" in Phase 3
    destination: str   # room this exit leads to

def _exit(thing_id, destination, thing=None):
    # description defaults to "<thing_id>_desc" until a writer supplies one
    return Exit(thing_id, thing or f"{thing_id}_desc", destination)

NAVIGATION_GRAPH = {
    "Entryway": {
        "ED": _exit("ED", "Dining Room"),
        "EL": _exit("EL", "Living Room"),
        "EH": _exit("EH", "Upstairs Hallway"),
    },
    "Dining Room": {
        "DE": _exit("DE", "Entryway"),
        "DK": _exit("DK", "Kitchen"),
    },
    # ... etc for all 9 rooms
}
```

This allows:
- Easy lookup: `NAVIGATION_GRAPH["Entryway"]["EL"].destination` → "Living Room"
- Easy iteration for initialization
- Easy updates if exits change
- **Phase 3 is a one-argument change per exit:** `_exit("EL", "Living Room", thing="blue door")`.
  The ID, the key, the destination and every test referring to `EL` stay as they are.
  (Or, once the content file exists, the description comes from there and the
  argument is not needed at all - see `LOOK_COMMAND_SPEC.md`, *Content Loading*.)

A startup self-check validates the graph: every room present, every exit's
destination real, every exit bidirectional, every room reachable from the
Entryway, each dict key matching its exit's `thing_id`, and — once writers start
naming things — no two exits in the same room sharing a description, which would
make a player's input ambiguous.

**Placeholder descriptions are deliberately ugly.** `EL_desc` cannot be mistaken
for finished copy, so any exit a writer has not yet named stands out in play.

---

## Implementation Architecture

### Files & Modules

**bot.py** (existing, needs updates)
- Import `house_utils`
- Add `/initialize-haunted-house` admin command
- Add `/use` player command
- Integrate with `house_utils` for room management

**database.py** (existing, needs updates)
- Add `player_game_state` table creation in `init_db()` with composite key `(user_id, guild_id)`
- Add `guild_id` to `users` and `pet_events`; refuse to start against a pre-multi-server database
- Add async functions (**all guild-scoped — every one takes `guild_id`**):
  - `ensure_user_exists(user_id, guild_id)` → creates the `users` row for this
    server if absent, so the `player_game_state` foreign key can be satisfied for
    a player who has never petted the cat here
  - `start_game(user_id, guild_id, cohort, room, rooms_unlocked)` → enrols, or reports already enrolled
  - `get_game_state(user_id, guild_id)` → cohort, current room and unlocked rooms in this server
  - `update_current_room(user_id, guild_id, room_name)` → sets current room in this server
  - `get_all_player_locations(guild_id)` → who is where, in this server only
  - **All queries must filter by both `user_id` AND `guild_id`**

**house_utils.py** (new file)
- Define `NAVIGATION_GRAPH` constant
- Define `ROOM_NAMES_A` and `ROOM_NAMES_B` for easy access
- Implement `get_thread_name(room_name, cohort)` → returns thread name ("Entryway" or "The Entryway")
- Implement `find_exit(current_room, user_input)` → returns destination room or None
- Implement `initialize_threads(guild, channel)` → creates/recreates all threads
- Implement thread management helpers (add/remove player from thread)

**game_state.py** (optional, for clarity)
- Centralize game logic and room management functions
- Or integrate into `house_utils.py`

---

## Implementation Checklist

### Database Setup
- [ ] Create `player_game_state` table with composite key `(user_id, guild_id)`
- [ ] Add `guild_id` to `users` (composite key) and `pet_events`
- [ ] Refuse to start against a database that predates `guild_id`, pointing to `reset_db.py --yes --fresh`
- [ ] Implement `ensure_user_exists(user_id, guild_id)` async function (call before any
      `player_game_state` insert)
- [ ] Implement `start_game(user_id, guild_id, ...)` async function
- [ ] Implement `get_game_state(user_id, guild_id)` async function
- [ ] Implement `update_current_room(user_id, guild_id, room_name)` async function
- [ ] Implement `get_all_player_locations(guild_id)` async function
- [ ] **CRITICAL: every query filters by BOTH `user_id` AND `guild_id`**
- [ ] Mark every command guild-only so none can run from a DM
- [ ] Async database operations for all queries

### Navigation & Room Management (house_utils.py)
- [ ] Define `NAVIGATION_GRAPH` constant with all 9 rooms and exits
- [ ] Define `ROOM_NAMES_A` and `ROOM_NAMES_B` lists
- [ ] Implement `get_thread_name(room_name, cohort)` function
- [ ] Implement `find_exit(current_room, user_input)` function (case-insensitive matching)
- [ ] Implement `initialize_threads(guild, channel)` async function
  - [ ] Fetch/verify `#halloween` channel exists
  - [ ] Delete existing threads (if any)
  - [ ] Create 18 new threads (9 rooms × 2 cohorts)
  - [ ] Set thread privacy (private)
  - [ ] Set auto-archive duration (7 days - Discord's maximum)
- [ ] Implement a daily sweep that un-archives every house thread, so rooms
      stay open no matter how long they sit idle
  - [ ] Return success/failure info
- [ ] Implement `add_player_to_thread(thread, player_id)` async function
- [ ] Implement `remove_player_from_thread(thread, player_id)` async function
- [ ] Implement `get_thread_by_room_and_cohort(guild, room_name, cohort)` async function

### Commands (bot.py)
- [ ] Implement `/initialize-haunted-house` admin command
  - [ ] Take guild_id from command context
  - [ ] Check if caller is admin/has appropriate permissions
  - [ ] Call `initialize_threads()` with this server's players only
  - [ ] Confirm success in Discord, naming the server
  - [ ] Handle errors gracefully

- [ ] Implement `/enter-entryway` player command (temporary testing)
  - [ ] Take guild_id from command context
  - [ ] Check if player already in `player_game_state` table for this server
    - [ ] Query: WHERE user_id = X AND guild_id = <guild_id>
  - [ ] If yes: respond "already in the haunted house"
  - [ ] If no:
    - [ ] Assign cohort to the smaller group in this server (coin flip on a tie)
    - [ ] Create `player_game_state` entry with all 9 rooms unlocked
    - [ ] Set `current_room = "Entryway"`
    - [ ] Determine correct Entryway thread (Entryway for A, The Entryway for B)
    - [ ] Add player to correct thread
    - [ ] Send welcome message in Entryway thread
    - [ ] Respond to player with confirmation
  - [ ] Handle database errors gracefully
  - [ ] Mark with TODO comment: remove in Phase 3 when game start flow exists
  
- [ ] Implement `/use [thing]` player command
  - [ ] Take guild_id from command context
  - [ ] Get player's current room from database (guild-scoped query)
  - [ ] Get player's cohort from database (guild-scoped query)
  - [ ] Parse `thing` (case-insensitive)
  - [ ] Call `find_exit()` to resolve destination
  - [ ] Validate destination room is unlocked (currently: all rooms are unlocked)
  - [ ] Send exit message in current room, naming the exit taken
  - [ ] Remove player from current room thread
  - [ ] Add player to destination room thread
  - [ ] Send entry message in destination room
  - [ ] Update `current_room` in database (guild-scoped update)
  - [ ] Handle errors gracefully

### Threading & Message Management
- [ ] Link the destination thread in the private "You head to" reply (public exit message carries no link)
- [ ] Implement entry message formatting
- [ ] Implement exit message formatting
- [ ] Ensure bot can invite players to private threads
- [ ] Ensure bot can remove players from threads

### Testing (Local & Railway)
- [ ] Test `/initialize-haunted-house` creates all 18 threads with correct names
- [ ] Test thread naming: Cohort A threads have no article, Cohort B have article
- [ ] Test player assignment: first player is a coin flip, second always lands
      opposite, N players split as evenly as N allows
- [ ] Test `/use` with exit code (e.g., `/use EL`)
- [ ] Test `/use` with lowercase (e.g., `/use el`)
- [ ] Test `/use` with spaces in future (e.g., `/use secret library`)
- [ ] Test entry/exit messages appear in correct threads
- [ ] Test the private "You head to" reply links to the destination thread
- [ ] Test `/use` from dead-end rooms (e.g., Bedroom only has one exit)
- [ ] Test reinitializing threads preserves player permissions
- [ ] Test cohort consistency: same player always sees same room names
- [ ] Test `/enter-entryway` for a player who has never run `/pet` (no `users`
      row yet) - must succeed, not fail on the foreign key
- [ ] Test error cases: invalid exits, unlocked room checks (currently all unlocked)

### Multi-Server Testing (CRITICAL)
- [ ] Install the bot on Server 1 and Server 2
- [ ] Run `/initialize-haunted-house` on Server 1 → creates 18 threads in Server 1
- [ ] Run `/initialize-haunted-house` on Server 2 → creates 18 threads in Server 2 (independent)
- [ ] Player A runs `/enter-entryway` on Server 1 → assigned a cohort
- [ ] Player A runs `/enter-entryway` on Server 2 → cohort is decided by Server 2's
      own counts, independent of Server 1
- [ ] Player A navigates Server 1 to Living Room
- [ ] Player A's state on Server 2 still shows Entryway (different guild state)
- [ ] Player A uses `/use` on Server 1 → moves them only on Server 1
- [ ] Player A uses `/use` on Server 2 → moves them only on Server 2
- [ ] Verify database: Player A has two separate `player_game_state` records (one per guild)
- [ ] Player B can be in the same room on both servers without cross-server conflicts
- [ ] **The cat too:** Player A pets the cat 5 times on Server 1; `/stats` on Server 2 still shows 0 pets and relationship 50
- [ ] Player A annoys the Server 1 cat (rapid pets) → Server 2's mood weighting is unaffected
- [ ] Nightly decay: Player A pets only on Server 1 → next morning Server 1 relationship is unchanged, Server 2 has drifted
- [ ] Commands are not offered in DMs

---

## Important Notes

### Testing Phase Simplifications

For this phase:
- All rooms are unlocked from the start
- No puzzles or obstacles
- Exit labels are simple codes (DK, EL, etc.)
- Messages are placeholder text

### Future Phase Expansions

Phase 3+ will add:
- Puzzle mechanics that unlock specific rooms
- Flavor text for entry/exit messages
- Descriptive exit names ("blue door", "ornate painting", etc.)
- Look/inspect commands to discover exits
- Interactive content within room threads
- Teleport dropdown menu for faster navigation

### Design Philosophy

- Room versions are distinguished by articles for mod visibility, not player visibility
- Exit codes match destination room pattern (first letter of current room + first letter of destination)
- All room management is bot-driven; players can only move through bot commands
- Database tracks full game state for persistence and Phase 3 expansion

---

## Temporary Placeholder Considerations

The room entry/exit messages should use placeholder text that's easy to find and replace:

**Exit Message:**
```python
exit_msg = f"@{player_name} exits via {exit.thing}."
```

**Entry Message:**
```python
entry_msg = f"@{player_name} enters {room_name}"
```

In Phase 3, writers will provide flavor text that replaces these templates:
```python
# Example future flavor text
exit_flavors = {
    ("Entryway", "Dining Room"): "You push through the heavy wooden doors into the grand dining hall...",
    ...
}
```

---

## Questions for Claude Code

- Should we use a config file for `NAVIGATION_GRAPH` or hardcode in `house_utils.py`? (Hardcoding is fine for Phase 2)
- Should thread auto-archive be 1 week or different? **Resolved:** rooms should
  never archive. Discord's maximum setting is 7 days, so the setting is a
  backstop and a daily sweep keeps all 18 threads permanently open.
- Any specific logging recommendations for room transitions? (Standard `logging` module is fine)
- Should we add a `/current-room` command so players can check where they are? (Nice to have, but not required for MVP)
- Should we add a `/rooms-unlocked` command so players can see what they've discovered? (Nice to have, but not required for MVP)

---

## Success Criteria

### Single-Server Tests
- [ ] 18 threads created in #halloween with correct naming convention
- [ ] `/initialize-haunted-house` works and is rerunnable
- [ ] `/enter-entryway` initializes new players into correct cohort
- [ ] Running `/enter-entryway` twice on same player prevents duplicate entry
- [ ] Players randomly assigned to cohort A or B on first game start
- [ ] All players in cohort A see "Entryway", all in cohort B see "The Entryway"
- [ ] `/use [exit_code]` navigates between rooms correctly
- [ ] `/use` is case-insensitive
- [ ] Entry/exit messages appear in correct threads; the exit message names the exit taken
- [ ] Player removed from room when they leave, added to new room when they enter
- [ ] Player cohort and current room tracked in database
- [ ] All 9 rooms reachable via navigation graph
- [ ] Reinitializing threads preserves player permissions

### Multi-Server Isolation Tests (CRITICAL)
- [ ] Same player has separate state on Server 1 and Server 2
- [ ] Player can be assigned different cohorts on different servers, because each
      server balances its own groups
- [ ] Player can unlock rooms at a different pace on each server
- [ ] Threads on Server 1 are independent from Server 2
- [ ] Running `/initialize-haunted-house` on Server 1 doesn't affect Server 2's threads
- [ ] Player navigation on Server 1 doesn't affect their state on Server 2
- [ ] Each server has its own cat: pet counts, relationship and decay are per-server
- [ ] Database contains separate `users` and `player_game_state` records per (user_id, guild_id) pair
- [ ] All queries properly scope by guild_id
- [ ] No command can be invoked from a DM

### Readiness for Phase 3
- [ ] Code ready for Phase 3 content expansion
- [ ] Guild scoping pattern established for future multi-server expansion
- [ ] Database schema supports multi-server architecture

