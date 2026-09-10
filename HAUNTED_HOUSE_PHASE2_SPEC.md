# Halloween Discord Bot - Phase 2: Haunted House Exploration

## Overview

Phase 2 transforms the bot into a haunted house exploration experience. Players are randomly assigned to one of two cohorts (A or B) and explore a 9-room haunted house through private Discord threads. Each room has two versions (with and without an article) so mods can distinguish cohorts, but players don't explicitly know they're in different versions.

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
└─ Nursery (exit code: HN)

Bedroom
└─ Upstairs Hallway (exit code: BH)

Nursery
└─ Upstairs Hallway (exit code: NH)
```

**Note:** The exit codes (DK, DE, etc.) are temporary. In future iterations, exits will have descriptive names like "blue door" or "ornate doorway". The `/use` command must be flexible enough to accept both codes and descriptive strings.

---

## Database Schema

### Update to Users Table

Keep all existing columns: `id`, `pet_count`, `relationship`, `last_decay_date`,
`created_at`, `updated_at`. Phase 2 adds nothing to this table — the relationship
meter and its nightly decay (see the Phase 1 spec) continue to work unchanged
alongside the haunted house.

### New Table: Player Game State

```sql
CREATE TABLE player_game_state (
  user_id BIGINT PRIMARY KEY,
  room_version_assignment CHAR(1) CHECK (room_version_assignment IN ('A', 'B')),
  current_room VARCHAR(50),
  rooms_unlocked JSON, -- JSON array of room names player has visited/unlocked
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**Ordering requirement (important):** a `users` row is created only on a player's
first `/pet` — nothing else creates one. A player who starts the haunted house
without ever petting the cat therefore has no `users` row, and inserting their
`player_game_state` row would violate this foreign key.

Game start must **ensure the `users` row exists before** inserting into
`player_game_state`. Creating it there is harmless: `pet_count` stays 0 until they
actually pet, and `relationship` takes its usual starting value, which suits a game
whose opening line has the cat appearing at the player's side.

The alternative — dropping the foreign key — is not recommended: it would let game
state exist for players the rest of the bot knows nothing about, and the nightly
relationship drift iterates `users`, so such a player would silently never drift.

**Schema Details:**
- `user_id` (BIGINT, PRIMARY KEY): Discord user ID
- `room_version_assignment` (CHAR(1)): 'A' or 'B', randomly assigned on first game start
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

**Purpose:** Create/recreate all haunted house threads and initialize game state.

**Behavior:**
1. Check if `#halloween` channel exists (must exist before running command)
2. Delete all existing threads in `#halloween` (if any)
3. Create 18 threads (9 rooms × 2 versions):
   - Thread names follow naming convention (no article / with article)
   - Threads are set to **private** with no initial members
   - Set auto-archive: 1 week (reasonable default)
4. Log completion: "Haunted House initialized with 18 threads"
5. Provide confirmation in Discord

**Important:** This command should be **rerunnable**. If run multiple times:
- First run: Creates all threads
- Subsequent runs: Deletes existing threads and recreates them
- **Preserves player permissions:** If player A was in "Entryway", they remain invited after recreation
- Use database as source of truth for who should have access to which threads

**Error Handling:**
- If `#halloween` channel doesn't exist, inform admin to create it first
- If thread creation fails, log specific errors
- Provide meaningful error messages

---

### 2. `/enter-entryway` (Player Command - Temporary Testing Only)

**Purpose:** Initialize a new player into the game and place them in the Entryway.

**Note:** This is a temporary testing command. In Phase 3, this will be replaced with a proper game start flow/mechanism.

**Behavior:**
1. Check if player already has an entry in `player_game_state` table
2. If YES: Respond "You're already in the haunted house!" (stop here)
3. If NO, proceed:
   - Ensure a `users` row exists for this player (create it if they have never
     petted the cat) so the `player_game_state` foreign key is satisfied
   - Randomly assign cohort: A or B (50/50 chance)
   - Set `current_room = "Entryway"`
   - Set `rooms_unlocked = ["Entryway", "Dining Room", "Living Room", "Kitchen", "Courtyard", "Secret Library", "Upstairs Hallway", "Bedroom", "Nursery"]` (all rooms for testing phase)
   - Insert new record into `player_game_state` table
   - Determine correct Entryway thread based on cohort (Entryway for A, The Entryway for B)
   - Add player to the correct Entryway thread
   - Send welcome message in Entryway thread: `Welcome, @<username>! You arrive at the entrance to the haunted house. The cat appears at your side.` (placeholder text)
   - Respond to player's `/enter-entryway` command: "You've entered the haunted house! Check #halloween for the Entryway thread."

**Error Handling:**
- If database insert fails, inform player: "An error occurred. Try again."
- Log all errors for debugging

**Testing Note:** This command allows testers to self-onboard without admin help. Remove or replace in Phase 3 when proper game start flow exists.

---

### 3. `/use [exit_label]` (Player Command)

**Purpose:** Navigate between rooms using an exit label.

**Behavior:**
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
   - Format: `@<username> exits to go to <destination room name>` with clickable link to destination thread
   - Example: `@Alice exits to go to [Living Room](thread_link)`

5. **Remove player from current room:**
   - Bot removes player from current room thread

6. **Add player to destination room:**
   - Bot adds player to destination room thread (correct version for their cohort)

7. **Entry message:**
   - Send entry message in destination thread
   - Format: `@<username> enters <room name>`
   - Example: `@Alice enters Living Room`

8. **Update database:**
   - Set `current_room = <destination_room_name>`
   - Update `updated_at` timestamp

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

1. Check if player exists in `player_game_state` table
2. If NOT found:
   - **Ensure a `users` row exists for this player, creating one if needed** — the
     foreign key requires it, and a player who has never petted has no row yet
   - Randomly assign cohort: A or B (50/50)
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
@<username> exits to go to <destination room name>
```

With destination room name as a **clickable link** to the destination thread.

**Example in Discord:**
```
@Alice exits to go to [Living Room](https://discord.com/channels/...)
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
NAVIGATION_GRAPH = {
    "Entryway": {
        "exits": {
            "ED": "Dining Room",      # exit code: destination
            "EL": "Living Room",
            "EH": "Upstairs Hallway"
        }
    },
    "Dining Room": {
        "exits": {
            "DE": "Entryway",
            "DK": "Kitchen"
        }
    },
    "Living Room": {
        "exits": {
            "LE": "Entryway",
            "LS": "Secret Library"
        }
    },
    # ... etc for all 9 rooms
}
```

This allows:
- Easy lookup: `NAVIGATION_GRAPH["Entryway"]["exits"]["EL"]` → "Living Room"
- Easy iteration for initialization
- Easy updates if exits change
- Easy extension for future exit descriptions (replace "ED" with descriptive name)

**In future:** Exit labels will be descriptive ("blue door", "ornate doorway") instead of codes. The structure remains the same.

---

## Implementation Architecture

### Files & Modules

**bot.py** (existing, needs updates)
- Import `house_utils`
- Add `/initialize-haunted-house` admin command
- Add `/use` player command
- Integrate with `house_utils` for room management

**database.py** (existing, needs updates)
- Add `player_game_state` table creation in `init_db()`
- Add async functions:
  - `ensure_user_exists(user_id)` → creates the `users` row if absent, so the
    `player_game_state` foreign key can be satisfied for a player who has
    never petted the cat
  - `get_or_create_game_state(user_id)` → returns cohort assignment
  - `update_current_room(user_id, room_name)` → sets current room
  - `get_rooms_unlocked(user_id)` → returns list of unlocked rooms
  - `add_room_unlocked(user_id, room_name)` → adds room to unlocked list

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
- [ ] Create `player_game_state` table in `database.py` init
- [ ] Implement `ensure_user_exists(user_id)` async function (call before any
      `player_game_state` insert)
- [ ] Implement `get_or_create_game_state(user_id)` async function
- [ ] Implement `update_current_room(user_id, room_name)` async function
- [ ] Implement `get_rooms_unlocked(user_id)` async function
- [ ] Implement `add_room_unlocked(user_id, room_name)` async function
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
  - [ ] Set auto-archive duration
  - [ ] Return success/failure info
- [ ] Implement `add_player_to_thread(thread, player_id)` async function
- [ ] Implement `remove_player_from_thread(thread, player_id)` async function
- [ ] Implement `get_thread_by_room_and_cohort(guild, room_name, cohort)` async function

### Commands (bot.py)
- [ ] Implement `/initialize-haunted-house` admin command
  - [ ] Check if caller is admin/has appropriate permissions
  - [ ] Call `initialize_threads()`
  - [ ] Confirm success in Discord
  - [ ] Handle errors gracefully

- [ ] Implement `/enter-entryway` player command (temporary testing)
  - [ ] Check if player already in `player_game_state` table
  - [ ] If yes: respond "already in the haunted house"
  - [ ] If no:
    - [ ] Randomly assign cohort A or B
    - [ ] Create `player_game_state` entry with all 9 rooms unlocked
    - [ ] Set `current_room = "Entryway"`
    - [ ] Determine correct Entryway thread (Entryway for A, The Entryway for B)
    - [ ] Add player to correct thread
    - [ ] Send welcome message in Entryway thread
    - [ ] Respond to player with confirmation
  - [ ] Handle database errors gracefully
  - [ ] Mark with TODO comment: remove in Phase 3 when game start flow exists
  
- [ ] Implement `/use [exit_label]` player command
  - [ ] Get player's current room from database
  - [ ] Get player's cohort from database
  - [ ] Parse exit_label (case-insensitive)
  - [ ] Call `find_exit()` to resolve destination
  - [ ] Validate destination room is unlocked (currently: all rooms are unlocked)
  - [ ] Send exit message in current room with link
  - [ ] Remove player from current room thread
  - [ ] Add player to destination room thread
  - [ ] Send entry message in destination room
  - [ ] Update `current_room` in database
  - [ ] Handle errors gracefully

### Threading & Message Management
- [ ] Implement Discord thread link generation (for clickable thread links in messages)
- [ ] Implement entry message formatting
- [ ] Implement exit message formatting
- [ ] Ensure bot can invite players to private threads
- [ ] Ensure bot can remove players from threads

### Testing (Local & Railway)
- [ ] Test `/initialize-haunted-house` creates all 18 threads with correct names
- [ ] Test thread naming: Cohort A threads have no article, Cohort B have article
- [ ] Test player assignment: New players randomly assigned A or B
- [ ] Test `/use` with exit code (e.g., `/use EL`)
- [ ] Test `/use` with lowercase (e.g., `/use el`)
- [ ] Test `/use` with spaces in future (e.g., `/use secret library`)
- [ ] Test entry/exit messages appear in correct threads
- [ ] Test Discord links in messages are clickable
- [ ] Test `/use` from dead-end rooms (e.g., Bedroom only has one exit)
- [ ] Test reinitializing threads preserves player permissions
- [ ] Test cohort consistency: same player always sees same room names
- [ ] Test `/enter-entryway` for a player who has never run `/pet` (no `users`
      row yet) - must succeed, not fail on the foreign key
- [ ] Test error cases: invalid exits, unlocked room checks (currently all unlocked)

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
exit_msg = f"@{player_name} exits to go to [{destination_room}]({thread_link})"
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
- Should thread auto-archive be 1 week or different? (1 week is reasonable for testing)
- Any specific logging recommendations for room transitions? (Standard `logging` module is fine)
- Should we add a `/current-room` command so players can check where they are? (Nice to have, but not required for MVP)
- Should we add a `/rooms-unlocked` command so players can see what they've discovered? (Nice to have, but not required for MVP)

---

## Success Criteria

- [ ] 18 threads created in #halloween with correct naming convention
- [ ] `/initialize-haunted-house` works and is rerunnable
- [ ] `/enter-entryway` initializes new players into correct cohort
- [ ] Running `/enter-entryway` twice on same player prevents duplicate entry
- [ ] Players randomly assigned to cohort A or B on first game start
- [ ] All players in cohort A see "Entryway", all in cohort B see "The Entryway"
- [ ] `/use [exit_code]` navigates between rooms correctly
- [ ] `/use` is case-insensitive
- [ ] Entry/exit messages appear in correct threads with clickable links
- [ ] Player removed from room when they leave, added to new room when they enter
- [ ] Player cohort and current room tracked in database
- [ ] All 9 rooms reachable via navigation graph
- [ ] Reinitializing threads preserves player permissions
- [ ] Code ready for Phase 3 content expansion

