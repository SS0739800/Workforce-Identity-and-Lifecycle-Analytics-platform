"""Generate the synthetic dataset and write it to data/raw/ as one CSV file per table.

Usage:
    python scripts/generate_data.py [--seed 42] [--output data/raw]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running as a plain script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.etl.csv_files import write_tables  # noqa: E402
from app.synthetic.assumptions import DEFAULT_SEED  # noqa: E402
from app.synthetic.simulator import generate  # noqa: E402

logger = logging.getLogger("generate_data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "raw")
    args = parser.parse_args()

    configure_logging()
    started = time.perf_counter()
    logger.info("Generating synthetic dataset with seed %s", args.seed)
    tables = generate(args.seed)
    write_tables(tables, args.output)

    for name, rows in tables.items():
        logger.info("%-22s %7d rows", name, len(rows))
    logger.info("Wrote %d tables to %s in %.1fs", len(tables), args.output, time.perf_counter() - started)


if __name__ == "__main__":
    main()
