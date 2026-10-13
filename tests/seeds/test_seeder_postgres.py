"""Seeder behaviour against PostgreSQL: repeatability, uniqueness, preservation of runtime data, rollback."""
from datetime import datetime

import pytest
from sqlalchemy import func, select, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.data_models.districts_model import Districts
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.platform_model import AuditLogs
from src.data_models.roles_model import Roles
from src.data_models.states_model import States
from src.seeds.__main__ import main
from src.seeds.seeder import Seeder, SeedError, load_seed_data

DATA = load_seed_data()
EXPECTED = {
    Miscellaneous_Data: sum(len(v) for v in DATA["misc"].values()),
    Roles: len(DATA["roles"]),
    States: len(DATA["states"]),
    Districts: sum(len(s["districts"]) for s in DATA["states"]),
}


def _counts(session):
    return {model: session.execute(select(func.count()).select_from(model)).scalar() for model in EXPECTED}


def _run(session_factory, **kwargs):
    with session_factory() as session:
        return {r.name: r for r in Seeder(session, DATA).run(**kwargs)}


def test_first_run_inserts_all_reference_data(session_factory):
    results = _run(session_factory)
    assert {name: r.inserted for name, r in results.items()} == {
        "lookups": EXPECTED[Miscellaneous_Data], "roles": EXPECTED[Roles],
        "states": EXPECTED[States], "districts": EXPECTED[Districts],
    }
    with session_factory() as session:
        assert _counts(session) == EXPECTED
        assert session.execute(select(func.count()).select_from(States).where(States.created_by.is_not(None))).scalar() == 0
        assert session.execute(select(AuditLogs.action)).scalars().all() == ["seed.applied"]


def test_second_run_changes_nothing(session_factory):
    _run(session_factory)
    with session_factory() as session:
        ids_before = session.execute(select(Districts.id).order_by(Districts.id)).scalars().all()
    results = _run(session_factory)
    assert all(r.inserted == 0 and r.updated == 0 for r in results.values())
    assert results["districts"].unchanged == EXPECTED[Districts]
    with session_factory() as session:
        assert _counts(session) == EXPECTED
        assert session.execute(select(Districts.id).order_by(Districts.id)).scalars().all() == ids_before


def test_natural_keys_are_unique_and_enforced_by_the_database(session_factory):
    _run(session_factory)
    _run(session_factory)
    with session_factory() as session:
        dupes = session.execute(
            select(Districts.state_id, func.lower(Districts.district_name), func.count())
            .group_by(Districts.state_id, func.lower(Districts.district_name)).having(func.count() > 1)
        ).all()
        assert dupes == []
        state_id, name = session.execute(select(Districts.state_id, Districts.district_name).limit(1)).one()
        with pytest.raises(IntegrityError):
            session.execute(insert(Districts).values(state_id=state_id, district_name=f" {name.upper()} "))
            session.flush()


def test_canonical_names_are_updated_but_runtime_fields_are_preserved(session_factory):
    created = datetime(2020, 1, 1)
    with session_factory() as session:
        session.execute(insert(Miscellaneous_Data).values(category="status", value="inactive", created_at=created))
        inactive_id = session.execute(select(Miscellaneous_Data.id)).scalar_one()
        session.execute(insert(Roles).values(name="FARMER", status=inactive_id, created_time=created))
        session.execute(insert(States).values(state_name="andhra pradesh", created_at=created))
        session.commit()
        role_id = session.execute(select(Roles.id)).scalar_one()
        state_id = session.execute(select(States.id)).scalar_one()

    results = _run(session_factory)
    assert results["roles"].updated == 1 and results["states"].updated == 1

    with session_factory() as session:
        role = session.execute(select(Roles).where(Roles.id == role_id)).scalar_one()
        assert role.name == "farmer"
        assert role.status == inactive_id  # runtime-managed: an admin deactivated it, the seeder must not re-enable it
        assert role.created_time == created
        state = session.execute(select(States).where(States.id == state_id)).scalar_one()
        assert state.state_name == "Andhra Pradesh"
        assert state.created_at == created
        assert _counts(session) == EXPECTED


def test_failure_rolls_back_every_dataset(session_factory, monkeypatch):
    def boom(self):
        self.session.execute(text("SELECT * FROM table_that_does_not_exist"))

    monkeypatch.setattr(Seeder, "seed_districts", boom)
    with pytest.raises(SeedError, match="rolled back"):
        _run(session_factory)
    with session_factory() as session:
        assert all(count == 0 for count in _counts(session).values())
        assert session.execute(select(func.count()).select_from(AuditLogs)).scalar() == 0


def test_dry_run_reports_changes_without_persisting(session_factory):
    results = _run(session_factory, dry_run=True)
    assert results["districts"].inserted == EXPECTED[Districts]
    with session_factory() as session:
        assert all(count == 0 for count in _counts(session).values())


def test_partial_dataset_run_respects_dependencies(session_factory):
    _run(session_factory, datasets=("lookups", "roles"))
    with session_factory() as session:
        counts = _counts(session)
    assert counts[Roles] == EXPECTED[Roles] and counts[States] == 0
    with pytest.raises(SeedError, match="seed 'states' before 'districts'"):
        _run(session_factory, datasets=("districts",))


def test_existing_duplicates_abort_without_changes(engine_without_indexes):
    factory = sessionmaker(bind=engine_without_indexes, future=True)
    with factory() as session:
        session.execute(insert(States).values(state_name="Goa"))
        state_id = session.execute(select(States.id)).scalar_one()
        session.execute(insert(Districts).values(state_id=state_id, district_name="North Goa"))
        session.execute(insert(Districts).values(state_id=state_id, district_name="north goa"))
        session.commit()
    with factory() as session:
        with pytest.raises(SeedError, match="duplicate rows"):
            Seeder(session, DATA).run()
    with factory() as session:
        assert session.execute(select(func.count()).select_from(Miscellaneous_Data)).scalar() == 0
        assert session.execute(select(func.count()).select_from(Districts)).scalar() == 2


def test_cli_end_to_end(engine, capsys, monkeypatch):
    # The CLI builds its own engine; libpq's PGOPTIONS points it at this test's schema.
    with engine.connect() as conn:
        search_path = conn.execute(text("SHOW search_path")).scalar()
    monkeypatch.setenv("PGOPTIONS", f"-csearch_path={search_path}")
    url = engine.url.render_as_string(hide_password=False)

    assert main(["--database-url", url, "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert main(["--database-url", url]) == 0
    capsys.readouterr()
    assert main(["--database-url", url, "--json"]) == 0
    output = capsys.readouterr().out
    assert '"inserted": 0' in output and '"updated": 0' in output
