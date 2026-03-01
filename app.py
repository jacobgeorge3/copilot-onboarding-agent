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

Authentication:
    All endpoints (except /health) require the X-API-Key header.
    Set the API_KEY environment variable in Azure App Service Application Settings.
    Never hardcode the key value in source.

Data persistence:
    Employee records, tasks, and completion state are stored in a SQLAlchemy-
    managed database. By default this is a local SQLite file (onboarding_dev.db).
    In production, set DATABASE_URL to an Azure SQL connection string.
    Run seed.py once after provisioning the database to load initial data.

Error Responses:
    All errors return structured JSON (never HTML) so Copilot Studio
    can parse them and route to a fallback topic gracefully.
    Schema: { "error": { "code": str, "message": str, "details": any } }
"""

import os
from functools import wraps

from flask import Flask, jsonify, request

from database import db_session, init_db
from models import Department, Employee, Task, TaskCompletion

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()


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


def _get_tasks_for_dept(dept_name: str) -> list[Task]:
    """Return ordered Task objects for a department, with completion state loaded."""
    dept = db_session.query(Department).filter_by(name=dept_name.lower()).first()
    if not dept:
        return []
    return dept.tasks  # already ordered by Task.order via relationship


def _completion_percentage(tasks: list[Task]) -> int:
    if not tasks:
        return 0
    completed = sum(1 for t in tasks if t.completed)
    return round((completed / len(tasks)) * 100)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def require_api_key(f):
    """
    Decorator that validates the X-API-Key request header.

    The expected key is read from the API_KEY environment variable.
    In Azure App Service, set this under Configuration > Application Settings.

    Returns 401 with a structured error body on failure so Copilot Studio
    can route to a graceful fallback rather than crashing the conversation.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = os.environ.get("API_KEY", "")
        provided = request.headers.get("X-API-Key", "")
        if not expected:
            # Fail open during local development when API_KEY is not set.
            app.logger.warning("API_KEY environment variable is not set. Skipping auth check.")
            return f(*args, **kwargs)
        if provided != expected:
            return error_response(
                code="UNAUTHORIZED",
                message="Invalid or missing API key. Provide a valid key in the X-API-Key header.",
                status=401,
            )
        return f(*args, **kwargs)
    return decorated


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
    return error_response(
        code="NOT_FOUND",
        message="The requested endpoint does not exist.",
        status=404,
    )

@app.errorhandler(405)
def handle_405(e):
    return error_response(
        code="METHOD_NOT_ALLOWED",
        message="HTTP method not allowed on this endpoint.",
        status=405,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/employee/<string:name>", methods=["GET"])
@require_api_key
def get_employee(name: str):
    """
    GET /employee/<name>

    Returns the employee record for the given first name.
    Called by the Copilot Studio agent at conversation start to personalise
    the greeting and pre-populate department context.

    Path param:
        name (str): Employee first name. Case-insensitive.

    Returns 200 with employee record or 404 if name not found.
    On 404, the agent falls back to asking the user for their department manually.
    """
    employee = db_session.query(Employee).filter_by(name=name.lower()).first()
    if not employee:
        return error_response(
            code="EMPLOYEE_NOT_FOUND",
            message=f"No employee record found for '{name}'. "
                    f"The agent will ask the user to confirm their department.",
            status=404,
        )
    return jsonify(employee.to_dict()), 200


@app.route("/onboarding/<string:department>", methods=["GET"])
@require_api_key
def get_onboarding_tasks(department: str):
    """
    GET /onboarding/<department>

    Returns the ordered onboarding task checklist for the given department,
    with live completion state from the database.
    Called by the Copilot Studio agent to begin the checklist conversation act.

    Path param:
        department (str): One of Engineering, Sales, Marketing, HR. Case-insensitive.

    Returns 200 with task list and progress summary, or 404 for unknown departments.
    """
    dept_lower = department.lower()
    dept = db_session.query(Department).filter_by(name=dept_lower).first()

    if not dept:
        valid = [d.name.title() for d in db_session.query(Department).order_by(Department.name).all()]
        return error_response(
            code="DEPARTMENT_NOT_FOUND",
            message=f"Department '{department}' is not recognised. "
                    f"Valid values: {', '.join(valid)}.",
            status=404,
        )

    tasks = dept.tasks  # ordered by Task.order via relationship
    next_task = next((t for t in tasks if not t.completed), None)

    return jsonify({
        "department": department.title(),
        "tasks": [t.to_dict() for t in tasks],
        "total_tasks": len(tasks),
        "completion_percentage": _completion_percentage(tasks),
        "next_task": next_task.to_dict() if next_task else None,
    }), 200


@app.route("/complete-task", methods=["POST"])
@require_api_key
def complete_task():
    """
    POST /complete-task

    Marks a task as complete in the database and returns the updated task list
    with new completion percentage and the next incomplete task.
    Called by the Copilot Studio agent when the user confirms a step is done.

    Request body (JSON):
        task_id    (str): ID of the task to mark complete (e.g. 'eng_001').
        department (str): Department the task belongs to.

    Returns 200 with updated progress, 400 for missing fields, 404 for unknown task.
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

    # Mark complete — idempotent: do nothing if already completed
    if not task.completed:
        completion = TaskCompletion(task_id=task.id)
        db_session.add(completion)
        db_session.commit()
        # Expire cached state so the relationship reflects the new row
        db_session.expire(task)

    # Build updated task list for response
    tasks = dept.tasks
    next_task = next((t for t in tasks if not t.completed), None)
    pct = _completion_percentage(tasks)

    return jsonify({
        "task_id": task_id,
        "completed": True,
        "department": department.title(),
        "completion_percentage": pct,
        "remaining_tasks": sum(1 for t in tasks if not t.completed),
        "all_complete": pct == 100,
        "next_task": next_task.to_dict() if next_task else None,
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
    # Local development only. Azure App Service uses gunicorn via startup.txt.
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
