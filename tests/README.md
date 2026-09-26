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
| `test_cat.py` | Pet counting, the recent-pet window, mood weighting, the relationship meter and its clamps |
| `test_decay.py` | The nightly drift toward neutral, catch-up after an outage, and Pacific day boundaries across DST |
| `test_isolation.py` | Cross-server scoping, table by table |
| `test_world.py` | Rooms, things, `/look` and inventory — the queries phase 2a step 4 rewrites |
| `test_house.py` | The navigation graph, exit resolution, thread naming |
| `test_threads.py` | Thread build, rebuild, the keep-alive sweep and permission reporting, against `fake_discord.py` |

## Foreign keys

SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON` is set on every
connection. `database._enforce_sqlite_foreign_keys` sets it, so the fallback
backend refuses the same rows PostgreSQL refuses and the suite means the same
thing in both places. `test_foreign_keys_are_enforced_on_this_backend` asserts
the setting directly, so a regression names its own cause rather than surfacing
as an unrelated failure somewhere else.

## Cohorts

Gone as of phase 2a step 4. Two columns survive the removal —
`player_game_state.room_version_assignment` and `things.cohort` — because the
startup migration can only add columns, never drop them. Nothing reads either.

`test_world.py` ends with a short section that backfills both columns the way a
pre-2a database would have them and checks the old values are genuinely inert:
a thing that used to be cohort-B only is visible to everyone, and a rebuild
places players by room alone.
