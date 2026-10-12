"""Map a natural-language question to one approved analytics query.

The model never writes SQL. A question is matched to a query in the registry by keywords;
only if that fails, Groq is asked to pick a name from the same registry, and its answer is
rejected unless the name is on the list. Time phrases ("last month") are parsed here, in code.
"""

import json
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.ai.client import AIError
from app.ai.fallback import AIClient
from app.ai.prompts import ROUTER_PROMPT
from app.analytics.queries import QUERIES

WORKFLOW_TYPES = ("onboarding", "offboarding", "leave", "return_from_leave")

# (query, keyword groups). Every group must match at least one keyword.
# More specific intents come first, so they win ties against general ones.
INTENTS: list[tuple[str, list[list[str]]]] = [
    ("sync_failures_by_department", [["sync", "synchroniz"], ["department", "dept", "team"]]),
    ("sync_failures_by_location", [["sync", "synchroniz"], ["location", "site", "plant", "office"]]),
    ("sync_failures_by_error_type", [["sync", "synchroniz"], ["error", "why", "reason", "cause", "type"]]),
    ("sync_monthly_trend", [["sync", "synchroniz"], ["trend", "monthly", "by month", "over time"]]),
    ("workflow_action_failures", [["onboard", "offboard", "leave", "return"], ["fail", "error", "problem"]]),
    ("time_to_disable_account", [["disable", "deprovision"], ["how quick", "how fast", "how long", "time", "hours"]]),
    ("access_remaining_after_offboarding", [["leaver", "terminated", "offboard"], ["access", "still", "remaining", "left"]]),
    ("license_cleanup_summary", [["license", "licence"]]),
    ("group_cleanup_summary", [["group"], ["remov", "cleanup", "clean up"]]),
    ("dq_by_department", [["data quality", "data-quality", "dq", "issue"], ["department"]]),
    ("dq_monthly_trend", [["data quality", "data-quality", "dq", "issue"], ["trend", "by month", "over time"]]),
    ("dq_by_type", [["data quality", "data-quality", "dq", "issue"], ["type", "kind", "field", "common", "significant", "biggest", "main"]]),
    ("action_failure_rates", [["action", "step"], ["fail"]]),
    ("repeated_operational_failures", [["repeat", "keep failing", "most failures"]]),
    ("pending_workflows", [["pending", "queued", "waiting"]]),
    ("attribute_changes_by_attribute", [["attribute", "hr change"]]),
    ("sync_summary", [["sync", "synchroniz"]]),
    ("dq_summary", [["data quality", "data-quality", "dq", "issue"]]),
    ("workflow_summary", [["workflow", "onboard", "offboard", "leave"]]),
]


@dataclass(frozen=True)
class Period:
    start: date | None
    end: date | None
    description: str


@dataclass(frozen=True)
class Route:
    query: str
    method: str  # "keywords" or "ai"
    params: dict = field(default_factory=dict)


def _has(text: str, keyword: str) -> bool:
    return re.search(r"\b" + re.escape(keyword), text) is not None


def workflow_type_in(text: str) -> str | None:
    text = text.lower()
    if _has(text, "return"):
        return "return_from_leave"
    if _has(text, "offboard"):
        return "offboarding"
    if _has(text, "onboard"):
        return "onboarding"
    if re.search(r"\bleave\b", text):
        return "leave"
    return None


def route_by_keywords(question: str) -> Route | None:
    text = question.lower()
    for query, groups in INTENTS:
        if all(any(_has(text, keyword) for keyword in group) for group in groups):
            params = {}
            if query == "workflow_action_failures":
                params["workflow_type"] = workflow_type_in(text) or "offboarding"
            return Route(query, "keywords", params)
    return None


def route_with_ai(question: str, client: AIClient) -> Route | None:
    catalog = "\n".join(f"- {name}: {query.question}" for name, query in QUERIES.items())
    try:
        response = client.complete(ROUTER_PROMPT.format(catalog=catalog), question, json_output=True)
        choice = json.loads(response.text)
    except (AIError, json.JSONDecodeError):
        return None

    name = choice.get("query") if isinstance(choice, dict) else None
    if name not in QUERIES:
        return None  # null, or a name that isn't on the allowlist
    params = {}
    if name == "workflow_action_failures":
        workflow_type = choice.get("workflow_type")
        params["workflow_type"] = workflow_type if workflow_type in WORKFLOW_TYPES else "offboarding"
    return Route(name, "ai", params)


MONTHS = {name: number for number, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def parse_period(question: str, as_of: date) -> Period:
    """Resolve a time phrase relative to `as_of` (the date of the most recent data)."""
    text = question.lower()

    if "this quarter" in text:
        return Period(_quarter_start(as_of), as_of, "this quarter")
    if "last quarter" in text or "previous quarter" in text:
        end = _quarter_start(as_of) - timedelta(days=1)
        return Period(_quarter_start(end), end, "last quarter")
    if "this month" in text:
        return Period(as_of.replace(day=1), as_of, "this month")
    if "last month" in text or "previous month" in text:
        end = as_of.replace(day=1) - timedelta(days=1)
        return Period(end.replace(day=1), end, "last month")
    if "this year" in text:
        return Period(date(as_of.year, 1, 1), as_of, "this year")
    if "last year" in text:
        return Period(date(as_of.year - 1, 1, 1), date(as_of.year - 1, 12, 31), "last year")

    days = re.search(r"last (\d{1,3}) days", text)
    if days:
        count = int(days.group(1))
        return Period(as_of - timedelta(days=count - 1), as_of, f"last {count} days")

    # A month counts only in a date-like context ("in March", "during May", "March 2026"),
    # so "what may cause this" is not read as the month of May.
    names = "|".join(MONTHS)
    month = (re.search(rf"\b(?:in|during|for)\s+({names})\b(?:\s+(\d{{4}}))?", text)
             or re.search(rf"\b({names})\s+(\d{{4}})\b", text))
    if month:
        number = MONTHS[month.group(1)]
        if month.group(2):
            year = int(month.group(2))
        else:
            # The most recent such month on or before the data's latest date.
            year = as_of.year if number <= as_of.month else as_of.year - 1
        return Period(date(year, number, 1), _month_end(year, number), f"{month.group(1).title()} {year}")

    return Period(None, None, "all available data")
