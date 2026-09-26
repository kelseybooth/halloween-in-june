# Tests

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

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

## Two known divergences, marked `xfail`

SQLite does not enforce foreign keys unless `PRAGMA foreign_keys=ON` is set on
each connection, and nothing sets it. PostgreSQL does enforce them. So
`add_to_inventory` with a `thing_id` that does not exist is refused in
production and silently accepted locally, leaving an orphaned row that
`inventory_count` counts and `get_inventory` does not.

Both tests are marked `xfail(strict=False)`: they fail here, pass on Postgres,
and will turn green everywhere if the pragma is ever enabled. They are left in
rather than deleted because the divergence is the point — it is the class of bug
running CI on the fallback backend can hide.

## Cohorts

Cohort *placement* has light coverage; cohort *assignment* has none, because
phase 2a step 4 deletes it. What the tests pin down instead is thing visibility
— exclusive versus copyable, carried versus not — which has to survive that
change unaltered.
