"""
models.py — SQLAlchemy ORM models for the Onboarding Agent API.

Tables:
    departments      — Department records (engineering, sales, marketing, hr)
    tasks            — Onboarding task definitions, scoped per department
    employees        — Employee records used for agent personalisation
    task_completions — Persistent completion records, scoped per user_oid

Per-user completion scoping:
    task_completions.user_oid stores the caller's identity:
        - Entra ID Bearer token:  real oid GUID (per-user state)
        - API key auth:           "_api_key"  (global shared state, legacy)
        - Local dev (no key):     "_dev"

    Route handlers do a bulk lookup of completed task IDs for the current
    user_oid rather than relying on a model-level relationship, since the
    ORM can't filter a relationship by request context automatically.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Department(Base):
    """One row per department. Name stored lowercase for case-insensitive lookups."""

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)  # e.g. "engineering"

    tasks = relationship("Task", back_populates="department", order_by="Task.order")
    employees = relationship("Employee", back_populates="department")

    def __repr__(self) -> str:
        return f"<Department name={self.name!r}>"


class Task(Base):
    """
    One row per onboarding task. task_key is the stable identifier used by the
    Copilot Studio agent (e.g. "eng_001"). Unique across all departments.

    Completion state is NOT stored on this model — it is user-scoped and lives
    in TaskCompletion. Route handlers look up completed task IDs for the current
    caller and pass `completed=True/False` into to_dict() explicitly.
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    task_key = Column(String(20), unique=True, nullable=False)  # "eng_001", "sal_002", …
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    order = Column(Integer, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    department = relationship("Department", back_populates="tasks")

    def to_dict(self, completed: bool = False) -> dict:
        """
        Serialize to the response schema the connector and agent expect.
        Caller must pass the per-user completed state explicitly.
        """
        return {
            "id": self.task_key,
            "title": self.title,
            "description": self.description,
            "order": self.order,
            "completed": completed,
        }

    def __repr__(self) -> str:
        return f"<Task key={self.task_key!r}>"


class Employee(Base):
    """
    Employee record used for personalised agent greetings.
    name stored lowercase (first name only) to match case-insensitive URL lookups.
    """

    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)   # first name, lowercase
    full_name = Column(String(100), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    manager = Column(String(100))
    team = Column(String(100))
    start_date = Column(String(20))   # ISO date string "YYYY-MM-DD"
    office = Column(String(100))

    department = relationship("Department", back_populates="employees")

    def to_dict(self) -> dict:
        """Serialize to the response schema returned by GET /employee/<name>."""
        return {
            "name": self.name.title(),
            "full_name": self.full_name,
            "department": self.department.name.title(),
            "manager": self.manager,
            "team": self.team,
            "start_date": self.start_date,
            "office": self.office,
        }

    def __repr__(self) -> str:
        return f"<Employee name={self.name!r}>"


class TaskCompletion(Base):
    """
    One row per (task, user) completion event.

    user_oid scopes completions to a specific caller:
        - Real Entra ID oid (GUID) when the request uses a Bearer token.
        - "_api_key" when the request uses the legacy X-API-Key header.
        - "_dev"     in local dev when no API_KEY env var is set.

    There is intentionally no UNIQUE constraint on (task_id, user_oid) at the
    DB level — the application layer prevents duplicate insertions via an
    existence check before inserting. A formal constraint and Alembic migration
    will be added in a later session.
    """

    __tablename__ = "task_completions"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_oid = Column(String(50), nullable=False, default="_api_key")
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("Task")

    def __repr__(self) -> str:
        return f"<TaskCompletion task_id={self.task_id} user={self.user_oid!r}>"
