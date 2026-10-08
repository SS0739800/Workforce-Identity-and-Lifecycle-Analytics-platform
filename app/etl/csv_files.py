"""Read and write the raw CSV layer.

Column order and types come from the SQLAlchemy models, so the CSV files always match
the database schema. Empty cells mean NULL; the generator never produces empty strings.
"""

import csv
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Integer, Table

from app.db.database import Base
import app.models  # noqa: F401  (registers every table on Base.metadata)


def table_for(name: str) -> Table:
    return Base.metadata.tables[name]


def _to_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def write_tables(tables: dict[str, list[dict]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        columns = [column.name for column in table_for(name).columns]
        with (output_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([_to_cell(row[column]) for column in columns])


def _parse(cell: str, column_type):
    if cell == "":
        return None
    if isinstance(column_type, Integer):
        return int(cell)
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(cell)
    if isinstance(column_type, Date):
        return date.fromisoformat(cell)
    return cell


def read_table(path: Path, name: str) -> tuple[list[str], list[dict]]:
    """Return the CSV header and its rows converted to Python types."""
    table = table_for(name)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        types = {column.name: column.type for column in table.columns if column.name in header}
        rows = [{key: _parse(value, types[key]) for key, value in raw.items() if key in types} for raw in reader]
    return header, rows
