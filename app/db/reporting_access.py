"""A read-only database login for Power BI.

The login can read the views in the `reporting` schema and nothing else. The views read the
underlying tables with their owner's rights, so no grants on the base tables are needed.
"""

from psycopg import sql
from sqlalchemy import Engine


def grant_reporting_access(engine: Engine, username: str, password: str) -> None:
    """Create the login (or reset its password) and grant read access to the reporting views."""
    role = sql.Identifier(username)
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
            if cursor.fetchone():
                cursor.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(role, sql.Literal(password)))
            else:
                cursor.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(role, sql.Literal(password)))

            cursor.execute("SELECT current_database()")
            database = sql.Identifier(cursor.fetchone()[0])
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA reporting TO {}").format(role))
            cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO {}").format(role))
        connection.commit()
    finally:
        connection.close()
