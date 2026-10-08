# Workforce Identity & Lifecycle Analytics Platform

A synthetic identity operations platform. It simulates a year of employee lifecycle
workflows at a fictional manufacturer and stores the results for analysis: HR → identity
sync runs, onboarding, offboarding, leave and return, access cleanup, workflow failures
and data-quality issues.

In a previous IAM role I automated employee lifecycle operations with PowerShell:
attribute sync from an HR export, offboarding cleanup, and leave/return handling.
This project rebuilds those concepts in Python on fully synthetic data. No employer code,
infrastructure or data is used.

> **Status: work in progress.** Phases 1–3 are in place: database, synthetic data, loading,
> SQL analytics, a REST API, and lifecycle operations (sync, workflows, data-quality scan) that run
> against the database. Power BI, Streamlit, AI and AWS deployment come in later phases and are
> not implemented yet.

## What exists so far

- PostgreSQL schema (SQLAlchemy models + Alembic migration). See [docs/data-model.md](docs/data-model.md).
- A deterministic, day-by-day simulation of one year of identity operations for ~1,000
  fictional employees. See [docs/data-generation.md](docs/data-generation.md).
- Validation and loading of the generated CSV files into PostgreSQL.
- 27 analytical SQL queries covering sync reliability, attribute changes, workflow failures,
  offboarding and access cleanup, and data quality. See [docs/analytics.md](docs/analytics.md).
- A FastAPI service for employee investigation and analytics.
- Lifecycle operations through the API: enter HR changes, run the sync, onboard, offboard,
  handle leave and return, re-run failed workflows, and run the data-quality scan. The simulator
  and the API share the same rules in `app/lifecycle/`. See [docs/operations.md](docs/operations.md).
- Tests for the validation rules, the shared lifecycle engine, generated data, the load step,
  every query (checked against an independent Python calculation), the lifecycle operations
  against PostgreSQL, and the API.

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

uvicorn app.main:app --reload      # API docs at http://127.0.0.1:8000/docs
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
  lifecycle/   shared rules: reference data, validation, sync rules, workflow plans,
               failure model and the workflow executor
  synthetic/   the year-long simulation and its assumptions
  etl/         CSV read/write, validation and loading
  analytics/   named SQL queries (sql/*.sql) and the query registry
  services/    analytics, employee lookups, and database-backed sync, workflow,
               data-quality and HR operations
  schemas/     Pydantic response models
  api/         FastAPI routers
  main.py      FastAPI application
alembic/       migrations
scripts/       generate_data.py, load_data.py
tests/
docs/
```
