# Reference data seeding

Static reference data is loaded by an explicit, idempotent command. It is **not** run on
application startup and **not** part of Alembic migrations.

| Dataset | Table | Natural key | Source file |
|---|---|---|---|
| `lookups` | `miscellaneous_data` | `(category, value)` | `src/seeds/data/lookups.json` |
| `roles` | `roles` | `lower(name)` | `src/seeds/data/lookups.json` |
| `states` | `states` | `lower(state_name)` | `src/seeds/data/locations.json` |
| `districts` | `districts` | `(state, lower(district_name))` | `src/seeds/data/locations.json` |

Datasets always run in this dependency order, in a single transaction.

## Where the data comes from

- **`locations.json`**: the 28 states and 491 districts from `docs/tables_scripts.txt`, in the
  same order. The script's duplicated Nagaland block was dropped. Assam, Bihar and Mizoram have no
  districts in the script, and several lists stop early (for example Uttar Pradesh ends at Lucknow),
  so add the missing districts here, not in SQL.
- **`lookups.json`**: only values the application code reads:

| Category | Values | Used by |
|---|---|---|
| `status` | active, inactive, suspended | login, users, admin, crops/soil/fertilizers |
| `answer` | yes | `permissions_service` |
| `order_status` | the 12 lifecycle states | `orders_model.ORDER_STATUSES`, `order_core` |
| `payment_status` | initiated, pending, paid, failed, refund_pending, refunded | `transactions_model`, payments |
| roles | farmer, vendor, admin | registration, `role_guard` |

`docs/tables_scripts.txt` is kept for reference. Seed from the JSON files, not from that script.

## How it behaves

- **Idempotent.** Rows are matched by natural key, never by id. Missing rows are inserted, so
  running the command again changes nothing.
- **Updates only predefined fields.** If a row exists with different casing or spacing (for
  example `andhra pradesh`), only the name is corrected to its canonical form.
- **Never touches runtime-managed fields:** ids, `status` (an admin-deactivated role stays
  deactivated), `created_by`, `created_at` and existing references. New rows get
  `created_by = NULL`, since they come from the system and not a user.
- **Never deletes.** Removing an entry from a JSON file does not remove it from the database.
- **All or nothing.** Everything runs in one transaction under a Postgres advisory lock, so
  concurrent runs wait for each other. On any error everything is rolled back.
- **Leaves an audit trail.** A successful run writes one `audit_logs` row (`seed.applied`) with
  the counts and the SHA-256 checksum of the seed files.
- **Refuses to work on duplicates.** If a table already contains duplicate natural keys, the
  command stops without changing anything. Migration `004` merges existing duplicates and adds
  unique indexes that enforce the keys at database level.
- **PostgreSQL only.**

## Running it

Run it in this order when setting up or updating any environment (local, staging, production):

```bash
alembic upgrade head          # 1. schema (004 also merges duplicate reference rows)
python -m src.seeds --dry-run # 2a. optional: preview the changes, then roll back
python -m src.seeds           # 2b. apply reference data
uvicorn main:smart_agri_tech_app --host 0.0.0.0 --port $BACKEND_PORT   # 3. start the app
```

The connection comes from the same `POSTGRES_*` variables as the app (`.env` is loaded).

| Option | Meaning |
|---|---|
| `--dry-run` | Do everything, print what would change, then roll back |
| `--only lookups,roles` | Run a subset (dependencies must already be seeded) |
| `--database-url URL` | Override the connection (`postgresql+psycopg2://...`) |
| `--json` | Machine-readable output for CI/CD logs |
| `--verbose` | List every inserted or updated row |

Exit codes: `0` success; `1` seeding failed and was rolled back; `2` invalid seed files or
arguments, nothing attempted.

Example output:

```
Reference data applied. Seed data checksum 3f9c2a1b7e0d
  lookups    inserted=0    updated=0    unchanged=22
  roles      inserted=0    updated=0    unchanged=3
  states     inserted=0    updated=0    unchanged=28
  districts  inserted=0    updated=0    unchanged=491
```

### Docker / CI

Add it as an explicit deploy step after migrations. For example:

```bash
docker compose run --rm backend sh -c "alembic upgrade head && python -m src.seeds"
```

## Changing reference data

1. Edit the JSON file in a pull request; the git history is the version history.
2. Run `pytest tests/seeds`. The validation tests reject duplicates, blank or over-long names,
   and malformed files.
3. Deploy, then run `python -m src.seeds`. The output and the `seed.applied` audit row show
   exactly what changed.

Rename a district by correcting its spelling; only casing and spacing are matched automatically.
A real rename (a different name) is a data migration, because the seeder would otherwise insert
a second row and leave existing references pointing at the old one.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/seeds                                   # file validation tests always run
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/scratch pytest tests/seeds
```

With `TEST_DATABASE_URL` set, each test creates and drops its own temporary schema, so any
writable database works. The tests cover:

- first run inserts everything;
- second run inserts and updates nothing, and ids stay stable;
- no duplicates, plus the database unique index rejects case and space variants;
- canonical renames that preserve status and timestamps;
- full rollback when a later dataset fails;
- dry-run leaving nothing behind;
- dependency errors for partial runs;
- refusal on pre-existing duplicates;
- the CLI end to end.
