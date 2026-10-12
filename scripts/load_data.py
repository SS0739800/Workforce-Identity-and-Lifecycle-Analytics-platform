"""Validate the raw CSV files and load them into PostgreSQL.

Run the Alembic migrations first:
    alembic upgrade head
    python scripts/load_data.py [--input data/raw] [--if-empty]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.database import make_engine  # noqa: E402
from app.etl.loader import ValidationError, has_employees, load, read_raw_tables, validate  # noqa: E402

logger = logging.getLogger("load_data")


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, default=settings.raw_data_dir)
    parser.add_argument("--if-empty", action="store_true",
                        help="skip the load if the database already has employees (used by the AWS deployment, "
                             "so a redeploy keeps changes made through the API)")
    args = parser.parse_args()

    configure_logging(settings.log_level)
    started = time.perf_counter()
    engine = make_engine()

    if args.if_empty and has_employees(engine):
        logger.info("Database already has data; skipping the load (--if-empty)")
        return 0

    try:
        data = read_raw_tables(args.input)
    except ValidationError as error:
        for problem in error.problems:
            logger.error(problem)
        return 1

    problems = validate(data)
    if problems:
        for problem in problems:
            logger.error(problem)
        logger.error("Validation failed; nothing was loaded")
        return 1
    logger.info("Validation passed for %d tables", len(data))

    counts = load(engine, data)
    mismatched = [name for name, rows in data.items() if counts[name] != len(rows)]
    if mismatched:
        logger.error("Row counts in the database do not match the CSV files: %s", ", ".join(mismatched))
        return 1

    logger.info("Loaded %d rows in %.1fs", sum(counts.values()), time.perf_counter() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
