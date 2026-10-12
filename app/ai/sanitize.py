"""Remove personal fields before anything is sent to Groq.

The data is synthetic, but the AI layer is written as if it were not: employees are only
referred to by their HR employee ID, and names, emails and usernames never leave the database.
"""

import re

# Fields that identify a person directly.
PERSONAL_FIELDS = {
    "first_name",
    "last_name",
    "employee_name",
    "manager_name",
    "name",
    "email",
    "username",
}

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def sanitize(value):
    """Return a copy with personal fields dropped and any email-like text redacted."""
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items() if key not in PERSONAL_FIELDS}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub("[redacted email]", value)
    return value


def contains_personal_data(value) -> bool:
    """True if a personal field name or an email address is present anywhere."""
    if isinstance(value, dict):
        return any(key in PERSONAL_FIELDS or contains_personal_data(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_personal_data(item) for item in value)
    if isinstance(value, str):
        return bool(EMAIL_PATTERN.search(value))
    return False
