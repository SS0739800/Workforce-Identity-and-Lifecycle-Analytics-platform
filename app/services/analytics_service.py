import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.queries import QUERIES

logger = logging.getLogger(__name__)

# Used when the caller gives no date range: wide enough to include all data.
EARLIEST_DATE = date(2000, 1, 1)
LATEST_DATE = date(2099, 12, 31)


class InvalidDateRange(ValueError):
    pass


def date_bounds(start_date: date | None, end_date: date | None) -> tuple[datetime, datetime]:
    """Turn inclusive calendar dates into a [start, end) UTC timestamp range."""
    start = start_date or EARLIEST_DATE
    end = end_date or LATEST_DATE
    if start > end:
        raise InvalidDateRange(f"start_date {start} is after end_date {end}")
    return (
        datetime.combine(start, time.min, tzinfo=timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
    )


def run_query(
    session: Session,
    name: str,
    start_date: date | None = None,
    end_date: date | None = None,
    **params,
) -> list[dict]:
    """Run an approved query by name. Unknown names raise KeyError."""
    query = QUERIES[name]
    values = dict(query.defaults)
    values.update(params)
    if query.uses_date_range:
        values["start_date"], values["end_date"] = date_bounds(start_date, end_date)

    rows = session.execute(text(query.sql), values).mappings().all()
    logger.debug("Query %s returned %d rows", name, len(rows))
    # PostgreSQL returns numeric results as Decimal; floats are simpler for JSON and charts.
    return [
        {key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()}
        for row in rows
    ]
