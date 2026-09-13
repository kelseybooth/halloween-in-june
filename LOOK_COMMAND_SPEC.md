# Halloween Discord Bot - Phase 2: /look Command & Inventory System

## Overview

Phase 2 introduces environmental interactivity through the `/look` command and player inventory. Players can examine their surroundings, discover things in rooms, and maintain an inventory of collectible items. This feature adds depth to room exploration and sets up the foundation for puzzle mechanics in Phase 3+.

---

## Terminology

- **`thing_id`**: Unique identifier for each specific thing instance (database primary key)
- **`thing`** (or `thing_name`): The name players use in `/look` commands (e.g., "cat food", "dusty painting") — case-insensitive
- **`thing_description`**: The flavor text shown when a player looks at a thing (e.g., "A can of tuna-flavored cat food sitting on a dusty shelf.")
- **Room Description**: Flavor text describing the current room, shown when `/look` is used without arguments

---

## Database Schema

### New Table: Rooms

```sql
CREATE TABLE rooms (
  room_id SERIAL PRIMARY KEY,
  guild_id BIGINT NOT NULL,
  room_name VARCHAR(50) NOT NULL,
  room_description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(guild_id, room_name)
);
```

**No `guilds` table.** There is nothing to reference: `guild_id` is a scoping
column, exactly as in `users`, `pet_events` and `player_game_state`, none of
which has a guilds table behind it. A guilds table would need populating whenever
the bot joined a server, for no benefit. The foreign key is dropped.

**Room rows are seeded by `/initialize-haunted-house`**, one per room in
`house_utils.ROOMS`, with an empty description. Reseeding is a no-op for rows that
exist, so rebuilding the house never discards a writer's description.

**Schema Details:**
- `room_id`: Primary key for database lookups
- `guild_id`: Discord server ID (multi-server isolation)
- `room_name`: Name of the room (e.g., "Entryway", "Kitchen")
- `room_description`: Full flavor text description of the room
- `UNIQUE(guild_id, room_name)`: Each server has unique room descriptions

**Notes:**
- Room descriptions populated during game setup (via seed data or `/initialize-haunted-house`)
- **Long term, all flavour text comes from a content file** loaded into every
  server - see *Content Loading (Phase 3+)* below. Per-server hand entry is a
  testing convenience only.
- Empty/null descriptions show generic message: "You see a room."

---

### New Table: Things

```sql
CREATE TABLE things (
  thing_id SERIAL PRIMARY KEY,
  guild_id BIGINT NOT NULL,
  room_id INTEGER NOT NULL,
  thing_name VARCHAR(100) NOT NULL,
  thing_description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);
```

**Schema Details:**
- `thing_id`: Unique identifier for each thing instance
- `guild_id`: Discord server ID (multi-server isolation)
- `room_id`: Which room this thing exists in
- `thing_name`: What players type in `/look` command (e.g., "cat food")
- `thing_description`: Flavor text shown when player looks at it
- Each thing instance is unique (5 cans of cat food = 5 separate rows)
- **An instance someone is carrying has left the room.** `room_id` records where
  it was placed, but an instance with an `inventory` row is excluded from room
  lookups. Without this rule, a player's own carried cans would be counted once
  in the room and again in their bag - "There are 7." for five cans.

**Multi-Instance Example:**
```
thing_id=1: guild_id=456, room_id=1, thing_name="cat food", thing_description="A can of tuna-flavored cat food..."
thing_id=2: guild_id=456, room_id=1, thing_name="cat food", thing_description="A can of tuna-flavored cat food..."
thing_id=3: guild_id=456, room_id=1, thing_name="cat food", thing_description="A can of tuna-flavored cat food..."
thing_id=47: guild_id=456, room_id=5, thing_name="cat food", thing_description="A can of chicken-flavored cat food..."
```

---

### New Table: Inventory

```sql
CREATE TABLE inventory (
  inventory_id SERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  guild_id BIGINT NOT NULL,
  thing_id INTEGER NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id, guild_id) REFERENCES users(id, guild_id),
  FOREIGN KEY (thing_id) REFERENCES things(thing_id),
  UNIQUE(user_id, guild_id, thing_id) -- Each player can only have one instance of each thing_id
);
```

**Schema Details:**
- `inventory_id`: Primary key
- `user_id`: Discord user ID
- `guild_id`: Discord server ID (multi-server isolation)
- `thing_id`: Reference to the specific thing instance
- `UNIQUE(user_id, guild_id, thing_id)`: Prevent duplicates (each player owns each thing_id at most once)
- Created_at tracks when item was added
- The `users` foreign key is composite, since `users` is keyed by
  `(id, guild_id)`. As with `player_game_state`, the player's `users` row for the
  server is ensured before an inventory row is inserted, so a player who has never
  petted the cat can still be given an item.

**Notes:**
- When player has multiple of same thing_name (5 cat food cans), they have 5 separate inventory rows (each with different thing_id)
- Grouping by thing_name and counting handles display of "There are 5."

---

## Commands

### 1. `/look [thing]` (Player Command)

**Purpose:** Examine the current room or look at a specific thing.

**Behavior:**

#### Case 1: No Arguments (`/look`)
1. Get player's current room from `player_game_state` table (guild-scoped)
2. Query `rooms` table for room_description: `WHERE guild_id = <guild_id> AND room_name = <current_room>`
3. If room_description exists: Send it
4. If room_description is null/empty: Send generic message "You see a room."

**Example Output:**
```
You enter a grand dining hall. Chandeliers hang from the ceiling, casting dancing shadows across an ornate wooden table. The air smells of old wood and dust.
```

---

#### Case 2: With Thing Argument (`/look cat food`)
1. Get player's current room (guild-scoped)
2. Convert input to lowercase for matching
3. **Search Step A: Look in current room**
   - Query `things` table: `WHERE guild_id = <guild_id> AND room_id = <current_room_id> AND LOWER(thing_name) = LOWER('<input>')`
   - If found: Store results
4. **Search Step B: Look in inventory**
   - Query `inventory` + `things` JOIN: Get all things in player's inventory with matching thing_name
   - If found: Store results
5. **Determine source and display:**
   - If found in room OR inventory:
     - Get thing_description from first matching thing
     - Count total matching things (by thing_name) across room and inventory combined
     - If count == 1: Display `"[thing_description]"`
     - If count > 1: Display `"[thing_description] There are (count)."`
   - If not found in room and not in inventory:
     - Display: "You can't look at that."

**Important:** Search BOTH room and inventory. If they have 3 cans in inventory and 2 in the room, count is 5.

**Counting rules:**
- "In the room" means placed in this room *and not carried by anyone*. An
  instance the looking player carries is counted via their inventory, never via
  the room, so nothing is counted twice.
- An instance *another* player carries is not counted at all: it has left the room.
- The player's carried instances are found from any room, not only the one they
  were picked up in.
- The description shown is the first matching instance's. An instance with no
  description falls back to "You see <what they typed>."

**Replies are private** (ephemeral - visible only to the player who ran the
command). This is a requirement, not an implementation choice: players must be
able to explore a room without spamming its thread with their `/look` and
`/inventory` calls. It also means a public reply can never leak room or thing
descriptions to people who are not playing, since either command can be typed in
any channel of the server.

**Error Handling:**
- If player is not in a valid room: "You must be in a room to look around."
- Handle database errors gracefully

**Case Insensitivity Example:**
```
/look cat food
/look CAT FOOD
/look Cat Food
/look CaT FoOd
All resolve to same result
```

---

### 2. `/inventory` (Player Command - Placeholder for Phase 2)

**Purpose:** Display all items in player's inventory.

**Behavior:**
1. Get player's guild_id from command context
2. Query `inventory` table: `WHERE user_id = <player_id> AND guild_id = <guild_id>`
3. For each result, fetch associated `thing_name` from `things` table
4. Group by `thing_name` and count duplicates
5. Display formatted list

**Response Format:**
```
Your inventory:
- cat food (3)
- dusty key (1)
- old photograph (2)

Total items: 6
```

**If Empty:**
```
Your inventory is empty.
```

**Error Handling:**
- If database query fails, inform player: "Couldn't retrieve your inventory. Try again."

**Phase 2 Note:** In testing phase, inventory will likely be empty unless items are manually added to `inventory` table for testing. In Phase 3, puzzles will populate inventory.

---

## Database Functions

### Room Functions

**`get_room_description(guild_id, room_name)` → room_description: str**
- Query: `SELECT room_description FROM rooms WHERE guild_id = ? AND room_name = ?`
- Return: Description string or None
- If None, client displays generic message

---

### Thing Functions

**`get_things_in_room(guild_id, room_name)` → list of thing_id**
- Query: `SELECT things.thing_id FROM things JOIN rooms WHERE things.guild_id = ? AND rooms.guild_id = ? AND rooms.room_name = ?`
- Return: List of thing_ids in this room

**`get_thing_by_name(guild_id, thing_name)` → thing_id, thing_description**
- Query: `SELECT thing_id, thing_description FROM things WHERE guild_id = ? AND LOWER(thing_name) = LOWER(?)`
- Return: First match (thing_id, thing_description) or None
- Case-insensitive matching

**`count_things_by_name(guild_id, thing_name, room_name=None, user_id=None)` → count: int**
- Query things in specific room OR in player's inventory
- If room_name provided: Count things in room
- If user_id provided: Count things in inventory
- If both: Count things in either (for `/look` combined search)
- Return: Integer count

---

### Inventory Functions

**`get_inventory(user_id, guild_id)` → list of (thing_name, count)**
- Query: `SELECT things.thing_name, COUNT(*) FROM inventory JOIN things WHERE inventory.user_id = ? AND inventory.guild_id = ? GROUP BY things.thing_name`
- Return: List of tuples: [(thing_name, count), ...]
- Grouped and counted automatically

**`add_to_inventory(user_id, guild_id, thing_id)` → success: bool**
- Insert: `INSERT INTO inventory (user_id, guild_id, thing_id) VALUES (?, ?, ?)`
- Return: True if success, False if error (e.g., thing already in inventory)
- Handle UNIQUE constraint violation gracefully

**`remove_from_inventory(user_id, guild_id, thing_id)` → success: bool**
- Delete: `DELETE FROM inventory WHERE user_id = ? AND guild_id = ? AND thing_id = ?`
- Return: True if deleted, False if not found

**`inventory_count(user_id, guild_id)` → count: int**
- Query: `SELECT COUNT(*) FROM inventory WHERE user_id = ? AND guild_id = ?`
- Return: Total number of items in inventory

---

## Implementation Architecture

### Files & Modules

**database.py** (existing, needs updates)
- Add `rooms`, `things`, `inventory` table creation in `init_db()`
- Add all async database functions listed above
- All queries guild-scoped: `WHERE guild_id = <guild_id>`

**house_utils.py** (existing, can add here or new file)
- Implement `get_thread_name(room_name, cohort)` (already exists)
- Add room/thing lookup helpers if needed

**bot.py** (existing, needs updates)
- Add `/look [thing]` slash command handler
- Add `/inventory` slash command handler
- Integrate with database functions

---

## Content Loading (Phase 3+)

**The long-term source of every piece of flavour text is a single content file
in the repository, loaded into each server.** Room descriptions and the things
in each room - exits included, since an exit is a thing - all come from it.
Nothing is authored per server by hand.

**Why this is a requirement, not a convenience.** Game mechanics depend on
specific things existing in specific rooms: a puzzle may need "the blue door" to
exist in the Entryway and "cat food" to exist in the Kitchen. If content were
entered by each server's admin, a server could be missing the very object a
puzzle needs, or have it under a different name, and the game would break there.
The content file guarantees every server presents the same world. Per-server
tables then hold only *state* - which player carries which instance - not
*content*.

**Shape of the file** (illustrative; the exact format is Phase 3 design).
There is one list of things per room. **An exit is a thing** with the same
`name` and `description` as any other; what makes it an exit is a `leads_to`.
There is no separate exit section and no separate "exit description" field.

```yaml
rooms:
  Kitchen:
    description: "A dusty kitchen with cracked tiles and a rusty stove."
    things:
      KD:
        name: "swinging door"
        description: "A swinging door on shrieking hinges. Light leaks under it."
        leads_to: "Dining Room"
      KH:
        name: "secret staircase"
        description: "Narrow stone steps behind the pantry, climbing into the dark."
        leads_to: "Upstairs Hallway"
      KC:
        name: "glass door"
        description: "A cracked glass door. Something moves in the courtyard beyond."
        leads_to: "Courtyard"
      cat_food:
        name: "cat food"
        description: "A can of tuna-flavored cat food."
        count: 3
      rusty_stove:
        name: "rusty stove"
        description: "Cold for decades. Something rattles inside."
```

For every thing, exit or not:
- `name` is what a player types (`/use swinging door`, `/look cat food`) and what
  the "exits via …" announcement uses: `@Alice exits via swinging door.`
- `description` is what `/look <name>` shows.
- The key (`KD`, `cat_food`) is the stable content key mechanics refer to.
- `leads_to` makes it an exit. `count` makes several instances.

Today's `Exit.thing` serves as the name; a `/look`-able description for exits
does not exist yet and arrives with the unified model.

**Consequences for the schema, to plan for now:**

- **Things need a content key.** Mechanics must be able to say "the cat food",
  not "thing_id 47" - instance ids are auto-assigned and differ per server. The
  `things` table needs a stable `thing_key` (e.g. `cat_food`) from the content
  file, alongside the per-server instance `thing_id`. This is the same split the
  exits already have: `thing_id` ("EL", stable, from content) versus the runtime
  row.
- **One model for every thing.** Exits and objects are the same kind of row,
  distinguished only by whether `leads_to` is set. `/look swinging door` works
  like `/look cat food`; `/use` resolves either and acts on its kind. The
  exit-specific `house_utils.Exit` and the `things` table converge on this.
- **Loading must be idempotent and state-preserving.** Reloading the file into a
  server that already has players updates descriptions, adds instances that are
  missing, and never duplicates instances or touches inventories. A player
  holding a can of cat food must still hold it after a content reload.
- **Exit names and descriptions leave the code.** Today an exit's player-facing
  text is the `thing=` argument in `house_utils.NAVIGATION_GRAPH`; with the
  content file it comes from the exit's thing entry like any other thing's, and
  the graph in code carries only structure (ids and destinations).
- **`/look` on a room could list its things and exits**, since the file makes the
  full set known - the "nice to have" below becomes straightforward.

**How the file reaches a server:** loaded on `/initialize-haunted-house` (which
already seeds room rows), or by a dedicated admin command such as
`/load-content`. Either way the file is versioned in the repository, so writers
edit it through pull requests and every server picks up the same version on its
next load.

**The admin commands `/add-thing` and `/add-room-desc` are testing tools.** They
exist so `/look` can be exercised before the content file exists. They should be
kept as debugging aids or removed once loading works; they must not become the
way content is authored, for the reasons above.

---

## Seed Data / Initial Setup

### Phase 2 Testing

The setup below is for exercising the mechanics before the content file exists.
See *Content Loading (Phase 3+)* for the real source of content.

For this testing phase, rooms and things should be:

1. **Room Descriptions:** Initially empty/null
   - Players see generic "You see a room." when `/look` with no args
   - For testing: an admin sets one from inside the room with `/add-room-desc`
   - Phase 3+: populated from the content file

2. **Things:** Sample things created for testing (optional)
   - Example: Add 3-5 test things per room so players can test `/look` command
   - Examples: "dusty painting", "cat food", "ornate mirror", "cobweb"
   - For testing: an admin places them from inside the room with `/add-thing`
   - These are optional; game functions work fine with no things
   - Phase 3+: populated from the content file, which is what mechanics rely on

3. **Inventory:** Starts empty
   - Players test `/look` on things in rooms
   - Can manually add things to inventory for testing via database
   - In Phase 3: Puzzles will populate inventory

---

## Implementation Checklist

### Database Setup
- [ ] Create `rooms` table with guild_id, room_name, room_description
- [ ] Create `things` table with guild_id, room_id, thing_name, thing_description
- [ ] Create `inventory` table with user_id, guild_id, thing_id (UNIQUE constraint)
- [ ] Implement `get_room_description(guild_id, room_name)` async function
- [ ] Implement `get_things_in_room(guild_id, room_name)` async function
- [ ] Implement `get_thing_by_name(guild_id, thing_name)` async function (case-insensitive)
- [ ] Implement `count_things_by_name(guild_id, thing_name, room_name=None, user_id=None)` async function
- [ ] Implement `get_inventory(user_id, guild_id)` async function
- [ ] Implement `add_to_inventory(user_id, guild_id, thing_id)` async function
- [ ] Implement `remove_from_inventory(user_id, guild_id, thing_id)` async function
- [ ] Implement `inventory_count(user_id, guild_id)` async function
- [ ] **CRITICAL: All queries guild-scoped with guild_id WHERE clause**

### Commands (bot.py)
- [ ] Implement `/look` command (no arguments)
  - [ ] Get player's current room (guild-scoped)
  - [ ] Retrieve room_description from database
  - [ ] Send room_description or generic fallback
  - [ ] Handle errors gracefully

- [ ] Implement `/look [thing]` command (with argument)
  - [ ] Get guild_id from command context
  - [ ] Get player's current room (guild-scoped)
  - [ ] Parse thing argument (lowercase conversion)
  - [ ] Query things in current room (case-insensitive match)
  - [ ] Query things in inventory (case-insensitive match)
  - [ ] If found: Get thing_description and count
    - [ ] If count == 1: Send thing_description only
    - [ ] If count > 1: Send `thing_description + " There are (count)."`
  - [ ] If not found: Send "You can't look at that."
  - [ ] Handle errors gracefully

- [ ] Implement `/inventory` command
  - [ ] Get guild_id from command context
  - [ ] Call `get_inventory(user_id, guild_id)`
  - [ ] Format and send grouped list with counts
  - [ ] Handle empty inventory case
  - [ ] Handle errors gracefully

### Thing & Room Management (Admin Commands - TESTING ONLY)

Built rather than optional: with the bot on Railway, "add rows to the database by
hand" means the Railway data browser, which is a poor way to write flavour text.
Both act on the admin's **current room**, so an admin walks to a room and works
from inside the game.

**These are not how content is authored long term.** Game mechanics depend on
specific things existing in specific rooms, which hand entry per server cannot
guarantee. Real content comes from the content file - see *Content Loading
(Phase 3+)*. These commands stay as testing and debugging aids until loading
exists, and may be removed after.

- [x] `/add-thing [name] [description]` admin command
  - [x] Creates a thing instance in the admin's current room; `description` optional
  - [x] Admin must be in the house (`/enter-entryway`) to have a current room
- [x] `/add-room-desc [description]` admin command
  - [x] Sets/overwrites room_description for the admin's current room
  - [x] Creates the room row if the house has not been initialized yet

### Testing (Local & Railway)
- [ ] Test `/look` with no arguments → displays room_description (or generic message if null)
- [ ] Test `/look [thing]` with thing in current room → displays thing_description
- [ ] Test `/look [thing]` with thing in inventory → displays thing_description
- [ ] Test `/look [thing]` with multiple instances → displays "There are (count)."
- [ ] Test `/look [thing]` with thing not in room/inventory → "You can't look at that."
- [ ] Test `/look` case-insensitivity: "/look CAT FOOD", "/look cat food", etc.
- [ ] Test `/inventory` with empty inventory → "Your inventory is empty."
- [ ] Test `/inventory` with items → grouped list with counts
- [ ] Test multi-server isolation: Same thing_name in different servers has separate thing_ids
- [ ] Test guild scoping: Player on Server 1 can't see Server 2 rooms/things
- [ ] Test database errors: Handle null descriptions, missing rooms, etc.

---

## Important Notes

### Phase 2 Simplifications

For this testing phase:
- Room descriptions initially empty (writers provide later)
- Things are minimal/optional (for testing the `/look` mechanics)
- Inventory is mostly empty (Phase 3 will populate via puzzles)
- No limits on inventory size

### Future Phase Expansions

Phase 3+ will add:
- Puzzle mechanics that add things to inventory
- Room descriptions written by writers
- Thing descriptions crafted by writers
- Possible thing properties (e.g., can_be_collected: bool)
- Interaction commands with things (e.g., `/use thing`)

### Design Philosophy

- Room descriptions provide atmosphere and lore
- Things are discoverable environmental details
- Inventory foundation enables future puzzle mechanics
- Case-insensitive commands maintain UX consistency
- Guild scoping keeps multi-server data isolated

---

## Success Criteria

### Single-Server Tests
- [ ] `/look` with no args displays room_description (or generic fallback)
- [ ] `/look [thing]` displays thing_description when thing found in room
- [ ] `/look [thing]` displays thing_description when thing found in inventory
- [ ] `/look [thing]` displays count when multiple instances exist
- [ ] `/look [thing]` displays "You can't look at that." when thing not found
- [ ] `/look` is case-insensitive for thing names
- [ ] `/inventory` displays grouped list with counts
- [ ] `/inventory` displays empty message when no items
- [ ] All database queries are async and non-blocking

### Multi-Server Isolation Tests
- [ ] Room descriptions isolated per server (guild_id)
- [ ] Things isolated per server (guild_id)
- [ ] Player inventory isolated per server (guild_id)
- [ ] Same thing_name in different servers = different thing_ids
- [ ] Player on Server 1 can't see Server 2 things/rooms

### Readiness for Phase 3
- [ ] Schema supports Phase 3 puzzle mechanics (things added to inventory)
- [ ] Writers update flavour text in the content file, not per-server columns
- [ ] Schema anticipates a stable content key on things (`thing_key`) so mechanics
      can reference "the cat food" independent of instance id or server
- [ ] Code ready for thing interaction mechanics (`/use thing`)
- [ ] Inventory system ready for item properties/mechanics

---

## Questions for Claude Code

- Should we add an optional `/describe [thing]` command as an alias for `/look [thing]`? (Not built; nice to have)
- Should `/look` suggest things available in the room? (Nice to have; becomes
  straightforward once the content file defines the full set per room)
- Should `/inventory` show thing_descriptions along with names? (Nice to have; currently just names and counts)
- Any logging recommendations for `/look` searches? (Standard logging module fine)
- ~~Naming collision to resolve before Phase 3~~ **Resolved: exits are things.**
  An exit is a thing whose effect, when used, is to move the player to another
  room; an object is a thing with some other effect. `/use` will resolve any thing
  and dispatch on its kind: `/use blue door` moves the player if the destination
  is unlocked; `/use cat food` opens the can or feeds the cat, whichever Phase 3
  design decides. The Phase 3 data model should therefore unify
  `house_utils.Exit` and the `things` table under one vocabulary. Until then the
  two coexist: exits live in code (`NAVIGATION_GRAPH`) and objects in the
  database, and `/look` reports only objects.

---

## Example Gameplay Flow

1. Player in Kitchen runs `/look`
   - Sees: "A dusty kitchen with cracked tiles and a rusty stove. Pots hang from hooks on the wall."

2. Player runs `/look cat food`
   - Finds 3 cans in kitchen, 2 in inventory
   - Sees: "A can of tuna-flavored cat food. There are 5."

3. Player runs `/look mysterious key`
   - Not found in room or inventory
   - Sees: "You can't look at that."

4. Player runs `/inventory`
   - Sees:
     ```
     Your inventory:
     - cat food (2)
     - dusty key (1)
     - old photograph (1)
     
     Total items: 4
     ```

