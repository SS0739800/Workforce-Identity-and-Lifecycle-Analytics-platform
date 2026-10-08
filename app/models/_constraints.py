from sqlalchemy import CheckConstraint


def allowed_values(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """CHECK constraint restricting a status-style column to a fixed set of values."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=f"{column}_allowed")
