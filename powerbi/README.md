# Power BI report

The report reads the `reporting` schema in PostgreSQL through a read-only login.
This folder holds everything needed to build it, as text that can be reviewed in git:

| File | Contents |
|------|----------|
| [power-query/](power-query/) | One Power Query (M) script per table |
| [measures.dax](measures.dax) | All DAX measures, with comments |
| [report-pages.md](report-pages.md) | The four report pages: question, visuals, fields |
| [validation.sql](validation.sql) | The totals the finished report should show |

The views themselves are defined in the Alembic migration
`alembic/versions/*_add_reporting_views.py`. `tests/test_reporting.py` checks that the
measures' formulas, computed over the views, match the API's analytics queries exactly.

## Data model

```
                         dim_date ─────────────┬──────────────┬───────────────┬────────────────┐
                            │ (date)           │              │               │                │
                            │                  │              │               │   detected_date (active)
                            │                  │              │               │   resolved_date (inactive)
 fact_sync_runs      fact_sync_records  fact_workflow_runs  fact_workflow_actions  fact_attribute_changes  fact_dq_issues
                            │                  │              │               │                │
                            └──────────────────┴──────┬───────┴───────────────┴────────────────┘
                                                      │ (employee_key)
                                                dim_employee

 dim_workflow_type ──(workflow_type)──> fact_workflow_runs, fact_workflow_actions
```

All relationships are many-to-one, single direction (dimension filters fact).

| From (many) | To (one) | Active |
|-------------|----------|--------|
| `fact_sync_runs[date]` | `dim_date[date]` | yes |
| `fact_sync_records[date]` | `dim_date[date]` | yes |
| `fact_sync_records[employee_key]` | `dim_employee[employee_key]` | yes |
| `fact_workflow_runs[date]` | `dim_date[date]` | yes |
| `fact_workflow_runs[employee_key]` | `dim_employee[employee_key]` | yes |
| `fact_workflow_runs[workflow_type]` | `dim_workflow_type[workflow_type]` | yes |
| `fact_workflow_actions[date]` | `dim_date[date]` | yes |
| `fact_workflow_actions[employee_key]` | `dim_employee[employee_key]` | yes |
| `fact_workflow_actions[workflow_type]` | `dim_workflow_type[workflow_type]` | yes |
| `fact_attribute_changes[date]` | `dim_date[date]` | yes |
| `fact_attribute_changes[employee_key]` | `dim_employee[employee_key]` | yes |
| `fact_dq_issues[detected_date]` | `dim_date[date]` | yes |
| `fact_dq_issues[resolved_date]` | `dim_date[date]` | **no**, used by `Issues Resolved (by resolved date)` |
| `fact_dq_issues[employee_key]` | `dim_employee[employee_key]` | yes |

Design choices:

- **Star schema where it helps, not everywhere.** Each fact has its own grain: run, record,
  workflow, action, change, issue. There are no fact-to-fact relationships. Workflow type and
  employee are copied onto each action so action visuals don't depend on the workflow table.
- **Department and location live on `dim_employee`.** They are the employee's *current* values,
  matching the API. A separate department dimension would add a table without adding anything.
- **`fact_sync_runs` has no employee.** A run covers everyone, so run-level measures don't
  respond to the department slicer. The report says so on the page.
- **Shaping happens in SQL, not Power Query.** Joins, flags (`is_attempt`, `is_rerun`,
  `had_open_dq_issue`), durations and UTC timestamps are in the views, where they are tested and
  fold back to PostgreSQL. Power Query only connects, drops the time-zone-aware timestamp
  columns, sets types and labels missing HR IDs.
- **No email in the model.** The reports don't need it.

## Building the report

### 1. Prepare the database

```bash
docker compose up -d
alembic upgrade head                     # includes the reporting views
python scripts/generate_data.py
python scripts/load_data.py
python scripts/create_reporting_user.py  # read-only login from REPORTING_DB_USER / REPORTING_DB_PASSWORD in .env
```

Re-run `create_reporting_user.py` after any migration that re-creates the reporting views.

### 2. Set up Power BI Desktop

1. Install Power BI Desktop (Windows; free from the Microsoft Store).
2. File > Options > Current file > Data load: turn off **Auto date/time** (the model has its own date table).
3. Optional, recommended: File > Options > Preview features: enable **Power BI Project (.pbip) save option**
   if it is listed, so the finished report is saved as text files that can be committed.

### 3. Connect

1. Home > Transform data > **Manage Parameters** > New:
   - `DatabaseServer`, type Text, current value `localhost:5432`
   - `DatabaseName`, type Text, current value `workforce`
2. For each file in `power-query/`: Home > New Source > **Blank Query** > Advanced Editor,
   paste the file's contents, and name the query exactly as the file (e.g. `fact_sync_runs`).
3. When asked for credentials choose **Database** and use `powerbi_reader` with the password
   from `.env`.
4. The local Docker database has no TLS certificate. Power BI will say it can't connect with an
   encrypted connection. For `localhost` only, accept the unencrypted connection. For a cloud
   database (Phase 7), keep encryption on.
5. Close & Apply. Row counts should match `validation.sql`.

Timestamps come from the views' `*_utc` columns (plain UTC date-times). The time-zone-aware
originals are dropped in Power Query because the connector returned them as nulls.

### 4. Model

1. Model view: create the relationships in the table above (Power BI may detect some; check the
   direction and set `fact_dq_issues[resolved_date]` to inactive).
2. Select `dim_date` > Table tools > **Mark as date table** > `date`.
3. Sort by column: `dim_date[month_label]` by `month_start`, `dim_date[quarter_label]` by
   `quarter_start`, `dim_workflow_type[workflow_label]` by `sort_order`.
4. Hide the key columns in the report view (`*_key`, `fact_*[date]` columns, `sort_order`) so
   the field list shows what report builders should use.

### 5. Measures

1. Home > Enter data > create an empty table named `_Measures` ("Measures" is reserved in Power BI),
   then hide its placeholder column.
2. Add each measure from `measures.dax` (New measure, paste one block at a time) and put it in a
   display folder matching its section heading.
3. Format every measure ending in `Rate` as a percentage with one decimal place, and counts as
   whole numbers.

### 6. Pages

Build the four pages in [report-pages.md](report-pages.md).

### 7. Check the numbers

Run `validation.sql` and compare it with the cards on each page with **no slicers selected**:

```bash
docker compose exec -T postgres psql -U workforce -d workforce < powerbi/validation.sql
```

Every card must match. If one doesn't, the cause is usually a missing or reversed relationship,
or a filter left on a visual.

### 8. Save

Save into this folder as `WorkforceIdentity.pbip` (or `.pbix` if the project format isn't
available). `.gitignore` already excludes Power BI's local cache and settings files.
Export page screenshots to `docs/images/` for the main README.

## Opening the saved report

The report is saved as a Power BI Project: open `WorkforceIdentity.pbip` in Power BI Desktop.
Pages and visuals are stored as JSON under `WorkforceIdentity.Report/definition/`, and the model
(tables, relationships, measures) as TMDL under `WorkforceIdentity.SemanticModel/definition/`, so
changes show up as readable diffs. No credentials are stored in these files; Power BI asks for the
`powerbi_reader` password on the first refresh.

On Windows, the visual files have long paths. If git reports "Filename too long", run
`git config core.longpaths true` in the repository. Power BI Desktop itself can't open files
whose full path is over 260 characters; if the repository is in a deeply nested folder, open the
report through a short folder link instead, for example:

```powershell
New-Item -ItemType Junction -Path C:\Users\<you>\wi-powerbi -Target <repository>\powerbi
# then open C:\Users\<you>\wi-powerbi\WorkforceIdentity.pbip
```

## Switching to the cloud database later

Change the `DatabaseServer` and `DatabaseName` parameters to the RDS endpoint and refresh.
Nothing else in the model changes.
