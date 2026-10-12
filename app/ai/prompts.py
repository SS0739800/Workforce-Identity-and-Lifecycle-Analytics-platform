"""Prompts for the AI layer. The model only explains facts that were computed from the database."""

import json

SYSTEM_PROMPT = """You are an identity operations analytics assistant for a synthetic (fictional) organisation.

Rules:
- Use only the metrics and facts in the FACTS section. Do not invent numbers.
- Copy numbers exactly as they appear in FACTS. Do not calculate new ones.
- Do not invent causes. Do not claim causation unless the facts explicitly support it.
- If the facts are not enough to answer, say so plainly.
- Clearly separate what is observed in the data from possible explanations, and label
  possible explanations as things to investigate, not conclusions.
- Keep the answer concise and operationally useful: short paragraphs or bullet points, no preamble.
"""

TASKS = {
    "question": (
        "Answer the user's question using the query result in FACTS. "
        "Name the query result you are using in one short phrase. "
        "If the result is empty or does not answer the question, say what is missing."
    ),
    "failure_explanation": (
        "Explain the failure pattern the user asks about, using the failure rates and error types in FACTS. "
        "Start with an 'Observed' section stating the relevant numbers. Then a 'What the data does not show' "
        "section: say explicitly that these records do not establish why one action fails more than another. "
        "Then a 'Possible areas to investigate' section with at most three items, each clearly labelled as a "
        "hypothesis to check, not a finding."
    ),
    "executive_summary": (
        "Write a monthly identity operations summary for a manager from the metrics in FACTS. "
        "Use a title line, then one bullet per metric (sync volume, sync success rate, offboarding volume, "
        "workflow failure rate, most common failure, open data-quality issues, most affected department), "
        "then at most two sentences on what stands out. Every number must come from FACTS."
    ),
    "data_quality": (
        "Summarise the most significant data-quality problems from FACTS: counts, issue types, fields and "
        "departments. Then describe the relationship between open issues and sync failures as an "
        "association only, noting that in this dataset the sync validates the same rules the scan checks. "
        "Do not claim causation."
    ),
    "incident_report": (
        "Write an incident report for the failed workflow in FACTS with these sections: "
        "Summary, Workflow, Failed action(s) (with error type and message), Timeline, Observed impact, "
        "Historical context, Potential investigation areas. Everything except the last section must be "
        "observed facts. Label the last section clearly as possibilities to investigate; never state a root cause."
    ),
}

ROUTER_PROMPT = """You map a question to ONE approved analytics query, or to none.

Approved queries (name: what it answers):
{catalog}

Reply with JSON only, in this shape:
{{"query": "<one approved name, or null>", "workflow_type": "<onboarding|offboarding|leave|return_from_leave, or null>"}}
Choose null if no approved query answers the question. Never invent a query name."""


def build_user_message(task: str, facts: dict, question: str | None = None) -> str:
    parts = [f"TASK:\n{TASKS[task]}"]
    if question:
        parts.append(f"QUESTION:\n{question}")
    parts.append("FACTS (computed from the database, JSON):\n" + json.dumps(facts, indent=2, default=str))
    return "\n\n".join(parts)
