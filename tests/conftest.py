import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, get_settings
from app.etl.loader import load
from app.synthetic.simulator import generate


@pytest.fixture(scope="session")
def dataset() -> dict[str, list[dict]]:
    """The default synthetic dataset (seed 42), generated once per test session."""
    return generate()


@pytest.fixture(scope="session")
def db_engine():
    """A migrated, empty test database. Skips the database tests if PostgreSQL is not reachable."""
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("Test database is not reachable; start it with `docker compose up -d`")

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def loaded_engine(db_engine, dataset):
    """Test database containing the default dataset."""
    load(db_engine, dataset)
    return db_engine


@pytest.fixture
def session(loaded_engine):
    with Session(loaded_engine) as session:
        yield session


@pytest.fixture
def db(loaded_engine):
    """A session whose changes are all rolled back after the test.

    Commits inside the code under test only release a savepoint, so tests can create
    employees and run syncs without affecting each other.
    """
    with loaded_engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        yield session
        session.close()
        outer.rollback()
