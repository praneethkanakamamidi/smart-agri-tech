"""reference data uniqueness: merge duplicate lookup/role/state/district rows and add unique indexes

docs/tables_scripts.txt inserted the Nagaland districts twice and nothing prevented duplicate
lookup rows. For each duplicate group the oldest row (lowest id) is kept: every foreign key that
points at a duplicate is repointed to the kept row before the duplicate is deleted, so no user,
order or profile loses its reference.

Revision ID: 004
Revises: 003
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

# table -> (natural-key SQL, unique index name)
REFERENCE_TABLES = (
    ("miscellaneous_data", "category, value", "uq_miscellaneous_data_category_value"),
    ("roles", "lower(btrim(name))", "uq_roles_name"),
    ("states", "lower(btrim(state_name))", "uq_states_name_ci"),
    ("districts", "state_id, lower(btrim(district_name))", "uq_districts_state_name"),
)


def _referencing_columns(bind, table: str) -> list[tuple[str, str]]:
    return bind.execute(sa.text("""
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = rc.constraint_name AND kcu.constraint_schema = rc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = rc.unique_constraint_name AND ccu.constraint_schema = rc.unique_constraint_schema
        WHERE ccu.table_name = :table AND ccu.column_name = 'id' AND kcu.table_schema = current_schema()
    """), {"table": table}).all()


def merge_duplicates(table: str, key_sql: str) -> int:
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS _seed_dup_map"))
    bind.execute(sa.text(f"""
        CREATE TEMP TABLE _seed_dup_map AS
        SELECT id AS dup_id, MIN(id) OVER (PARTITION BY {key_sql}) AS keep_id FROM {table}
    """))
    bind.execute(sa.text("DELETE FROM _seed_dup_map WHERE dup_id = keep_id"))
    count = bind.execute(sa.text("SELECT COUNT(*) FROM _seed_dup_map")).scalar()
    if count:
        for ref_table, ref_column in _referencing_columns(bind, table):
            bind.execute(sa.text(f"""
                UPDATE {ref_table} AS t SET {ref_column} = m.keep_id
                FROM _seed_dup_map m WHERE t.{ref_column} = m.dup_id
            """))
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id IN (SELECT dup_id FROM _seed_dup_map)"))
    bind.execute(sa.text("DROP TABLE _seed_dup_map"))
    return count


def upgrade() -> None:
    for table, key_sql, index_name in REFERENCE_TABLES:
        merge_duplicates(table, key_sql)
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({key_sql})")


def downgrade() -> None:
    # Merged duplicates are not recreated; only the constraints are removed.
    for _, _, index_name in REFERENCE_TABLES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
