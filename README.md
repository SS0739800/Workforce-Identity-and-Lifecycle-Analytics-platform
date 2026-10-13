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
> against the database, and a four-page Power BI report (Phase 4) saved as a Power BI Project
> in `powerbi/`, and an AI explanation layer (Groq, with Gemini as a fallback) over the analytics
> (Phase 5), a Streamlit operations console on top of the API (Phase 6), and a cloud deployment
> that costs nothing to run: Azure Container Apps with a Neon database (Phase 7). An AWS version
> is included as an alternative.

## What exists so far

- PostgreSQL schema (SQLAlchemy models + Alembic migration). See [docs/data-model.md](docs/data-model.md).
- A deterministic, day-by-day simulation of one year of identity operations for ~1,000
  fictional employees. See [docs/data-generation.md](docs/data-generation.md).
- Validation and loading of the generated CSV files into PostgreSQL.
- 28 analytical SQL queries covering sync reliability, attribute changes, workflow failures,
  offboarding and access cleanup, and data quality. See [docs/analytics.md](docs/analytics.md).
- A FastAPI service for employee investigation and analytics.
- A Power BI report with four pages (Overview, Synchronization, Lifecycle, Data Quality), built on a
  `reporting` schema of views (date, employee and workflow-type dimensions and six fact views) read
  through a read-only database login. The model, Power Query and 36 DAX measures are stored as text
  in the repository. See [powerbi/README.md](powerbi/README.md).
- Lifecycle operations through the API: enter HR changes, run the sync, onboard, offboard,
  handle leave and return, re-run failed workflows, and run the data-quality scan. The simulator
  and the API share the same rules in `app/lifecycle/`. See [docs/operations.md](docs/operations.md).
- AI explanations on top of the analytics: natural-language questions mapped to approved queries,
  failure explanations, monthly summaries, data-quality explanations and incident reports. Groq is
  the primary model and Gemini the fallback; the model only explains numbers computed in SQL, personal
  fields are removed before anything is sent, every number in an answer is checked against the data,
  and everything still works without an API key. See [docs/ai.md](docs/ai.md).
- A Streamlit console for day-to-day investigation, with six pages: Overview, Employee Investigation,
  Synchronization, Lifecycle, Data Quality and AI Insights. It reads everything through the API
  (it has no database access of its own). From it you can look up one employee's access, workflows,
  changes and audit trail, re-run failed workflows, run a sync or a data-quality scan (each needs
  a confirmation tick first), and ask the AI layer questions.
- A deployment to **Azure Container Apps**, which is the one in use. GitHub Actions builds the image
  on every push. Bicep defines the infrastructure, and one script (`scripts/azure_deploy.py`)
  migrates the database and deploys the image for the current commit. The console is the only
  public endpoint, over HTTPS and open to one IP address; the API is internal. Both apps scale to
  zero, and PostgreSQL runs on Neon's free plan. See [docs/azure.md](docs/azure.md).
- **Why Azure and not AWS:** the goal was a deployment that is actually free. On AWS the database
  and server are free only for the first 6–12 months, through the free tier or credits. On Azure,
  Container Apps' monthly free grant and Neon's free plan have no end date.
- **AWS as an alternative:** an AWS version is kept in `deploy/aws` for anyone who prefers it. It
  runs EC2 and RDS through CloudFormation, with SSM Parameter Store, S3 and CloudWatch, and is
  created and deleted with `scripts/aws_deploy.py`. See [docs/aws.md](docs/aws.md).
- Tests for the validation rules, the shared lifecycle engine, generated data, the load step,
  every query (checked against an independent Python calculation), the lifecycle operations
  against PostgreSQL, the API, the AI layer (with the models mocked), the Streamlit pages
  (rendered with Streamlit's test runner against the API), and the deployment templates (linted,
  with the database privacy, network and IAM rules asserted).

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

Then, in a second terminal (with the API still running):

```bash
streamlit run streamlit_app/app.py # console at http://localhost:8501
```

The console calls the API at `API_BASE_URL` (default `http://127.0.0.1:8000`).

To run the API and console in containers instead (the same image the cloud deployments use):

```bash
docker compose --profile app up -d --build   # console at http://localhost:8501
```

To deploy, see [docs/azure.md](docs/azure.md) (free), or [docs/aws.md](docs/aws.md) for AWS.

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
  ai/          model clients (Groq, Gemini fallback), prompts, question routing,
               sanitizing and the grounding check
  services/    analytics, employee lookups, database-backed sync, workflow,
               data-quality and HR operations, and AI insights
  schemas/     Pydantic response models
  api/         FastAPI routers
  main.py      FastAPI application
streamlit_app/ Streamlit console: app.py (navigation), api.py (HTTP client),
               ui.py (shared tables, charts, filters), pages/
.streamlit/    Streamlit theme and server settings
deploy/azure/  Bicep templates (Container Apps, Log Analytics, budget alert)
deploy/aws/    CloudFormation templates and the instance start script (alternative)
.github/       workflow that builds and publishes the image
Dockerfile     one image for the API, the console and the jobs
alembic/       migrations
powerbi/       Power Query scripts, DAX measures, report design, validation query
scripts/       generate_data.py, load_data.py, create_reporting_user.py,
               azure_deploy.py, aws_deploy.py, deploy_helpers.py
tests/
docs/
```
