import random


class FixedRandom(random.Random):
    """A random generator whose random() always returns the same value.

    value=0.0 makes every failure check fail; value=0.999 makes every action succeed.
    randint() still works, so simulated durations stay realistic.
    """

    def __init__(self, value: float):
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


ALWAYS_FAIL = 0.0
NEVER_FAIL = 0.999
# Above the 1% sync timeout rate but below create_account's 3% failure rate:
# the sync record succeeds and account creation fails.
ACCOUNT_CREATION_FAILS = 0.02
