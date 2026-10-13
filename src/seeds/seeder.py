"""
Idempotent seeding of static reference data (lookup values, roles, states, districts).

Rules
- Rows are matched by natural key, never by id: (category, value) for lookups, lower(name) for
  roles and states, (state, lower(name)) for districts.
- Missing rows are inserted. For existing rows only the predefined field (the canonical spelling
  of the name) is updated; runtime-managed fields (status, created_by, timestamps, ids) are never
  touched.
- Everything runs in one transaction guarded by a Postgres advisory lock: either all datasets
  are applied or none are. `dry_run` performs the same work and then rolls back.
"""
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, insert, update, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.data_models.districts_model import Districts
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.platform_model import AuditLogs
from src.data_models.roles_model import Roles
from src.data_models.states_model import States

DATA_DIR = Path(__file__).parent / "data"
ADVISORY_LOCK_KEY = 7_302_212  # distinct from the scheduler's lock
DATASETS = ("lookups", "roles", "states", "districts")  # dependency order


class SeedError(Exception):
    """Seeding could not be completed; nothing was committed."""


class SeedValidationError(SeedError):
    """The version-controlled seed files are invalid."""


@dataclass
class DatasetResult:
    name: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    details: list[str] = field(default_factory=list)


def _norm(value: str) -> str:
    """Natural-key normalisation; matches the lower(btrim(...)) unique indexes from migration 004."""
    return value.strip().lower()


# ---- seed files ------------------------------------------------------------------------

def load_seed_data(data_dir: Path = DATA_DIR) -> dict:
    """Load and validate the seed files. Raises SeedValidationError on any problem."""
    try:
        lookups = json.loads((data_dir / "lookups.json").read_text(encoding="utf-8"))
        locations = json.loads((data_dir / "locations.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeedValidationError(f"Cannot read seed data: {e}") from e

    errors = []
    misc = lookups.get("miscellaneous_data")
    if not isinstance(misc, dict) or not misc:
        errors.append("lookups.json: 'miscellaneous_data' must be a non-empty object")
        misc = {}
    for category, values in misc.items():
        if not category or len(category) > 50:
            errors.append(f"lookups.json: invalid category {category!r}")
        if not isinstance(values, list) or not values:
            errors.append(f"lookups.json: category {category!r} needs a non-empty list")
            continue
        if len(set(values)) != len(values):
            errors.append(f"lookups.json: duplicate values in category {category!r}")
        errors += [f"lookups.json: invalid value {v!r} in {category!r}" for v in values
                   if not isinstance(v, str) or not v.strip() or len(v) > 150]

    roles = lookups.get("roles", [])
    if not roles or len({_norm(r) for r in roles}) != len(roles):
        errors.append("lookups.json: 'roles' must be a non-empty list of unique names")
    errors += [f"lookups.json: role name too long {r!r}" for r in roles if len(r) > 30]

    states = locations.get("states", [])
    seen_states = set()
    for state in states:
        name = state.get("name", "")
        if not name.strip() or len(name) > 100:
            errors.append(f"locations.json: invalid state name {name!r}")
        if _norm(name) in seen_states:
            errors.append(f"locations.json: duplicate state {name!r}")
        seen_states.add(_norm(name))
        seen_districts = set()
        for district in state.get("districts", []):
            if not district.strip() or len(district) > 100:
                errors.append(f"locations.json: invalid district {district!r} in {name!r}")
            if _norm(district) in seen_districts:
                errors.append(f"locations.json: duplicate district {district!r} in {name!r}")
            seen_districts.add(_norm(district))
    if not states:
        errors.append("locations.json: 'states' must not be empty")

    if errors:
        raise SeedValidationError("Invalid seed data:\n  - " + "\n  - ".join(errors))
    checksum = hashlib.sha256(
        (data_dir / "lookups.json").read_bytes() + (data_dir / "locations.json").read_bytes()
    ).hexdigest()
    return {"misc": misc, "roles": roles, "states": states, "checksum": checksum}


# ---- seeder ------------------------------------------------------------------------------

class Seeder:
    def __init__(self, session: Session, data: dict | None = None, now: datetime | None = None):
        self.session = session
        self.data = data or load_seed_data()
        self.now = now or datetime.utcnow()

    @staticmethod
    def _duplicates_error(table: str, keys: list) -> SeedError:
        return SeedError(
            f"{table} already contains duplicate rows for {keys[:5]}. Run `alembic upgrade head` "
            "(migration 004 merges duplicates) before seeding."
        )

    def seed_lookups(self) -> DatasetResult:
        result = DatasetResult("lookups")
        rows = self.session.execute(select(Miscellaneous_Data.category, Miscellaneous_Data.value)).all()
        existing = [(c, v) for c, v in rows]
        dupes = [k for k in set(existing) if existing.count(k) > 1]
        if dupes:
            raise self._duplicates_error("miscellaneous_data", dupes)
        existing = set(existing)
        for category, values in self.data["misc"].items():
            for value in values:
                if (category, value) in existing:
                    result.unchanged += 1
                    continue
                self.session.execute(insert(Miscellaneous_Data).values(
                    category=category, value=value, created_at=self.now))
                result.inserted += 1
                result.details.append(f"+ {category}/{value}")
        return result

    def seed_roles(self) -> DatasetResult:
        result = DatasetResult("roles")
        rows = self.session.execute(select(Roles.id, Roles.name)).all()
        by_key: dict[str, list] = {}
        for role_id, name in rows:
            by_key.setdefault(_norm(name or ""), []).append((role_id, name))
        dupes = [k for k, v in by_key.items() if len(v) > 1 and k in {_norm(r) for r in self.data["roles"]}]
        if dupes:
            raise self._duplicates_error("roles", dupes)
        active_id = self.session.execute(select(Miscellaneous_Data.id).where(
            Miscellaneous_Data.category == "status", Miscellaneous_Data.value == "active")).scalar_one()
        for name in self.data["roles"]:
            match = by_key.get(_norm(name))
            if not match:
                # status is set only on insert; afterwards it's managed at runtime (admins may deactivate roles)
                self.session.execute(insert(Roles).values(name=name, status=active_id, created_time=self.now))
                result.inserted += 1
                result.details.append(f"+ {name}")
            elif match[0][1] != name:
                self.session.execute(update(Roles).where(Roles.id == match[0][0])
                                     .values(name=name, updated_time=self.now))
                result.updated += 1
                result.details.append(f"~ {match[0][1]!r} -> {name!r}")
            else:
                result.unchanged += 1
        return result

    def _state_ids(self) -> dict[str, tuple[int, str]]:
        by_key: dict[str, list] = {}
        for state_id, name in self.session.execute(select(States.id, States.state_name)).all():
            by_key.setdefault(_norm(name), []).append((state_id, name))
        dupes = [k for k, v in by_key.items() if len(v) > 1]
        if dupes:
            raise self._duplicates_error("states", dupes)
        return {k: v[0] for k, v in by_key.items()}

    def seed_states(self) -> DatasetResult:
        result = DatasetResult("states")
        existing = self._state_ids()
        for state in self.data["states"]:
            name = state["name"]
            match = existing.get(_norm(name))
            if not match:
                self.session.execute(insert(States).values(state_name=name, created_by=None, created_at=self.now))
                result.inserted += 1
                result.details.append(f"+ {name}")
            elif match[1] != name:
                self.session.execute(update(States).where(States.id == match[0]).values(state_name=name))
                result.updated += 1
                result.details.append(f"~ {match[1]!r} -> {name!r}")
            else:
                result.unchanged += 1
        return result

    def seed_districts(self) -> DatasetResult:
        result = DatasetResult("districts")
        states = self._state_ids()
        by_key: dict[tuple[int, str], list] = {}
        for district_id, state_id, name in self.session.execute(
                select(Districts.id, Districts.state_id, Districts.district_name)).all():
            by_key.setdefault((state_id, _norm(name)), []).append((district_id, name))
        dupes = [k for k, v in by_key.items() if len(v) > 1]
        if dupes:
            raise self._duplicates_error("districts", dupes)
        for state in self.data["states"]:
            state_match = states.get(_norm(state["name"]))
            if not state_match:
                raise SeedError(f"State {state['name']!r} is missing; seed 'states' before 'districts'.")
            state_id = state_match[0]
            for name in state["districts"]:
                match = by_key.get((state_id, _norm(name)))
                if not match:
                    self.session.execute(insert(Districts).values(
                        district_name=name, state_id=state_id, created_by=None, created_at=self.now))
                    result.inserted += 1
                    result.details.append(f"+ {state['name']} / {name}")
                elif match[0][1] != name:
                    self.session.execute(update(Districts).where(Districts.id == match[0][0]).values(district_name=name))
                    result.updated += 1
                    result.details.append(f"~ {match[0][1]!r} -> {name!r}")
                else:
                    result.unchanged += 1
        return result

    def run(self, datasets: tuple[str, ...] | None = None, dry_run: bool = False) -> list[DatasetResult]:
        """Apply the datasets in one transaction. On any error everything is rolled back."""
        datasets = tuple(datasets or DATASETS)
        unknown = set(datasets) - set(DATASETS)
        if unknown:
            raise SeedError(f"Unknown dataset(s): {', '.join(sorted(unknown))}. Choose from {', '.join(DATASETS)}.")
        if self.session.get_bind().dialect.name != "postgresql":
            raise SeedError("Seeding supports PostgreSQL only.")

        runners = {"lookups": self.seed_lookups, "roles": self.seed_roles,
                   "states": self.seed_states, "districts": self.seed_districts}
        results = []
        try:
            inspector = inspect(self.session.connection())
            missing = [t for t in ("miscellaneous_data", "roles", "states", "districts") if not inspector.has_table(t)]
            if missing:
                raise SeedError(f"Tables missing: {', '.join(missing)}. Run `alembic upgrade head` first.")
            has_audit_table = inspector.has_table("audit_logs")
            # Serialise concurrent seed runs (e.g. two deploy jobs); released at commit/rollback.
            self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
            for name in DATASETS:  # always dependency order, whatever order was requested
                if name in datasets:
                    results.append(runners[name]())
            if dry_run:
                self.session.rollback()
            else:
                if has_audit_table:
                    self.session.execute(insert(AuditLogs).values(
                        actor_id=None, actor_role="system", action="seed.applied", entity_type="reference_data",
                        entity_id=self.data["checksum"][:40],
                        after={r.name: {"inserted": r.inserted, "updated": r.updated, "unchanged": r.unchanged}
                               for r in results},
                        created_at=self.now,
                    ))
                self.session.commit()
        except SeedError:
            self.session.rollback()
            raise
        except SQLAlchemyError as e:
            self.session.rollback()
            raise SeedError(f"Database error while seeding; all changes were rolled back: {e}") from e
        return results


def results_as_dict(results: list[DatasetResult]) -> list[dict]:
    return [asdict(r) for r in results]
