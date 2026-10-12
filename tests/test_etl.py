import csv

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.etl.csv_files import read_table, write_tables
from app.etl.loader import ValidationError, has_employees, load, read_raw_tables, validate


@pytest.fixture(scope="module")
def raw_dir(dataset, tmp_path_factory):
    path = tmp_path_factory.mktemp("raw")
    write_tables(dataset, path)
    return path


def test_csv_round_trip_preserves_types(dataset, raw_dir):
    _, employees = read_table(raw_dir / "employees.csv", "employees")
    assert employees == dataset["employees"]
    _, actions = read_table(raw_dir / "workflow_actions.csv", "workflow_actions")
    assert actions == dataset["workflow_actions"]


def test_missing_column_stops_the_load(raw_dir, tmp_path):
    for source in raw_dir.iterdir():
        (tmp_path / source.name).write_bytes(source.read_bytes())
    path = tmp_path / "employees.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    manager_column = rows[0].index("manager_id")
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([row[:manager_column] + row[manager_column + 1:] for row in rows])

    with pytest.raises(ValidationError) as error:
        read_raw_tables(tmp_path)
    assert "missing column(s) manager_id" in error.value.problems[0]


def test_validation_catches_orphaned_rows(dataset):
    broken = {name: list(rows) for name, rows in dataset.items()}
    broken["workflow_actions"] = broken["workflow_actions"] + [{**broken["workflow_actions"][0], "id": 999_999, "workflow_run_id": 999_999}]
    problems = validate(broken)
    assert any("workflow_actions.workflow_run_id" in p for p in problems)


# --- database (skipped when PostgreSQL is not running) ---------------------------------------

def test_load_into_postgres(db_engine, raw_dir):
    data = read_raw_tables(raw_dir)
    counts = load(db_engine, data)
    assert counts == {name: len(rows) for name, rows in data.items()}


def test_has_employees_after_a_load(db_engine, raw_dir):
    load(db_engine, read_raw_tables(raw_dir))
    assert has_employees(db_engine)


def test_reload_replaces_data_instead_of_appending(db_engine, raw_dir):
    data = read_raw_tables(raw_dir)
    load(db_engine, data)
    counts = load(db_engine, data)
    assert counts["employees"] == len(data["employees"])


def test_sequences_continue_after_loaded_ids(db_engine, raw_dir):
    data = read_raw_tables(raw_dir)
    load(db_engine, data)
    with db_engine.begin() as conn:
        new_id = conn.execute(text(
            "INSERT INTO audit_events (event_type, description, event_timestamp, source) "
            "VALUES ('test', 'sequence check', now(), 'test') RETURNING id"
        )).scalar_one()
        conn.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": new_id})
    assert new_id == len(data["audit_events"]) + 1


def test_database_enforces_foreign_keys(db_engine, raw_dir):
    load(db_engine, read_raw_tables(raw_dir))
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO workflow_runs (employee_id, workflow_type, requested_at, status, initiated_by) "
                "VALUES (999999, 'onboarding', now(), 'pending', 'test')"
            ))


def test_database_rejects_unknown_status(db_engine, raw_dir):
    load(db_engine, read_raw_tables(raw_dir))
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE identity_accounts SET account_status = 'deleted' WHERE id = 1"))
