"""Create the read-only database login Power BI uses.

Reads REPORTING_DB_USER and REPORTING_DB_PASSWORD from the environment or .env.
Run after `alembic upgrade head`, and again after re-creating the reporting views.

Usage:
    python scripts/create_reporting_user.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.database import make_engine  # noqa: E402
from app.db.reporting_access import grant_reporting_access  # noqa: E402

logger = logging.getLogger("create_reporting_user")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.reporting_db_password:
        logger.error("Set REPORTING_DB_PASSWORD in .env first")
        return 1
    grant_reporting_access(make_engine(), settings.reporting_db_user, settings.reporting_db_password)
    logger.info("Login '%s' can now read the reporting views", settings.reporting_db_user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
