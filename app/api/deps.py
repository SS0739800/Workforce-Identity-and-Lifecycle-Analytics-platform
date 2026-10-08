"""Request dependencies for the operations endpoints. Tests override these to control time and failures."""

import random
from datetime import datetime, timezone


def get_now() -> datetime:
    return datetime.now(timezone.utc)


def get_rng() -> random.Random:
    # Unseeded: live runs fail at the documented rates, not in a fixed pattern.
    return random.Random()
