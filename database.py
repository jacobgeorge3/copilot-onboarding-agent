"""
database.py — SQLAlchemy engine and session configuration.

Environment variables:
    DATABASE_URL    Full connection string for the target database.
                    If unset, falls back to a local SQLite file (onboarding_dev.db).

Supported backends:
    Local dev   (default, zero config):
        SQLite file created automatically in the project root.
        No DATABASE_URL needed.

    Azure SQL   (production):
        Set DATABASE_URL in Azure App Service → Configuration → Application Settings.

        Format:
            mssql+pyodbc://<user>:<password>@<server>.database.windows.net:1433/<dbname>
            ?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no

        Requires: pyodbc installed (in requirements.txt) and the ODBC Driver for SQL
        Server on the host. Azure App Service Linux (Python 3.12) ships with ODBC
        Driver 17; Driver 18 is available via the startup command if needed.

    Postgres / MySQL:
        Supply the appropriate SQLAlchemy URL and install the matching driver.

Session lifecycle in Flask:
    db_session is a scoped session tied to the current thread. Register
    db_session.remove() in app.teardown_appcontext to ensure the connection
    is returned to the pool at the end of every HTTP request.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

_SQLITE_FALLBACK = "sqlite:///onboarding_dev.db"


def _build_engine():
    url = os.environ.get("DATABASE_URL", _SQLITE_FALLBACK)

    kwargs: dict = {
        "pool_pre_ping": True,  # detect stale connections — important for Azure SQL
    }

    if url.startswith("sqlite"):
        # SQLite: disable same-thread check so Flask's threaded server works.
        kwargs["connect_args"] = {"check_same_thread": False}

    return create_engine(url, **kwargs)


engine = _build_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# scoped_session returns the same Session object within a thread, then cleans
# up when .remove() is called (typically in teardown_appcontext).
db_session = scoped_session(SessionLocal)


def init_db() -> None:
    """
    Create all tables defined in models.py if they don't already exist.

    Safe to call on every app startup — CREATE TABLE IF NOT EXISTS semantics.
    Does NOT drop existing data; use seed.py to populate initial rows.
    """
    from models import Base  # local import avoids circular dependency at module load
    Base.metadata.create_all(bind=engine)
