# Halloween Discord Bot MVP - Cat Petting Game

## Overview
Build a simple Discord bot that allows users to pet a cat (the bot) and track their pet count. This is Phase 1 of a larger Halloween haunted house Discord bot experience. Phase 2+ will expand significantly as writers create content.

## Project Scope: MVP Only
- ✅ `/pet` slash command to pet the cat
- ✅ Persistent per-user pet counter
- ✅ 6 random response variations for each pet (3 friendly, 3 standoffish)
- ✅ Cat mood weighting: repeated petting makes a standoffish reaction likelier
- ✅ Per-user relationship meter, with nightly drift back toward neutral
- ✅ `/stats` slash command to view pet count
- ❌ Thread management
- ❌ Role-based permissions
- ❌ Leaderboards (future phase)
- ❌ Multiple interaction types (buttons, etc. - future phase)

---

## Technical Stack

**Language:** Python
**Framework:** discord.py
**Database:** PostgreSQL (hosted on Railway)
**Database Access:** SQLAlchemy with asyncpg (async PostgreSQL driver)
**Hosting:** Railway (both dev/testing and production)
**Railway:** Free tier with $5 monthly credit for dev; $5-15/month for production (100-500 users)

---

## Discord Bot Setup (Pre-Code)

Before starting development, the user has:
- ✅ Created a Discord bot token in Developer Portal
- ✅ Invited the bot to a test Discord server
- ✅ Enabled "Message Content Intent" in Privileged Gateway Intents
- ✅ Set bot permissions: Send Messages, Embed Links, Read Message History
- ✅ Stored bot token securely (never commit to GitHub)

The bot token will be needed to run the bot.

---

## Data Model

### Storage: PostgreSQL Database (hosted on Railway)

**Table: `users`**

```sql
CREATE TABLE users (
  id BIGINT PRIMARY KEY,
  pet_count INTEGER DEFAULT 0,
  relationship INTEGER DEFAULT 50,
  last_decay_date DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Schema:**
- `id` (BIGINT, PRIMARY KEY): Discord user ID
- `pet_count` (INTEGER): Number of times user has petted the cat (default 0)
- `relationship` (INTEGER): How the cat feels about this user, -100 to 100 (default 50)
- `last_decay_date` (DATE): Last day the nightly drift was applied for this user
- `created_at` (TIMESTAMP): When user first petted the cat
- `updated_at` (TIMESTAMP): Last time the row was updated

**Table: `pet_events`**

One timestamped row per pet. The `users` table holds only a lifetime total, which
cannot answer "how many pets in the last ten minutes" — the question the mood
weighting depends on.

```sql
CREATE TABLE pet_events (
  id INTEGER PRIMARY KEY,
  user_id BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL
);
```

**Behavior:**
- Database connection established on bot startup using connection string from Railway environment variable
- For `/pet`: Query database → increment → update row → record a `pet_events` row
- For `/stats`: Query database → retrieve pet_count and relationship
- If user doesn't exist in database, insert new row with pet_count = 1
- A user's row is created on their first `/pet`, never before
- All queries are async (non-blocking)

---

## Cat Mood

The cat tires of being pestered. Each `/pet` is either **friendly** (one of the 3
friendly responses) or **standoffish** (one of the 3 standoffish responses), chosen
at random but weighted by how much the user has petted recently.

A user with no pets in the previous 10 minutes has a **70%** chance of a friendly
reaction. Every pet already inside that 10-minute window subtracts 10 percentage
points, floored at zero:

| Recent pets (last 10 min) | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7+ |
|---|---|---|---|---|---|---|---|---|
| Chance of a friendly response | 70% | 60% | 50% | 40% | 30% | 20% | 10% | 0% |

The window slides continuously rather than resetting on a timer, so the cat's
patience returns gradually as a user goes quiet. From the 7th recent pet onward the
cat is reliably standoffish until the window clears.

---

## Relationship Meter

Every player has a relationship score with the cat, ranging from **-100 to 100**.

**Starting value: 50.** The cat is friendly toward newcomers and has to be annoyed
into hostility. This is a starting disposition, not a resting one — see the drift
below.

**Per pet:** a friendly reaction adds 5; a standoffish reaction subtracts 5. The
score is clamped at both ends, so it never leaves the -100 to 100 range.

### Nightly drift toward neutral

At **midnight Pacific** each day, any player who did **not** `/pet` at all during
that day drifts back toward 0:

| Score at midnight | Change | Stops at |
|---|---|---|
| 10 or above | -10 | 0 (never below) |
| Between -19 and 9 | no change | — |
| -20 or below | +20 | 0 (never above) |

**Rules and edge cases:**
- Petting even once during a day cancels that night's drift entirely.
- The thresholds are re-evaluated each night, so a score of 15 drops to 5 and then
  stops, because 5 is below the 10 threshold. Drift never crosses zero.
- **0 is the resting point.** A new player who never returns drifts 50 → 40 → 30 →
  20 → 10 → 0 across five idle days.
- Nights the bot was offline for are settled when it next starts, so an outage does
  not silently skip a player's drift, and no night is ever applied twice.
- Midnight follows Pacific *local* time, so it tracks daylight saving rather than
  drifting by an hour twice a year.

---

## Slash Commands

### 1. `/pet`

**Trigger:** User types `/pet`

**Behavior:**
1. Get the user's ID
2. Query database: check if user exists
3. If user exists: increment pet_count by 1; if not: insert new user with pet_count = 1
4. Retrieve updated pet_count from database
5. Select a random response from the 6 predefined responses
6. Send a response message containing:
   - The random response text
   - The user's updated pet count (e.g., "You've petted the cat 5 times!")

**Response Examples (6 options - writers will iterate later):**

The cat's mood is an even coin flip between welcoming and prickly.

*Friendly:*
- "The cat purrs contentedly as you pet it, tail curling like smoke."
- "The cat meows and rubs against your leg, eyes glinting in the dark."
- "The cat stretches, blinks slowly at you, and vanishes for just a second."

*Standoffish:*
- "The cat meows incessantly until you pet it again."
- "The cat startles, hissing at you."
- "The cat gives you a warning bat with its paw."

**Response Format:**
```
[Random response text]

Total pets: 42
```

**Error Handling:**
- If database connection fails, log error and send user-friendly error message
- Handle database query errors gracefully
- Retry logic for transient database issues

### 2. `/stats`

**Trigger:** User types `/stats`

**Behavior:**
1. Get the user's ID
2. Query database for user's pet_count and relationship (default to 0 if user not found)
3. Send a response message displaying their pet count and relationship score

**Response Format:**
```
Your cat petting stats:
Total pets: 42
Relationship: 65
```

**Error Handling:**
- If user not in database, display 0 and offer to start petting with `/pet`
- Handle database query errors gracefully

---

## Project Structure

```
discord-bot/
├── bot.py                 # Main bot file
├── database.py            # SQLAlchemy models and database functions
├── requirements.txt       # Python dependencies
├── .env.example           # Template for environment variables
├── .gitignore             # Ignore .env and __pycache__
├── railway.json           # Railway configuration (optional)
└── README.md              # Setup instructions
```

### Key Files

**bot.py** (main file)
- Import discord.py, database module, and async utilities
- Set up bot intents
- Initialize bot with command prefix (for slash commands: none needed)
- On bot startup: establish database connection from `DATABASE_URL` env var, initialize tables
- Define `/pet` slash command handler (calls `database.increment_pet_count()`)
- Define `/stats` slash command handler (calls `database.get_pet_count()`)
- Handle database connection lifecycle (connect on startup, cleanup on shutdown)
- `if __name__ == "__main__":` block to run bot with token from environment

**database.py** (database layer)
- Define SQLAlchemy `User` model matching the schema
- Implement async database functions:
  - `init_db()` — establish connection and create tables
  - `increment_pet_count(user_id)` — insert or update user, return new count
  - `get_pet_count(user_id)` — retrieve user's pet count (0 if not found)
  - `close_db()` — cleanup database connection
- Handle connection pooling with asyncpg
- Error handling and logging for database operations

**requirements.txt**
```
discord.py==2.3.2
python-dotenv==1.0.0
sqlalchemy==2.0.23
asyncpg==0.29.0
```

**Environment Variables (.env)**
- `DISCORD_TOKEN` — Discord bot token (from Developer Portal)
- `DATABASE_URL` — PostgreSQL connection string (provided by Railway, e.g., `postgresql://user:pass@host:port/dbname`)

**Database Setup (Railway)**
- PostgreSQL database automatically provisioned when you add a database to your Railway project
- Railway provides `DATABASE_URL` environment variable automatically
- No manual database creation needed; SQLAlchemy creates tables on first run

---

## Implementation Checklist

### Setup
- [ ] Create Python project directory
- [ ] Create `requirements.txt` with all dependencies listed
- [ ] Create `.gitignore` (include `.env`, `__pycache__`, `*.pyc`)
- [ ] Create `.env.example` with `DISCORD_TOKEN=` and `DATABASE_URL=`
- [ ] Create `bot.py`
- [ ] Create `database.py`
- [ ] Set up Railway account and create a new project

### Database Setup (database.py)
- [ ] Import SQLAlchemy, asyncpg, and async utilities
- [ ] Define `User` SQLAlchemy model with columns: id, pet_count, created_at, updated_at
- [ ] Create `init_db()` function to establish connection and create tables
- [ ] Create `increment_pet_count(user_id)` async function
  - [ ] Try to find user by ID
  - [ ] If exists: increment pet_count
  - [ ] If not exists: insert new user with pet_count = 1
  - [ ] Return updated pet_count
- [ ] Create `get_pet_count(user_id)` async function
  - [ ] Query database for user
  - [ ] Return pet_count (or 0 if not found)
- [ ] Create `close_db()` function for cleanup
- [ ] Add error handling and logging

### Core Bot Structure (bot.py)
- [ ] Import necessary modules (discord, database, os, random, dotenv, etc.)
- [ ] Load environment variables with `python-dotenv`
- [ ] Set up bot intents (use default for MVP)
- [ ] Initialize Discord client
- [ ] Add `on_ready()` event handler
  - [ ] Call `database.init_db()` to establish connection
  - [ ] Print confirmation when connected

### Slash Commands
- [ ] Implement `/pet` command
  - [ ] Get user ID from context
  - [ ] Call `database.increment_pet_count(user_id)`
  - [ ] Pick random response from list
  - [ ] Send response with random text and updated count
  - [ ] Add error handling
- [ ] Implement `/stats` command
  - [ ] Get user ID from context
  - [ ] Call `database.get_pet_count(user_id)`
  - [ ] Format and send stats message
  - [ ] Handle user not found gracefully

### Robustness
- [ ] Handle database connection failures
- [ ] Handle query errors with try/except
- [ ] Add logging for all database operations
- [ ] Graceful shutdown: cleanup database connection on bot close
- [ ] Add user-friendly error messages if database is unavailable

### Testing (Local)
- [ ] Set up Railway account and PostgreSQL database
- [ ] Copy `DATABASE_URL` from Railway to `.env`
- [ ] Run bot locally: `python bot.py`
- [ ] Test `/pet` command 5+ times to verify counter increments
- [ ] Verify data persists in Railway PostgreSQL
- [ ] Test `/stats` to verify count displays correctly
- [ ] Test `/pet` with multiple user accounts to verify isolation
- [ ] Restart bot and verify data persists from database
- [ ] Test error case: disconnect database and verify graceful error handling

---

## Deployment Notes

**For Development (Local Machine):**
1. Create `.env` file with:
   ```
   DISCORD_TOKEN=your_token_here
   DATABASE_URL=postgresql://user:password@localhost:5432/catbot
   ```
2. Install dependencies: `pip install -r requirements.txt`
3. Run bot locally: `python bot.py`
4. (Optional: set up local PostgreSQL, or use Railway's free tier for testing)

**For Production (Railway):**
1. Push code to GitHub
2. Create new project on Railway
3. Connect GitHub repo to Railway
4. Add PostgreSQL database to Railway project:
   - Railway auto-provides `DATABASE_URL` environment variable
5. Add environment variable `DISCORD_TOKEN` in Railway dashboard
6. Railway automatically deploys from GitHub and runs `python bot.py`
7. Monitor logs in Railway dashboard for errors
8. Set up email alerts for crashes (Railway feature)

**Railway Best Practices:**
- Set Procfile to ensure bot starts correctly:
  ```
  worker: python bot.py
  ```
- Use Railway's built-in PostgreSQL (included in free tier during testing)
- Monitor resource usage in Railway dashboard
- Keep bot.py code clean to minimize startup time

---

## Important Constraints & Decisions

1. **PostgreSQL Database:** Using Railway's built-in PostgreSQL for reliability and scalability. Better than JSON/SQLite for production use.
2. **Railway Hosting:** Using Railway for both dev/testing and production. Auto-deployment from GitHub, built-in database support, and $5/month free credit.
3. **SQLAlchemy ORM:** Using SQLAlchemy for async database access. Cleaner than raw asyncpg, easier to expand for future features.
4. **Async/Await:** All database operations are async (non-blocking), so Discord bot responsiveness is never impacted.
5. **Slash Commands Only:** No prefix commands for MVP; slash commands are modern Discord standard.
6. **Random Responses:** Pick at random from the 6 strings, weighted by the cat's mood rather than evenly — see Cat Mood above. The two pools (friendly, standoffish) are chosen between first, then a line is picked uniformly from within the chosen pool.
7. **Per-User Isolation:** Each user's counter is independent and persists across sessions via database.
8. **No Authentication:** Discord handles auth via bot token; no additional security needed for MVP.

---

## Iteration Notes for Claude Code

- Writers will provide actual response texts later; use placeholder examples for now
- Response format (text + count display) can be refined based on Discord message best practices
- Consider using Discord embeds for nicer `/stats` display (but simple text is fine for MVP)
- Random responses should feel conversational and match the spooky Halloween theme
- Code should be clean and well-commented for future expansion

---

## Success Criteria

- [ ] Bot responds to `/pet` and increments counter via database
- [ ] Bot responds to `/stats` and displays correct count from database
- [ ] Multiple users can pet independently with separate database records
- [ ] Data persists in PostgreSQL when bot restarts
- [ ] Bot runs on Railway without errors
- [ ] Bot deployed from GitHub to Railway with auto-restarts on crash
- [ ] No hardcoded bot token or database URL in code (uses environment variables)
- [ ] Database connection established and tables created on startup
- [ ] Async database operations don't block Discord command responsiveness
- [ ] Code is ready for Phase 2 expansion (writers adding content)

---

## Questions for Claude Code (If Needed)

- Should responses use Discord embeds or plain text? (MVP: plain text is fine)
- Any logging recommendations for debugging in production Railway? (Use Railway logs dashboard)
- Should the bot have a startup message in a designated channel? (MVP: optional, not required)
- Any rate limiting needed for the `/pet` command? (MVP: not needed)
- Connection pool size for PostgreSQL? (Default SQLAlchemy settings fine for MVP scale)
- Should we add database migration tooling? (MVP: not needed; SQLAlchemy handles schema)
- Any specific error messages for database unavailability? (Keep user-friendly, suggest retry)

