"""Idempotent helpers shared by Alembic migrations (safe on databases created from docs/*.sql)."""
import sqlalchemy as sa
from alembic import op


def has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def add_column(table: str, column: sa.Column):
    if not has_column(table, column.name):
        op.add_column(table, column)


def drop_column(table: str, column: str):
    if has_table(table) and has_column(table, column):
        op.drop_column(table, column)


def insert_if_missing(table: str, exists_where: str, columns: str, values: str, params: dict | None = None):
    """Insert a seed row unless it exists. Supplies an id only if the table's id column has no default."""
    bind = op.get_bind()
    params = params or {}
    if bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE {exists_where}"), params).first():
        return
    has_default = bind.execute(
        sa.text(
            "SELECT column_default IS NOT NULL OR is_identity = 'YES' "
            "FROM information_schema.columns WHERE table_name = :table AND column_name = 'id'"
        ),
        {"table": table},
    ).scalar()
    if has_default:
        bind.execute(sa.text(f"INSERT INTO {table} ({columns}) SELECT {values}"), params)
    else:
        bind.execute(
            sa.text(f"INSERT INTO {table} (id, {columns}) SELECT (SELECT COALESCE(MAX(id), 0) + 1 FROM {table}), {values}"),
            params,
        )


def seed_misc(category: str, value: str):
    insert_if_missing(
        "miscellaneous_data", "category = :c AND value = :v", "category, value, created_at", ":c, :v, NOW()",
        {"c": category, "v": value},
    )


def seed_role(name: str):
    insert_if_missing(
        "roles", "LOWER(name) = :n", "name, status, created_time",
        ":n, (SELECT id FROM miscellaneous_data WHERE category = 'status' AND value = 'active' LIMIT 1), NOW()",
        {"n": name},
    )
