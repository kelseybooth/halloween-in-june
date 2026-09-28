# Tests

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Before you push

```
git config core.hooksPath .githooks
```

One command per clone. It points git at `.githooks/pre-push`, which runs this suite
and refuses the push if it fails — the stand-in for a required status check, which
this repository's plan does not offer. `git push --no-verify` skips it.

Everything runs against a throwaway SQLite file, one per test — no Postgres, no
Discord, no network. CI runs the same command on Python 3.13.

| File | Covers |
| --- | --- |
| `test_cat.py` | Pet counting, the recent-pet window, mood weighting, the relationship meter, `relationship_at_pet` |
| `test_decay.py` | The nightly drift toward neutral, catch-up after an outage, and Pacific day boundaries across DST |
| `test_isolation.py` | Cross-server scoping, and where phase 2b moved that line |
| `test_content.py` | Parsing and validating the seven content files; every validator, fed the break it exists to catch |
| `test_schema.py` | The content/world-state split, table by table, and migrating a database that predates 2b |
| `test_loader.py` | Loading content, first placement, reload semantics, the orphan abort, `--fresh`, load-on-boot |
| `test_drops.py` | Drop arrival — dated, event and manual — and the text each one resolves to |
| `test_world.py` | The house from the content tables: rooms, exits, `/look`, `/inventory` |
| `test_threads.py` | Thread build, rebuild, the keep-alive sweep and permission reporting, against `fake_discord.py` |
| `test_reach.py` | Resolution: which thing a player meant, and which copy — scope per verb, sources and their yields |
| `test_moving.py` | Taking, dropping, transforming and recording uses, including two players racing for the last copy |
| `test_verbs.py` | `/take`, `/drop` and the four `/use` branches, driven through the handlers |
| `test_look.py` | `/look` in three shapes, the `Also here:` listing rules, truncation, `/inventory` |
| `test_restocking.py` | The restock scheduler: derived times, both placements, catch-up, admin overrides |
| `test_craving.py` | Alexa's two replies, and the daily craving — drawing, judging, and the tally |
| `test_admin_config.py` | `/admin_config`, and the shape of the ten-command list |

## Foreign keys

SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON` is set on every
connection. `database._enforce_sqlite_foreign_keys` sets it, so the fallback
backend refuses the same rows PostgreSQL refuses and the suite means the same
thing in both places. `test_foreign_keys_are_enforced_on_this_backend` asserts
the setting directly, so a regression names its own cause rather than surfacing
as an unrelated failure somewhere else.

## Content versus world state

The split phase 2b introduced, and the one most worth not breaking. Content —
rooms, things, text, defaults, drops, restocks — is global and loaded from the
files; nothing mutates it at runtime, which is what makes a reload safe. World
state is per guild and is the only thing a player can change.

`test_schema.py` asserts it per table in both directions, because a content
table that grew a `guild_id` or a world-state table that lost one would fail
quietly and in opposite ways.

## Cohorts

Gone as of phase 2a step 4. Two columns survive the removal —
`player_game_state.room_version_assignment` and `things.cohort` — because the
startup migration can only add columns, never drop them. Nothing reads either.

`test_world.py` ends with a short section that backfills both columns the way a
pre-2a database would have them and checks the old values are genuinely inert:
a thing that used to be cohort-B only is visible to everyone, and a rebuild
places players by room alone.
