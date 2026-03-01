"""
Copilot Studio Customer Onboarding Agent — Flask API
=====================================================
Backend for a Microsoft Copilot Studio agent that guides new employees
through a structured onboarding workflow. Consumed by a Power Platform
custom connector.

Endpoints:
    GET  /employee/<name>         - Fetch employee record for agent greeting
    GET  /onboarding/<department> - Fetch ordered task checklist by department
    POST /complete-task           - Mark a task complete, return updated progress
    GET  /health                  - Azure App Service health check (no auth)

Authentication (dual-mode — see auth.py):
    Mode 1: X-API-Key header (existing connector, unchanged)
    Mode 2: Authorization: Bearer <Entra ID JWT> (production)
    Both modes are active simultaneously for zero-downtime migration.

    Required env vars for Bearer token mode:
        ENTRA_TENANT_ID   Azure AD directory/tenant ID (GUID)
        ENTRA_CLIENT_ID   Application (client) ID of the app registration

Data persistence:
    SQLAlchemy ORM. SQLite by default; Azure SQL via DATABASE_URL env var.
    Task completions are scoped per user_oid (real Entra oid when using
    Bearer token; "_api_key" when using the legacy API key).

Error Responses:
    All errors return structured JSON so Copilot Studio can parse them
    and route to a fallback topic gracefully.
    Schema: { "error": { "code": str, "message": str, "details": any } }
"""

import os

from flask import Flask, jsonify, request

from auth import get_caller_identity, require_auth
from database import db_session, init_db
from models import Department, Employee, Task, TaskCompletion

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Database initialisation (runs once at startup)
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()
    # Auto-seed on first startup: if departments table is empty, populate all
    # reference data. Safe on every startup — seed_all() skips existing rows.
    from models import Department as _Dept
    from seed import seed_all
    _db = db_session()
    if _db.query(_Dept).count() == 0:
        app.logger.info("Database is empty — running initial seed.")
        seed_all(_db)
    else:
        app.logger.info("Database already seeded — skipping.")
    db_session.remove()


@app.teardown_appcontext
def shutdown_db_session(exception=None) -> None:
    """Return the scoped session to the connection pool after each request."""
    db_session.remove()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def error_response(code: str, message: str, status: int, details=None):
    """Return a structured JSON error response Copilot Studio can parse."""
    return jsonify({"error": {"code": code, "message": message, "details": details}}), status


def _get_completed_task_ids(tasks: list[Task], user_oid: str) -> set[int]:
    """
    Return the set of Task.id values already completed by this user_oid.
    Single bulk query — avoids N+1 per task.
    """
    task_ids = [t.id for t in tasks]
    if not task_ids:
        return set()
    completions = (
        db_session.query(TaskCompletion.task_id)
        .filter(
            TaskCompletion.user_oid == user_oid,
            TaskCompletion.task_id.in_(task_ids),
        )
        .all()
    )
    return {row.task_id for row in completions}


def _completion_percentage(tasks: list[Task], completed_ids: set[int]) -> int:
    if not tasks:
        return 0
    return round((len(completed_ids) / len(tasks)) * 100)


# ---------------------------------------------------------------------------
# Global error handlers — ensure Flask never returns HTML to Power Platform
# ---------------------------------------------------------------------------

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred. Please try again or contact support.",
        status=500,
    )

@app.errorhandler(404)
def handle_404(e):
    return error_response(code="NOT_FOUND", message="The requested endpoint does not exist.", status=404)

@app.errorhandler(405)
def handle_405(e):
    return error_response(code="METHOD_NOT_ALLOWED", message="HTTP method not allowed on this endpoint.", status=405)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/employee/<string:name>", methods=["GET"])
@require_auth
def get_employee(name: str):
    """
    GET /employee/<name>

    Returns the employee record for the given first name.
    Called by the Copilot Studio agent at conversation start to personalise
    the greeting and pre-populate department context.

    When the caller is authenticated via Entra ID Bearer token, the response
    also includes their identity context so the agent can confirm who's signed in.
    """
    employee = db_session.query(Employee).filter_by(name=name.lower()).first()
    if not employee:
        return error_response(
            code="EMPLOYEE_NOT_FOUND",
            message=f"No employee record found for '{name}'. "
                    f"The agent will ask the user to confirm their department.",
            status=404,
        )

    result = employee.to_dict()

    # Enrich with caller identity when available (Entra ID mode only).
    identity = get_caller_identity()
    if identity["via_entra"]:
        result["authenticated_as"] = {
            "oid": identity["user_oid"],
            "name": identity["name"],
            "upn": identity["upn"],
        }

    return jsonify(result), 200


@app.route("/onboarding/<string:department>", methods=["GET"])
@require_auth
def get_onboarding_tasks(department: str):
    """
    GET /onboarding/<department>

    Returns the ordered onboarding task checklist for the given department,
    with completion state scoped to the current caller's user_oid.

    API key callers share a global "_api_key" completion state (same behaviour
    as before persistence was added). Entra ID callers each have independent
    per-user state — Jacob's progress is separate from Alex's.
    """
    dept = db_session.query(Department).filter_by(name=department.lower()).first()
    if not dept:
        valid = [d.name.title() for d in db_session.query(Department).order_by(Department.name).all()]
        return error_response(
            code="DEPARTMENT_NOT_FOUND",
            message=f"Department '{department}' is not recognised. "
                    f"Valid values: {', '.join(valid)}.",
            status=404,
        )

    identity = get_caller_identity()
    user_oid = identity["user_oid"]

    tasks = dept.tasks  # ordered by Task.order
    completed_ids = _get_completed_task_ids(tasks, user_oid)
    pct = _completion_percentage(tasks, completed_ids)

    task_dicts = [t.to_dict(completed=t.id in completed_ids) for t in tasks]
    next_task = next((t for t in tasks if t.id not in completed_ids), None)

    return jsonify({
        "department": department.title(),
        "tasks": task_dicts,
        "total_tasks": len(tasks),
        "completion_percentage": pct,
        "next_task": next_task.to_dict(completed=False) if next_task else None,
    }), 200


@app.route("/complete-task", methods=["POST"])
@require_auth
def complete_task():
    """
    POST /complete-task

    Marks a task as complete for the current caller and returns updated progress.
    Scoped to the caller's user_oid — each Entra ID user has independent state.
    Idempotent: marking an already-completed task is a no-op.

    Request body (JSON):
        task_id    (str): ID of the task to mark complete (e.g. 'eng_001').
        department (str): Department the task belongs to.
    """
    body = request.get_json(silent=True)
    if not body:
        return error_response(
            code="INVALID_REQUEST",
            message="Request body must be valid JSON with 'task_id' and 'department' fields.",
            status=400,
        )

    task_id = body.get("task_id", "").strip()
    department = body.get("department", "").strip()

    if not task_id or not department:
        return error_response(
            code="MISSING_FIELDS",
            message="Both 'task_id' and 'department' are required.",
            status=400,
        )

    # Validate department
    dept = db_session.query(Department).filter_by(name=department.lower()).first()
    if not dept:
        return error_response(
            code="DEPARTMENT_NOT_FOUND",
            message=f"Department '{department}' is not recognised.",
            status=404,
        )

    # Validate task exists and belongs to this department
    task = db_session.query(Task).filter_by(task_key=task_id, department_id=dept.id).first()
    if not task:
        valid_keys = [t.task_key for t in dept.tasks]
        return error_response(
            code="TASK_NOT_FOUND",
            message=f"Task '{task_id}' not found in department '{department}'. "
                    f"Valid task IDs: {', '.join(valid_keys)}.",
            status=404,
        )

    identity = get_caller_identity()
    user_oid = identity["user_oid"]

    # Mark complete — idempotent: skip if already completed for this user.
    already_done = (
        db_session.query(TaskCompletion)
        .filter_by(task_id=task.id, user_oid=user_oid)
        .first()
    )
    if not already_done:
        completion = TaskCompletion(task_id=task.id, user_oid=user_oid)
        db_session.add(completion)
        db_session.commit()

    # Build updated task list for response
    tasks = dept.tasks
    completed_ids = _get_completed_task_ids(tasks, user_oid)
    pct = _completion_percentage(tasks, completed_ids)
    next_task = next((t for t in tasks if t.id not in completed_ids), None)

    return jsonify({
        "task_id": task_id,
        "completed": True,
        "department": department.title(),
        "completion_percentage": pct,
        "remaining_tasks": len(tasks) - len(completed_ids),
        "all_complete": pct == 100,
        "next_task": next_task.to_dict(completed=False) if next_task else None,
    }), 200


# ---------------------------------------------------------------------------
# Health check — used by Azure App Service to verify the app is running
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
