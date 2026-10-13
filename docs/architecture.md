# Architecture

How the parts fit together. Each section links to the document with the detail.

## Components and data flow

```mermaid
flowchart LR
    subgraph rules["Shared rules (app/lifecycle)"]
        R["validation · sync rules<br/>workflow plans · failure model<br/>workflow executor"]
    end

    SIM["Year-long simulation<br/>(app/synthetic)"] -->|CSV files| ETL["Validate and load<br/>(app/etl)"]
    ETL --> DB[("PostgreSQL")]
    OPS["Operations<br/>sync · workflows · DQ scan<br/>(app/services)"] --> DB
    SIM -.uses.-> R
    OPS -.uses.-> R

    DB --> SQL["28 named SQL queries<br/>(app/analytics)"]
    SQL --> API["FastAPI<br/>(app/api)"]
    OPS --> API
    SQL --> AI["AI layer<br/>route · sanitize · ground<br/>(app/ai)"]
    AI -->|computed facts only| LLM["Groq<br/>Gemini fallback"]
    AI --> API
    API -->|HTTP| UI["Streamlit console"]
    DB --> VIEWS["reporting views"] -->|read-only login| PBI["Power BI report"]
```

- **One set of rules.** The simulation that generates the year of data and the operations the API
  runs today call the same code in `app/lifecycle/`. A sync run from the console behaves exactly
  like a nightly sync in the generated history. This was verified when the rules were extracted:
  the generated dataset stayed byte-identical. See [operations.md](operations.md).
- **Numbers come from SQL.** Every metric is a named query in `app/analytics/sql/`. The API, the AI
  layer and the tests use the same list, and each query is checked against an independent Python
  calculation. See [analytics.md](analytics.md).
- **The console has no database access.** It only calls the API, so the API is the single place
  where data is read and changed.
- **Power BI reads views, not tables.** A `reporting` schema of views (dimensions and facts) is the
  contract with the report, behind a read-only login. See [../powerbi/README.md](../powerbi/README.md).

## A sync run

What happens when the nightly sync runs, or someone presses **Run sync** in the console:

```mermaid
sequenceDiagram
    participant C as Console / scheduler
    participant S as Sync service
    participant DB as PostgreSQL
    participant R as Rules (app/lifecycle)
    participant W as Workflow executor

    C->>S: POST /api/sync/runs
    S->>DB: take advisory lock (one sync at a time)
    S->>DB: records changed since their last sync
    loop each changed record
        S->>R: validate the HR record
        alt blocking problem (missing or invalid attribute)
            S->>DB: record a failed attempt (up to 3 per change)
        else valid
            S->>DB: update the identity account, log attribute changes
        end
    end
    S->>R: which lifecycle work is due (hire, termination, leave, return)
    loop each workflow
        S->>W: run the planned actions
        W->>DB: one row per action: success, failed (with error type) or skipped
    end
    S-->>C: run summary and the workflows it started
```

A failed workflow can be re-run from the console. The failed steps are re-planned against the
account's current state, so only work that is still outstanding runs, and the run is recorded as a
service-desk re-run. A re-run is refused if it no longer applies, for example an offboarding re-run
for someone who has been rehired.

## An AI request

```mermaid
sequenceDiagram
    participant U as Console
    participant A as AI service
    participant Q as Approved SQL queries
    participant M as Groq (Gemini fallback)
    participant L as ai_insight_runs

    U->>A: question
    A->>A: route to an approved query (keywords first, then the model chooses from the list)
    A->>Q: run it for the requested period
    A->>A: remove names and emails from the rows
    A->>M: facts + instructions (explain, don't calculate)
    M-->>A: explanation
    A->>A: check every number in the answer against the facts
    A->>L: log the request (summary, model, status)
    A-->>U: explanation, facts, status (ok / needs_review / unavailable ...)
```

Without an AI key, or when both models fail, the same request returns the computed facts and a
plain template, so nothing depends on a model being available. See [ai.md](ai.md), and
[ai-examples.md](ai-examples.md) for real outputs.

## Deployment

```mermaid
flowchart LR
    DEV["git push"] --> GHA["GitHub Actions<br/>tests · image build"]
    GHA --> GHCR["GitHub Container Registry<br/>(private image)"]
    subgraph azure["Azure resource group"]
        CON["workforce-console<br/>public HTTPS, one IP allowed"]
        APIC["workforce-api<br/>internal ingress only"]
        LOG["Log Analytics"]
        CON --> APIC
        CON -.logs.-> LOG
        APIC -.logs.-> LOG
    end
    GHCR -->|pull| CON
    GHCR -->|pull| APIC
    APIC -->|TLS| NEON[("Neon PostgreSQL")]
    BROWSER["Browser"] --> CON
```

Both apps scale to zero, run at the smallest size, and fit Azure Container Apps' free monthly grant.
An AWS version (EC2 + RDS through CloudFormation) is kept as an alternative. See [azure.md](azure.md)
and [aws.md](aws.md).

## Tests

| Area | How it's tested |
|---|---|
| Rules and simulation | Unit tests of each rule; properties of the generated year (counts, ordering, no orphans) |
| Loading | CSV round trip, validation failures, reload replaces instead of appending |
| Analytics | Every query compared with an independent Python calculation over the same data |
| Operations | Sync, workflows, re-runs and the scan against PostgreSQL, each test in a rolled-back transaction |
| API | Endpoints over the test database, including errors and validation |
| AI | Routing, sanitizing, grounding, every degraded status and the fallback, with the models replaced by a fake |
| Console | Every page rendered with Streamlit's test runner against the API |
| Deployment | Templates linted and compiled; database privacy, network exposure, IAM scope and free-tier limits asserted |

CI runs all of it against a PostgreSQL service container on every push, and fails, rather than
skipping, if the database or the Bicep compiler is missing.
