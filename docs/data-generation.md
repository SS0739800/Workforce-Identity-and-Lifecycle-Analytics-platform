# Synthetic data generation

All data in this project is invented. There is no connection to any real directory,
HR system, tenant or company. The organisation is a fictional manufacturer,
**Northstar Manufacturing**, and email addresses use the reserved `.example` domain.

Run it with:

```bash
python scripts/generate_data.py            # seed 42, writes data/raw/*.csv
python scripts/generate_data.py --seed 7   # a different but equally reproducible year
```

The same seed always produces identical output (checked by `tests/test_generation.py`).
Every number below lives in `app/synthetic/assumptions.py` or `app/lifecycle/failures.py`.

## How the year is simulated

Instead of generating each table independently, the generator simulates one year
(1 Oct 2025 – 30 Sep 2026) day by day. Each day runs in a fixed order:

| Time | Step |
|------|------|
| 00:05 | Future-dated terminations take effect (HR status changes to `terminated`) |
| 02:00 | Nightly HR → identity sync, then the lifecycle workflows it detects |
| 07:45 | Manual re-run of the sync, only on days with a directory outage |
| 08:00–17:30 | Weekday HR activity: hires, terminations, leave, transfers, corrections, service-desk re-runs |
| 18:00 | Data-quality scan of every record |

Failures and data-quality issues are not inserted as statistics. They come out of the mechanics:
a bad HR record is detected by the scan, blocks the sync, and stays blocked until HR corrects it;
a failed license removal leaves the license assigned, and the next scan reports it.

### The sync

The sync is modelled on a nightly job that reads a full HR export:

1. **File checks first.** If the export is missing or lacks a required column, the whole run fails
   with an error message and no records are processed (happens on 2 days).
2. **Per record.** Records whose attributes already match the identity account are *skipped*.
   Changed records are validated. A record missing an employee ID, manager or job title, or with an
   invalid email, unknown department or a duplicate, *fails* with an error type instead of being
   silently skipped.
3. **Retry limit.** A failing record is retried on at most 3 runs, then held until its HR data
   changes again. This keeps one bad record from failing every night for months.
4. **Lifecycle hand-off.** New hires go to the onboarding workflow. Terminations, leave and return
   are detected from HR status and run whether or not the record passes attribute validation.

`total_records` on a run is the size of the export. Only records that needed an update get a
`sync_record_results` row.

### Workflows

| Workflow | Actions (in order) |
|----------|--------------------|
| Onboarding | create account → add birthright groups → assign roles → assign licenses |
| Offboarding | disable account → revoke sessions → reset password → remove each group, role and license |
| Leave | disable account → revoke sessions → set leave flag (access is kept for the return) |
| Return from leave | enable account → clear leave flag |

- If `create_account` fails, the rest of onboarding is recorded as `skipped`.
- Offboarding keeps going after a failed step, so one failure does not leave everything behind.
- Disabling an already-disabled account is recorded as `skipped` with `ALREADY_DISABLED`
  (happens after an involuntary termination, when the service desk has already disabled the account).
- A future-dated termination queues an offboarding workflow as `pending` until the date arrives.
- The service desk re-runs the outstanding steps of a failed workflow 1–5 business days later
  (onboarding 80%, offboarding 60%, leave 50%, return 80% of the time). Failures that are never
  re-run are what the data-quality scan reports as stale access.

## Assumptions and the patterns they create

### Workforce
- 875 employees at the start, structured as CEO → department heads → first-line managers
  (about 1 per 12 people) → individual contributors. Production is the largest department.
- With seed 42: 132 hires (114 regular plus 18 summer interns), 8 duplicate HR records,
  113 terminations within the year and 4 offboardings still pending at year end,
  for 1,015 employee records in total.
- Hiring peaks in **January–February** (new budget year) and **June–July** (summer production
  ramp-up; Production hiring is weighted ×1.8). December is quiet.
- Terminations peak in **January** (after year-end bonuses) and **August** (the intern program ends 21 Aug).
- Contractors are twice as likely to leave; managers are less likely to leave.
- 80% of terminations are voluntary with 7–21 days' notice; 20% are involuntary and effective immediately.
- 5 leaves of absence start each month and last 14–120 days; 12% end in termination instead of a return.
- An annual promotion cycle on **2 March 2026**, plus a few off-cycle promotions, transfers,
  location moves, contractor-to-employee conversions and routine plant supervisor reshuffles each month.
- On **1 April 2026** the Logistics department is merged into Supply Chain. The bulk update is
  loaded the evening before and misses about 10% of individual records, which then fail
  department validation.

### Failure rates (per action attempt)

| Action | Base rate | Main error types | Why |
|--------|-----------|------------------|-----|
| create_account | 3% | DEPENDENCY_ERROR, TIMEOUT, PERMISSION_ERROR | |
| assign_license | 3% (35% during shortages) | DEPENDENCY_ERROR | License pool runs short during both hiring peaks (19 Jan–13 Feb, 1–26 Jun) |
| remove_license | 8% | DEPENDENCY_ERROR (throttling), TIMEOUT | Assumed to go through a separate, rate-limited licensing API |
| revoke_session | 5% | TIMEOUT, DEPENDENCY_ERROR | |
| remove_role | 3% (×3 for the privileged directory role) | PERMISSION_ERROR | Automation account often lacks rights over privileged roles |
| remove_group_membership | 2.5% | TIMEOUT, PERMISSION_ERROR, RESOURCE_NOT_FOUND | |
| other actions | 1–2% | various | |

- Sync record updates time out 1% of the time.
- Directory outages on 18 Nov 2025, 10 Feb 2026 and 23 Jun 2026 fail the nightly run; an
  analyst re-runs it at 07:45. Outage failures don't count against a record's retry limit.

These rates mean the data shows license removal failing more often than group removal.
That pattern is **designed in**. Any analysis of it should say the cause is an assumption
of the simulation, not something the data discovered.

### Data-quality defects

| Defect | How it enters the data | Blocks sync? |
|--------|------------------------|--------------|
| Missing manager | 3% of hires; 12% of Production hires during hiring peaks | Yes |
| Missing job title | 1% of hires; 12% of contractors (staffing-agency records) | Yes |
| Invalid email | 2.5% of hires (missing `@`, missing TLD, space) | Yes |
| Missing employee ID | 1.5% of hires | Yes |
| Duplicate employee | 2.5% of hires are entered a second time 1–3 days later | Yes |
| Invalid department | Records missed by the Logistics merge | Yes |
| Invalid location | 2% of hires (misspelled site); 8 legacy records with "Dayton" | No |
| Incorrect employment status | 4% of voluntary terminations: date set, status never changed, so offboarding never starts | No |
| Missing termination date | 15% of involuntary terminations | No |
| Missing identity account | Onboarding blocked by bad data or `create_account` failed without a re-run | — |
| Stale group / role / license, active account after termination | Offboarding step failed and was not re-run | — |

65% of HR-record defects are corrected by HR 2–25 days later (the change is logged with
source `data_correction`). The rest stay open. With seed 42, 95 issues are detected
during the year and 33 employees (3.3%) still have an open issue at year end.

## Known simplifications

- All timestamps are UTC; sites in different time zones are not modelled.
- Employees hired before the simulated year have accounts and access but no workflow history.
- Employment status is `active` from the moment HR creates the record (no separate pre-hire status).
- The year ends at 30 Sep. Anyone terminated on that last day has not been offboarded yet (that
  would happen overnight), so they still hold access but are not flagged as a data-quality issue.
- Access is purely birthright, derived from department, site, title and employment type.
  There are no access requests or approvals.
