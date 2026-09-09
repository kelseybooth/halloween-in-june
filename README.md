# Halloween in June — Cat Petting Bot

Phase 1 MVP of a Halloween haunted-house Discord bot. Users pet a cat with `/pet`;
each user's total persists in a database and is readable via `/stats`.

## Commands

| Command | Description |
|---|---|
| `/pet` | Pet the cat. Increments your counter, returns one of three responses. |
| `/stats` | Show your total pet count. |

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

### Database

The backend is chosen from `DATABASE_URL`:

- **unset** — a local SQLite file (`catbot.db`) is created automatically. No setup
  required; this is the default for local development.
- **set** — used as a PostgreSQL connection string via asyncpg. Stock
  `postgresql://` URLs are rewritten to `postgresql+asyncpg://` automatically, so
  Railway's variable works unchanged.

Tables are created on startup, so there is no migration step.

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
