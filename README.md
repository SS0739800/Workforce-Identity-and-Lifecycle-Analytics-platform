# Workforce Identity & Lifecycle Analytics Platform

A synthetic identity operations platform. It simulates a year of employee lifecycle
workflows at a fictional manufacturer and stores the results for analysis: HR → identity
sync runs, onboarding, offboarding, leave and return, access cleanup, workflow failures
and data-quality issues.

In a previous IAM role I automated employee lifecycle operations with PowerShell:
attribute sync from an HR export, offboarding cleanup, and leave/return handling.
This project rebuilds those concepts in Python on fully synthetic data. No employer code,
infrastructure or data is used.

> **Status: work in progress.** Phase 1 (database, synthetic data, loading) is in place.
> Analytics, API, Power BI, Streamlit, AI and AWS deployment come in later phases and are
> not implemented yet.

## What exists so far

- PostgreSQL schema (SQLAlchemy models + Alembic migration). See [docs/data-model.md](docs/data-model.md).
- A deterministic, day-by-day simulation of one year of identity operations for ~1,000
  fictional employees. See [docs/data-generation.md](docs/data-generation.md).
- Validation and loading of the generated CSV files into PostgreSQL.
- Tests for the validation rules, workflow plans, generated data and the load step.

## Setup

Requirements: Python 3.12+, Docker.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt

cp .env.example .env               # then set a password in .env
docker compose up -d               # PostgreSQL 16 on localhost:5432

alembic upgrade head               # create the schema
python scripts/generate_data.py    # write data/raw/*.csv
python scripts/load_data.py        # validate and load into PostgreSQL
```

## Tests

```bash
pytest
```

Database tests use a separate `workforce_test` database (created by the Docker init script)
and are skipped if PostgreSQL is not running.

## Project layout

```
app/
  core/        configuration and logging
  db/          SQLAlchemy base and engine
  models/      database tables
  lifecycle/   domain rules: reference data, validation, workflow plans, failure model
  synthetic/   the year-long simulation and its assumptions
  etl/         CSV read/write, validation and loading
alembic/       migrations
scripts/       generate_data.py, load_data.py
tests/
docs/
```
