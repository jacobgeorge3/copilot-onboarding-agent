"""
database.py — SQLAlchemy engine and session configuration.

Environment variables:
    DATABASE_URL    Full connection string for the target database.
                    If unset, falls back to a local SQLite file (onboarding_dev.db).

Supported backends:
    Local dev (default, zero config):
        SQLite file created automatically in the project root.

    Azure SQL (production):
        DATABASE_URL=mssql+pyodbc://<user>:<password>@<server>.database.windows.net:1433/<db>
        ?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no

Session lifecycle in Flask:
    db_session is a scoped session tied to the current thread. Register
    db_session.remove() in app.teardown_appcontext to clean up after each request.
"""

import logging
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker

logger = logging.getLogger(__name__)

_SQLITE_FALLBACK = "sqlite:///onboarding_dev.db"


def _build_engine():
    url = os.environ.get("DATABASE_URL", _SQLITE_FALLBACK)
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
db_session = scoped_session(SessionLocal)


def init_db() -> None:
    """
    Create all tables defined in models.py if they don't already exist.
    Then run migrate_db() to apply any schema changes to existing tables.
    Safe to call on every startup.
    """
    from models import Base
    Base.metadata.create_all(bind=engine)
    migrate_db()


def migrate_db() -> None:
    """
    Apply incremental schema changes that SQLAlchemy's create_all() cannot
    handle (it only creates missing tables, never alters existing ones).

    Session 5 migration — Entra ID auth:
        task_completions.user_oid (VARCHAR 50) was added to scope completions
        per user. The old schema had a UNIQUE constraint on task_id alone (one
        global completion per task). The new schema allows one completion per
        (task_id, user_oid) pair with no DB-level constraint (enforced in app).

        Strategy: if user_oid column is missing, drop and recreate the table.
        Any existing completion rows are lost — acceptable for a dev/demo system
        where completion data is not authoritative.
    """
    insp = inspect(engine)

    if not insp.has_table("task_completions"):
        return  # Table doesn't exist yet — create_all() will handle it.

    existing_columns = {col["name"] for col in insp.get_columns("task_completions")}

    if "user_oid" not in existing_columns:
        logger.info(
            "Schema migration: task_completions missing user_oid column. "
            "Dropping and recreating table (completion history will be reset)."
        )
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE task_completions"))

        from models import Base
        Base.metadata.create_all(bind=engine)
        logger.info("Schema migration complete: task_completions recreated with user_oid.")
