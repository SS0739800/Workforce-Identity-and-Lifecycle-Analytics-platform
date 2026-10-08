# Lifecycle operations

The generated dataset covers one simulated year. The operations API keeps the platform
running after that year: HR changes go in, a sync run processes them, lifecycle workflows
change the (simulated) identity data, and a data-quality scan checks the result.

There is no real directory behind any of this. Accounts, groups, roles and licenses are rows
in PostgreSQL, and action failures are simulated at the rates documented in
[data-generation.md](data-generation.md).

## One set of rules, two callers

```
                       app/lifecycle/
         ┌───────────────────────────────────────────┐
         │ reference.py   birthright access           │
         │ validation.py  data-quality rules, scan    │
         │ sync.py        which records sync, errors, │
         │                which workflows are due     │
         │ workflows.py   action plans, re-run rules  │
         │ executor.py    run a plan, record outcomes │
         │ failures.py    failure rates, durations    │
         └─────────────┬───────────────┬─────────────┘
                       │               │
         app/synthetic/simulator.py   app/services/  (sync, workflow, data-quality, HR)
         in-memory store              PostgreSQL store (identity_store.py)
         generates the year           used by the API
```

The executor talks to an `IdentityStore` with two methods: the current account status, and
"apply this successful action". The simulator implements it over dictionaries and the API
over SQLAlchemy. Moving the rules into `app/lifecycle/` was checked by generating the dataset
before and after: the output was byte-identical.

## A typical sequence

```bash
# 1. HR enters a new hire (department, title etc. are not checked here on purpose)
curl -X POST localhost:8000/api/employees -H "Content-Type: application/json" \
     -d '{"first_name":"Dana","last_name":"Lee","hire_date":"2026-10-20",
          "department":"Quality Assurance","job_title":"Quality Engineer",
          "location":"Greenville Plant","manager_id":2}'

# 2. Run the sync: validates the record, then onboarding creates the account and access
curl -X POST localhost:8000/api/sync/runs

# 3. HR records a termination; the next sync runs offboarding
curl -X PATCH localhost:8000/api/employees/1011 -H "Content-Type: application/json" \
     -d '{"employment_status":"terminated","termination_date":"2026-10-07"}'
curl -X POST localhost:8000/api/sync/runs

# 4. Check what was left behind
curl -X POST localhost:8000/api/data-quality/scans
curl localhost:8000/api/employees/1011

# 5. If offboarding failed, the service desk re-runs the outstanding steps
curl -X POST localhost:8000/api/workflows/391/rerun
```

## Endpoints

| Endpoint | What it does |
|----------|--------------|
| `POST /api/employees` | Create an HR record for a new hire. Employee ID and email are generated if not given. |
| `PATCH /api/employees/{id}` | Change HR attributes. Each change is logged in `attribute_change_logs`. Unknown fields, invalid statuses and non-existent managers return 422. |
| `POST /api/sync/runs` | Run the sync now. Returns the run and the workflows it started. |
| `GET /api/sync/runs`, `GET /api/sync/runs/{id}` | Recent runs; one run with its record results. |
| `GET /api/workflows/{id}` | A workflow run with its actions. |
| `POST /api/workflows/{id}/rerun` | Service-desk re-run of a failed workflow. 409 if it isn't failed, if the situation changed (e.g. the employee returned from leave), or if nothing is left to do. |
| `POST /api/data-quality/scans` | Re-check every record; open new issues and resolve fixed ones. |

## Behaviour worth knowing

- **HR changes don't act immediately.** As in the original automation, nothing happens to the
  identity account until the next sync run sees the change.
- **What the sync processes.** A record is processed when `employees.updated_at` is later than
  `identity_accounts.last_sync_at`. A new hire is processed once, to hand it to onboarding.
  A record that fails on 3 runs is held until HR changes it again.
- **Bad HR data is accepted.** An unknown department or a missing manager is stored, then the
  sync refuses the record and the scan reports it. Only the fixed vocabularies (statuses,
  employment type) are validated at the API.
- **Lifecycle workflows are state-driven.** A terminated employee who hasn't been offboarded is
  offboarded, whenever the sync next runs. There is no lookback window to miss.
- **Future-dated terminations** queue a `pending` offboarding. It runs when HR changes the status
  to `terminated`.
- **Labels.** Workflows started by a sync are `initiated_by = nightly_sync` (scheduled) or
  `manual_sync` (API or after an outage); re-runs are `service_desk`.
- **One sync at a time.** The sync takes a PostgreSQL advisory lock; a second concurrent request
  gets 409.
- **Transactions.** Each request runs in one transaction. If anything fails, nothing is saved.

## Limitations

- Action durations are simulated, so `completed_at` is the start time plus a simulated duration,
  not real elapsed time.
- In live mode, failures are random at the documented rates. The tests replace the random
  generator to force success or failure.
- The sync is triggered by API call. A schedule (e.g. a nightly container task) is not set up yet.
- There is no authentication on the API yet. It is meant for local use until the AWS phase.
