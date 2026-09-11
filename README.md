# Halloween in June — Cat Petting Bot

Phase 1 MVP of a Halloween haunted-house Discord bot. Users pet a cat with `/pet`;
each user's total persists in a database and is readable via `/stats`.

## Commands

| Command | Description |
|---|---|
| `/pet` | Pet the cat. Increments your counter, returns one of six responses. |
| `/stats` | Show your total pet count and relationship. |
| `/enter-entryway` | Enter the haunted house (testing; replaced in Phase 3). |
| `/use thing` | Take an exit out of your current room. |
| `/look [thing]` | Describe your room, or one thing in it or in your bag. |
| `/inventory` | List what you're carrying. |
| `/initialize-haunted-house` | Admin. Rebuild every room thread. |
| `/add-thing name [description]` | Admin. Place a thing in the room you're in. |
| `/add-room-desc description` | Admin. Describe the room you're in. |

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `DISCORD_TOKEN`. Then:

```powershell
python bot.py
```

### Cohorts

Each player entering the house is placed in cohort A or B, which decides whether
they see "Entryway" or "The Entryway". Assignment is **balanced per server**: a
new player goes to whichever cohort currently has fewer members in that server
(counting everyone ever enrolled there), with a coin flip on a tie. The two groups
never differ by more than one player, which independent random rolls can't
promise on a small server.

### Looking around

`/look` shows your room's description, or `/look cat food` shows one thing.
Things are *instances* — five cans of cat food are five rows — so `/look` reports
"There are 5." when several match, counting what's in the room plus what you're
carrying. A thing someone is carrying has left the room. Room and thing text is
per-server and set from inside the game by an admin with `/add-room-desc` and
`/add-thing`; nothing needs a database edit.

### Multiple servers

The bot can live in several Discord servers at once, and **nothing is shared
between them**. Every table is keyed by `(user_id, guild_id)`, so the same person
has a separate pet count, relationship, mood window, cohort and room position in
each server. Each server also has its own `#halloween` and its own 18 threads.
Every command is guild-only and won't appear in DMs.

Upgrading from a database created before this change: the bot refuses to start
and tells you to run `python reset_db.py --yes --fresh`. There's no correct
`guild_id` to backfill for old rows, so a rebuild is the honest option; the file
is backed up first.

### Cat mood

`/pet` picks from two pools of three responses. A user with no pets in the last
ten minutes has a **70%** chance of a friendly reaction; each pet already inside
that window subtracts 10 points, floored at zero:

| Recent pets (last 10 min) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7+ |
|---|---|---|---|---|---|---|---|---|
| Friendly chance | 70% | 60% | 50% | 40% | 30% | 20% | 10% | 0% |

The window slides continuously rather than resetting, so the cat's patience
returns gradually as a user goes quiet. Each pet is timestamped in the
`pet_events` table, which is what makes the window computable — the `users`
table holds only a lifetime total.

### Relationship meter

Each player has a score from **-100 to 100**, starting at 0. A friendly reaction
adds 5; a standoffish one subtracts 5.

At **midnight Pacific** each day, players who did not `/pet` at all that day
drift back toward neutral:

| Score at midnight | Change | Never passes |
|---|---|---|
| 10 or above | -10 | 0 |
| Between -19 and 9 | no change | - |
| -20 or below | +20 | 0 |

Petting even once during a day cancels that night's drift. The bot settles any
nights it was offline for on next startup, and stamps each user's
`last_decay_date` so a restart cannot apply the same night twice.

> **Testing aid:** `/pet` currently appends a `[testing]` block showing the mood
> roll, its weighting, and the relationship score. Set `SHOW_DEBUG_INFO = False`
> in `bot.py` to turn it off.

### Database

The backend is chosen from `DATABASE_URL`:

- **unset** — a local SQLite file (`catbot.db`) is created automatically. No setup
  required; this is the default for local development.
- **set** — used as a PostgreSQL connection string via asyncpg. Stock
  `postgresql://` URLs are rewritten to `postgresql+asyncpg://` automatically, so
  Railway's variable works unchanged.

Tables are created on startup, so there is no migration step.

## Resetting test data

```powershell
python reset_db.py --yes            # clear all players and pet events
python reset_db.py --yes --fresh    # SQLite: delete the file, rebuilding the schema
```

Both wipe every player. Use `--fresh` after changing a column default: a column
added by the ALTER migration keeps whatever SQL default it was created with, so
only a rebuilt schema picks the new one up. The SQLite file is backed up to
`catbot.db.backup-<timestamp>` first; PostgreSQL is not, so snapshot it yourself.

Stop the bot before resetting, then restart it.

## Deploying to Railway

1. Push to GitHub.
2. Create a Railway project and connect this repo.
3. Add a PostgreSQL database — Railway injects `DATABASE_URL` automatically.
4. Add `DISCORD_TOKEN` in the Railway dashboard (it is **not** in the repo).
5. Railway runs `python bot.py` per `railway.json` / `Procfile`.

## Project layout

```
bot.py            Discord client, slash commands, error handling
database.py       SQLAlchemy model and async query functions
requirements.txt  Pinned dependencies
railway.json      Railway build/deploy config
Procfile          Process definition (worker)
.env.example      Template for environment variables
```

## Note on dependency versions

The spec pinned `discord.py==2.3.2`, `sqlalchemy==2.0.23`, and `asyncpg==0.29.0`.
Those predate Python 3.13 and do not install on it — discord.py <2.4 imports the
`audioop` stdlib module removed by PEP 594, and asyncpg <0.30 has no 3.13 wheels.
The pins here are the equivalent 3.13-compatible releases.
