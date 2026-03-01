#!/usr/bin/env python3
"""
seed.py — Populate the database with initial departments, tasks, and employees.

Run once after provisioning the database (local SQLite or Azure SQL):

    python seed.py

Safe to re-run: existing rows are skipped, not duplicated.
To reset all completion state only (without touching employees/tasks):

    python seed.py --reset-completions
"""

import argparse
import sys

from database import SessionLocal, init_db
from models import Department, Employee, Task, TaskCompletion


# ---------------------------------------------------------------------------
# Seed data — mirrors the hardcoded dicts that were in app.py
# ---------------------------------------------------------------------------

DEPARTMENTS = ["engineering", "sales", "marketing", "hr"]

TASKS_BY_DEPT: dict[str, list[dict]] = {
    "engineering": [
        {
            "task_key": "eng_001",
            "title": "Set up development environment",
            "description": (
                "Install VS Code, Docker, Git, and clone the team repository. "
                "Follow the README in the team repo for environment setup steps."
            ),
            "order": 1,
        },
        {
            "task_key": "eng_002",
            "title": "Complete security training",
            "description": (
                "Finish the mandatory security awareness module in the LMS. "
                "Takes approximately 45 minutes. Certificate auto-uploads to your profile."
            ),
            "order": 2,
        },
        {
            "task_key": "eng_003",
            "title": "Attend team architecture sync",
            "description": (
                "Join the weekly architecture sync (Thursdays, 10am PT). "
                "Calendar invite sent by your manager on Day 1."
            ),
            "order": 3,
        },
        {
            "task_key": "eng_004",
            "title": "Submit your first pull request",
            "description": (
                "Pick a 'good first issue' from the backlog, make the change, "
                "and open a PR for review. This gets you familiar with the team's "
                "code review process."
            ),
            "order": 4,
        },
    ],
    "sales": [
        {
            "task_key": "sal_001",
            "title": "Complete CRM onboarding",
            "description": (
                "Log in to Salesforce, complete the intro walkthrough, "
                "and verify your assigned territory and accounts are correct."
            ),
            "order": 1,
        },
        {
            "task_key": "sal_002",
            "title": "Shadow two discovery calls",
            "description": (
                "Coordinate with your manager to shadow two live discovery calls "
                "in your first week. Take notes and debrief afterward."
            ),
            "order": 2,
        },
        {
            "task_key": "sal_003",
            "title": "Review product positioning deck",
            "description": (
                "Read the latest competitive positioning deck in SharePoint. "
                "Confirm with your manager which version is current before reading."
            ),
            "order": 3,
        },
        {
            "task_key": "sal_004",
            "title": "Complete sales methodology certification",
            "description": (
                "Finish the MEDDIC certification course in the LMS. "
                "Required before leading your first customer call independently."
            ),
            "order": 4,
        },
    ],
    "marketing": [
        {
            "task_key": "mkt_001",
            "title": "Access brand asset library",
            "description": (
                "Log in to the DAM (Digital Asset Management) system and confirm "
                "access to the brand kit, logo files, and approved templates."
            ),
            "order": 1,
        },
        {
            "task_key": "mkt_002",
            "title": "Review content calendar",
            "description": (
                "Access the shared content calendar in SharePoint and introduce "
                "yourself in the #content-team Slack channel."
            ),
            "order": 2,
        },
        {
            "task_key": "mkt_003",
            "title": "Complete data privacy training",
            "description": (
                "Finish the GDPR and data privacy module in the LMS. "
                "Required for anyone handling campaign data or contact lists."
            ),
            "order": 3,
        },
        {
            "task_key": "mkt_004",
            "title": "Attend campaign planning standup",
            "description": (
                "Join the weekly campaign planning standup (Tuesdays, 9am PT). "
                "Calendar invite sent by your manager."
            ),
            "order": 4,
        },
    ],
    "hr": [
        {
            "task_key": "hr_001",
            "title": "Complete HRIS system access",
            "description": (
                "Log in to Workday and verify your employee profile is complete "
                "and accurate. Flag any discrepancies to IT immediately."
            ),
            "order": 1,
        },
        {
            "task_key": "hr_002",
            "title": "Review HR policy documentation",
            "description": (
                "Read the current employee handbook and HR policy library "
                "in SharePoint. Confirm version is current with your manager."
            ),
            "order": 2,
        },
        {
            "task_key": "hr_003",
            "title": "Shadow a benefits enrollment session",
            "description": (
                "Sit in on an upcoming benefits Q&A session to understand "
                "the enrollment process from the employee perspective."
            ),
            "order": 3,
        },
        {
            "task_key": "hr_004",
            "title": "Complete employment law training",
            "description": (
                "Finish the employment law fundamentals module in the LMS. "
                "Required for all HR team members before handling employee relations cases."
            ),
            "order": 4,
        },
    ],
}

EMPLOYEES: list[dict] = [
    {
        "name": "jacob",
        "full_name": "Jacob George",
        "department": "engineering",
        "manager": "Sarah Chen",
        "team": "Platform Infrastructure",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    {
        "name": "alex",
        "full_name": "Alex Rivera",
        "department": "sales",
        "manager": "Marcus Webb",
        "team": "Enterprise Accounts",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    {
        "name": "jordan",
        "full_name": "Jordan Kim",
        "department": "marketing",
        "manager": "Priya Nair",
        "team": "Brand & Content",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    {
        "name": "morgan",
        "full_name": "Morgan Patel",
        "department": "hr",
        "manager": "Linda Torres",
        "team": "People Operations",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_all(db) -> None:
    """Insert departments, tasks, and employees. Skip rows that already exist."""
    dept_map: dict[str, Department] = {}

    # --- Departments ---
    for dept_name in DEPARTMENTS:
        dept = db.query(Department).filter_by(name=dept_name).first()
        if not dept:
            dept = Department(name=dept_name)
            db.add(dept)
            db.flush()  # assign .id without committing
            print(f"  [+] Department: {dept_name}")
        else:
            print(f"  [=] Department exists: {dept_name}")
        dept_map[dept_name] = dept

    # --- Tasks ---
    for dept_name, task_list in TASKS_BY_DEPT.items():
        dept = dept_map[dept_name]
        for task_data in task_list:
            task = db.query(Task).filter_by(task_key=task_data["task_key"]).first()
            if not task:
                task = Task(
                    task_key=task_data["task_key"],
                    title=task_data["title"],
                    description=task_data["description"],
                    order=task_data["order"],
                    department_id=dept.id,
                )
                db.add(task)
                print(f"  [+] Task: {task_data['task_key']} ({dept_name})")
            else:
                print(f"  [=] Task exists: {task_data['task_key']}")

    # --- Employees ---
    for emp_data in EMPLOYEES:
        emp = db.query(Employee).filter_by(name=emp_data["name"]).first()
        if not emp:
            dept = dept_map[emp_data["department"]]
            emp = Employee(
                name=emp_data["name"],
                full_name=emp_data["full_name"],
                department_id=dept.id,
                manager=emp_data["manager"],
                team=emp_data["team"],
                start_date=emp_data["start_date"],
                office=emp_data["office"],
            )
            db.add(emp)
            print(f"  [+] Employee: {emp_data['name']}")
        else:
            print(f"  [=] Employee exists: {emp_data['name']}")

    db.commit()
    print("\nSeed complete.")


def reset_completions(db) -> None:
    """Delete all TaskCompletion rows — resets all task progress without touching data."""
    deleted = db.query(TaskCompletion).delete()
    db.commit()
    print(f"Cleared {deleted} completion record(s).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the onboarding agent database.")
    parser.add_argument(
        "--reset-completions",
        action="store_true",
        help="Delete all task completion records (resets demo progress).",
    )
    args = parser.parse_args()

    print("Initialising database schema…")
    init_db()

    db = SessionLocal()
    try:
        if args.reset_completions:
            print("Resetting completion records…")
            reset_completions(db)
        else:
            print("Seeding departments, tasks, and employees…")
            seed_all(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
