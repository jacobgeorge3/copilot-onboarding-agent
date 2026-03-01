"""
models.py — SQLAlchemy ORM models for the Copilot Studio Onboarding Agent.

Tables:
    departments      — Department records (engineering, sales, marketing, hr)
    tasks            — Onboarding task definitions, scoped per department
    employees        — Employee records used for agent personalization
    task_completions — Persistent record of completed tasks (replaces _completion_store)

Phase 2 note (Entra ID):
    When Entra ID auth is added, extend TaskCompletion with an `employee_id` FK
    so completions are scoped per user instead of globally per task.
    Also add OnboardingSession to track a user's full onboarding run.
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
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    task_key = Column(String(20), unique=True, nullable=False)  # "eng_001", "sal_002", …
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    order = Column(Integer, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    department = relationship("Department", back_populates="tasks")
    # uselist=False → one-to-one: a task is completed at most once (global, pre-Entra ID)
    completion = relationship("TaskCompletion", back_populates="task", uselist=False)

    @property
    def completed(self) -> bool:
        """True when a TaskCompletion row exists for this task."""
        return self.completion is not None

    def to_dict(self) -> dict:
        """Serialize to the response schema the agent and connector expect."""
        return {
            "id": self.task_key,
            "title": self.title,
            "description": self.description,
            "order": self.order,
            "completed": self.completed,
        }

    def __repr__(self) -> str:
        return f"<Task key={self.task_key!r} completed={self.completed}>"


class Employee(Base):
    """
    Employee record used for personalized agent greetings.
    name is stored lowercase (first name only) to match case-insensitive URL lookups.
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
        return f"<Employee name={self.name!r} dept={self.department_id}>"


class TaskCompletion(Base):
    """
    Persistent replacement for the in-memory _completion_store dict.

    One row per completed task. Inserting a row marks the task complete;
    deleting it (future reset endpoint) marks it incomplete again.

    Phase 2 — Entra ID: add `employee_id = Column(ForeignKey("employees.id"))`
    and a composite unique constraint on (task_id, employee_id) so each user
    has independent completion state.
    """

    __tablename__ = "task_completions"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, unique=True)
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("Task", back_populates="completion")

    def __repr__(self) -> str:
        return f"<TaskCompletion task_id={self.task_id} at={self.completed_at}>"
