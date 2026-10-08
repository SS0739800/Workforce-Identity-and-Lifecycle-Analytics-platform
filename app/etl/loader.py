"""Validate the raw CSV files and load them into PostgreSQL.

The load is a full refresh: generated tables are truncated and reloaded in one
transaction, so a failed load leaves the previous data in place.
"""

import logging
from pathlib import Path

from sqlalchemy import Engine, bindparam, func, select, text, update

from app.etl.csv_files import read_table, table_for
from app.synthetic.simulator import TABLES

logger = logging.getLogger(__name__)

# TABLES is already in dependency order: parents before children.
LOAD_ORDER = TABLES
INSERT_BATCH_SIZE = 5_000


class ValidationError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} validation problem(s): " + "; ".join(problems[:10]))
        self.problems = problems


def read_raw_tables(raw_dir: Path) -> dict[str, list[dict]]:
    """Read every table, failing early if a file is missing or its columns do not match the schema."""
    problems = []
    data = {}
    for name in LOAD_ORDER:
        path = raw_dir / f"{name}.csv"
        if not path.exists():
            problems.append(f"{path.name}: file not found")
            continue
        header, rows = read_table(path, name)
        expected = [column.name for column in table_for(name).columns]
        missing = [c for c in expected if c not in header]
        unexpected = [c for c in header if c not in expected]
        if missing:
            problems.append(f"{path.name}: missing column(s) {', '.join(missing)}")
        if unexpected:
            problems.append(f"{path.name}: unexpected column(s) {', '.join(unexpected)}")
        data[name] = rows
    if problems:
        raise ValidationError(problems)
    return data


def validate(data: dict[str, list[dict]]) -> list[str]:
    """Check primary keys, required columns and foreign keys before touching the database."""
    problems = []
    ids = {}
    for name in LOAD_ORDER:
        table = table_for(name)
        rows = data[name]
        row_ids = [row["id"] for row in rows]
        if len(row_ids) != len(set(row_ids)):
            problems.append(f"{name}: duplicate id values")
        ids[name] = set(row_ids)

        required = [c.name for c in table.columns if not c.nullable]
        for column in required:
            empty = sum(1 for row in rows if row[column] is None)
            if empty:
                problems.append(f"{name}.{column}: {empty} empty value(s) in a required column")

    for name in LOAD_ORDER:
        for fk in table_for(name).foreign_keys:
            column = fk.parent.name
            parent_ids = ids[fk.column.table.name]
            orphans = sum(1 for row in data[name] if row[column] is not None and row[column] not in parent_ids)
            if orphans:
                problems.append(f"{name}.{column}: {orphans} value(s) reference missing {fk.column.table.name} rows")
    return problems


def load(engine: Engine, data: dict[str, list[dict]]) -> dict[str, int]:
    """Replace the generated tables with `data`. Returns row counts read back from the database."""
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(LOAD_ORDER)} RESTART IDENTITY CASCADE"))

        for name in LOAD_ORDER:
            table = table_for(name)
            rows = data[name]
            if name == "employees":
                # manager_id points at other employees, so insert without it and set it afterwards.
                rows = [{**row, "manager_id": None} for row in rows]
            for start in range(0, len(rows), INSERT_BATCH_SIZE):
                conn.execute(table.insert(), rows[start:start + INSERT_BATCH_SIZE])
            if name == "employees":
                employees = table_for("employees")
                manager_updates = [
                    {"row_id": row["id"], "manager": row["manager_id"]}
                    for row in data["employees"] if row["manager_id"] is not None
                ]
                if manager_updates:
                    statement = (
                        update(employees)
                        .where(employees.c.id == bindparam("row_id"))
                        .values(manager_id=bindparam("manager"))
                    )
                    conn.execute(statement, manager_updates)
            logger.info("Loaded %-22s %7d rows", name, len(rows))

        # Rows were inserted with explicit ids, so move each sequence past the highest id.
        for name in LOAD_ORDER:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false)"
            ))

        counts = {}
        for name in LOAD_ORDER:
            counts[name] = conn.execute(select(func.count()).select_from(table_for(name))).scalar_one()
    return counts
