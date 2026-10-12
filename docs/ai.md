# AI layer

AI is an explanation layer on top of the analytics. It never produces the numbers: every
figure comes from an approved SQL query, and the model is asked to explain those figures,
and nothing else.

```
question / request
      │
      ▼
approved SQL query (app/analytics/sql/)  ──►  facts (JSON)
      │                                         │
      │                                  remove personal fields
      │                                         │
      │                                  Groq  (Gemini if Groq can't answer)
      │                                         │
      │                                  check every number against the facts
      ▼                                         ▼
response: facts + explanation + ai_status ──► logged in ai_insight_runs
```

## Models

| Provider | Role | Default model | Setting |
|----------|------|---------------|---------|
| Groq | primary | `openai/gpt-oss-120b` | `GROQ_API_KEY`, `GROQ_MODEL` |
| Gemini | fallback | `gemini-3.5-flash-lite` | `GEMINI_API_KEY`, `GEMINI_MODEL` |

Both are optional and configured in `.env`. Defaults were chosen from the providers' model
pages in October 2026. Groq's Llama models were deprecated for free and developer tiers in
2026, so the default is one of the recommended replacements. Model lists change, so check
[Groq models](https://console.groq.com/docs/models) and
[Gemini models](https://ai.google.dev/gemini-api/docs/models) before relying on a default.

When both keys are set, a request goes to Groq first. If Groq can't answer (rate limit or
token quota used up, timeout, outage or error), the same request goes to Gemini. The model that
answered is recorded in `ai_insight_runs.model`, so fallbacks are visible.

## Endpoints

| Endpoint | What it does | Facts come from |
|----------|--------------|-----------------|
| `POST /api/ai/ask` `{"question": "..."}` | Answers an analytics question | One approved query, chosen as described below |
| `POST /api/ai/failure-explanation` `{"question": "..."}` | Explains a failure pattern ("Why are license removal failures higher than group removal failures?") | `action_failure_rates`, `action_failures_by_error_type` |
| `POST /api/ai/executive-summary?month=YYYY-MM` | Monthly operations summary | Sync, workflow, failure, data-quality and department queries for that month |
| `POST /api/ai/data-quality-explanation` | The most significant data-quality problems | `dq_summary`, `dq_by_type`, `dq_by_department`, `sync_failures_with_open_dq_issue` |
| `POST /api/ai/incident-report/{workflow_run_id}` | Incident write-up for a failed workflow | The workflow, its actions, current access, and history |
| `GET /api/ai/runs` | Recent AI requests, for monitoring | `ai_insight_runs` |

They are `POST` because each one writes a log row.

### Answering a question

1. **Map it to an approved query.** Keyword rules in `app/ai/router.py` match the question to
   one query in the registry. Only if no rule matches is the model asked to pick a query
   *name* from the registry. A name that isn't on the list is rejected. The model never writes SQL.
2. **Work out the period in code.** "This quarter", "last month", "in March" and "last 30 days"
   are converted to dates by `parse_period`, relative to the most recent sync run (the data is
   a simulated year, so "last month" means the last month of data, not of the calendar).
3. **Run the query.** No rows means no AI call: the response says the query found nothing.
4. **Explain.** The rows (at most 25) go to the model with the system prompt below.

Questions that match nothing return `ai_status: "unmatched"` with example questions.

## Guardrails

**System prompt** (`app/ai/prompts.py`): use only the facts provided, copy numbers exactly,
don't invent causes, don't claim causation unless the facts support it, say when the data isn't
enough, and keep observed facts separate from possible explanations.

**Grounding check** (`app/ai/grounding.py`): every number in the answer is compared with the
numbers in the facts (allowing for rounding and percentage/fraction formats). Any that aren't
found are listed in `ungrounded_numbers` and the status becomes `needs_review`. This catches
invented or recalculated metrics. It doesn't prove the wording is right.

**Causes are kept separate.** Failure explanations and incident reports must have an "Observed"
part and a separately labelled "possible areas to investigate" part. The simulated failure
rates are assumptions of this project, and the model is told the records can't show *why* one
action fails more than another.

## Privacy

- Before anything is sent, `app/ai/sanitize.py` drops personal fields (names, emails,
  usernames) and redacts anything that looks like an email address. A final check refuses to
  send if personal data is still present.
- Employees appear only by their synthetic HR employee ID, department, title and location.
- Most requests send aggregated metrics only.
- `ai_insight_runs` stores a short input summary (which query, which period, how many rows)
  and the first 500 characters of the answer, never the full prompt.
- API keys come from `.env` (or AWS Secrets Manager later) and are never logged.

## Without AI

The application works with no AI keys at all:

| Situation | `ai_status` | What the caller gets |
|-----------|-------------|----------------------|
| No keys configured | `unavailable` | The facts; the executive summary and incident report use a plain template |
| Rate limit / quota (both providers) | `rate_limited` | Same as above |
| Timeout | `timeout` | Same as above |
| Empty or unusable answer | `invalid_response` | Same as above |
| Other provider error (e.g. retired model) | `error` | Same as above |
| Answer contains numbers not in the facts | `needs_review` | The explanation, plus the list of unmatched numbers |

Groq's SDK retries rate limits and connection errors itself (`GROQ_MAX_RETRIES`, default 2)
before the fallback is tried.

## Testing

`tests/test_ai.py` never calls a real model. A fake client returns canned answers or raises
each error type. The tests cover: routing and time phrases, rejection of invented query names,
sanitizing (including that an incident prompt contains no name or email), the grounding check,
every degraded status, the Gemini fallback, the mapping of real Groq and Gemini SDK errors, the
template fallbacks, logging, and the API endpoints.

## Limitations

- Keyword routing covers the questions in the examples and close variations. Unusual phrasing
  falls back to model-based routing, which needs an AI key.
- The grounding check compares numbers, not meaning: an answer can use correct numbers and
  still describe them badly. Treat explanations as drafts for a person to read.
- Explanations are only as complete as the facts sent: at most 25 rows per question.
