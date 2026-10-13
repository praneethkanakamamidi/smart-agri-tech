"""Schema guard: every foreign key that is queried or cascaded through must have a covering index."""
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

import src.data_models.registry  # noqa: F401  (registers every model on Base.metadata)
from src.db_connections.postgresql_conn import Base

# Seeded lookup tables: rows are never deleted, and nothing lists children by these keys alone.
REFERENCE_TABLES = {
    "miscellaneous_data", "states", "districts", "crops", "soil", "fertilizers",
    "roles", "permissions", "produce_categories",
}
# "Who did it" columns: written for audit, never filtered on; users are anonymised, not deleted.
ACTOR_COLUMNS = {
    "created_by", "updated_by", "reviewed_by", "reviewer_id", "resolved_by", "moderated_by", "actor_id",
    "author_id", "initiated_by", "recorded_by", "changed_by", "cancelled_by", "cancel_requested_by",
}
# Low-volume, never-queried pointers.
ALLOWED = {
    "market_offers.order_id",  # legacy table
    "recurring_orders.last_order_id",
    "shipments.pickup_proof_file_id",
    "shipments.delivery_proof_file_id",
}


def _leading_columns(table) -> set[str]:
    leading = set()
    for index in table.indexes:
        expressions = list(index.expressions)
        if expressions and hasattr(expressions[0], "name"):
            leading.add(expressions[0].name)
    for constraint in table.constraints:
        if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint)) and constraint.columns:
            leading.add(list(constraint.columns)[0].name)
    leading.update(c.name for c in table.columns if c.index or c.unique)
    return leading


def test_foreign_keys_have_a_covering_index():
    missing = []
    for table in Base.metadata.tables.values():
        leading = _leading_columns(table)
        for fk in table.foreign_keys:
            column = fk.parent.name
            if (column in leading or fk.column.table.name in REFERENCE_TABLES or column in ACTOR_COLUMNS
                    or f"{table.name}.{column}" in ALLOWED):
                continue
            missing.append(f"{table.name}.{column} -> {fk.target_fullname}")
    assert not missing, (
        "Foreign keys without an index (declare one in the model's __table_args__ and add a migration):\n  "
        + "\n  ".join(sorted(missing))
    )


def test_index_names_are_unique_across_tables():
    seen = {}
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            assert index.name not in seen, f"{index.name} declared on {seen[index.name]} and {table.name}"
            seen[index.name] = table.name
