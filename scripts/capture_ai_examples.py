"""Call each AI endpoint of a running API and write the unedited results to docs/ai-examples.md.

    python scripts/capture_ai_examples.py [--api http://127.0.0.1:8000]

The examples in the docs come from this script, not from hand-written text: what the model returned
is copied as-is, next to the facts it was given and the grounding check. Model output varies between
runs, so re-running it produces different wording over the same numbers.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT  # noqa: E402

OUTPUT = PROJECT_ROOT / "docs" / "ai-examples.md"
MAX_ROWS = 8


def find_failed_offboarding(client: httpx.Client) -> int:
    """A failed workflow run belonging to a leaver who still has access: the case an incident report is for."""
    leavers = client.get("/api/analytics/offboarding").raise_for_status().json()["access_remaining"]
    for leaver in leavers:
        runs = client.get(f"/api/employees/{leaver['employee_db_id']}/workflows").raise_for_status().json()
        for run in runs:
            if run["status"] == "failed":
                return run["id"]
    raise SystemExit("No failed workflow found for a leaver with access remaining")


def table(rows: list[dict]) -> str:
    columns = list(rows[0])
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows[:MAX_ROWS]:
        lines.append("| " + " | ".join("" if row[c] is None else str(row[c]) for c in columns) + " |")
    if len(rows) > MAX_ROWS:
        lines.append(f"\n*…and {len(rows) - MAX_ROWS} more rows.*")
    return "\n".join(lines)


def facts_section(facts: dict) -> str:
    rows = facts.get("rows")
    if rows:
        header = f"Query `{facts.get('query')}`"
        if facts.get("period"):
            header += f" · {facts['period'].get('description')}"
        return f"{header} · {facts.get('row_count', len(rows))} rows\n\n{table(rows)}"
    body = json.dumps(facts, indent=2, default=str)
    if len(body) > 2500:
        body = body[:2500] + "\n…(truncated)"
    return f"```json\n{body}\n```"


def section(number: int, title: str, request: str, result: dict) -> str:
    ungrounded = ", ".join(result["ungrounded_numbers"]) or "none"
    answer = result["explanation"] or result["message"] or "(no text)"
    quoted = "\n".join(f"> {line}" if line else ">" for line in answer.splitlines())
    return (
        f"## {number}. {title}\n\n"
        f"**Request:** {request}\n\n"
        f"**Status:** `{result['ai_status']}` · model `{result['model'] or 'none'}` · "
        f"numbers in the answer that are not in the facts: {ungrounded}\n\n"
        f"### Facts given to the model\n\n{facts_section(result['facts'])}\n\n"
        f"### Answer (unedited model output)\n\n{quoted}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=120) as client:
        workflow_id = find_failed_offboarding(client)
        calls = [
            ("Question mapped to an approved query",
             "Which departments had the most synchronization failures this quarter?",
             lambda q: client.post("/api/ai/ask", json={"question": q})),
            ("Question mapped to an approved query",
             "What were the most common offboarding failures last month?",
             lambda q: client.post("/api/ai/ask", json={"question": q})),
            ("Question outside the approved queries",
             "What is the CEO's home address?",
             lambda q: client.post("/api/ai/ask", json={"question": q})),
            ("Failure explanation",
             "Why are license removal failures higher than group removal failures?",
             lambda q: client.post("/api/ai/failure-explanation", json={"question": q})),
            ("Monthly summary", "2026-09",
             lambda m: client.post("/api/ai/executive-summary", params={"month": m})),
            ("Data-quality explanation", None,
             lambda _: client.post("/api/ai/data-quality-explanation")),
            ("Incident report for a failed offboarding", workflow_id,
             lambda w: client.post(f"/api/ai/incident-report/{w}")),
        ]
        sections = []
        for number, (title, argument, call) in enumerate(calls, start=1):
            print(f"{number}. {title}…")
            result = call(argument).raise_for_status().json()
            if title.startswith("Question"):
                request = f'`POST /api/ai/ask` — "{argument}"'
            elif title == "Failure explanation":
                request = f'`POST /api/ai/failure-explanation` — "{argument}"'
            elif title == "Monthly summary":
                request = f"`POST /api/ai/executive-summary?month={argument}`"
            elif title == "Data-quality explanation":
                request = "`POST /api/ai/data-quality-explanation`"
            else:
                request = f"`POST /api/ai/incident-report/{argument}`"
            sections.append(section(number, title, request, result))

    OUTPUT.write_text(
        "# AI examples\n\n"
        f"Captured on {date.today():%Y-%m-%d} by `scripts/capture_ai_examples.py` against the synthetic "
        "dataset. Each answer is copied exactly as the model returned it, next to the facts it was given "
        "(computed by SQL) and the result of the grounding check, which lists any number in the answer "
        "that does not appear in the facts. See [ai.md](ai.md) for how the layer works.\n\n"
        "Model output varies between runs; re-running the script gives different wording over the same numbers.\n\n"
        + "\n".join(sections),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
