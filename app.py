"""
Copilot Studio Customer Onboarding Agent — Flask API
=====================================================
Backend for a Microsoft Copilot Studio agent that guides new employees
through a structured onboarding workflow. Consumed by a Power Platform
custom connector.

Endpoints:
    GET  /employee/<name>         - Fetch mock employee record for agent greeting
    GET  /onboarding/<department> - Fetch ordered task checklist by department
    POST /complete-task           - Mark a task complete, return updated progress

Authentication:
    All endpoints require the X-API-Key header.
    Set the API_KEY environment variable in Azure App Service Application Settings.
    Never hardcode the key value in source.

Error Responses:
    All errors return structured JSON (never HTML) so Copilot Studio
    can parse them and route to a fallback topic gracefully.
    Schema: { "error": { "code": str, "message": str, "details": any } }
"""

import os
from functools import wraps
from flask import Flask, jsonify, request

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Hardcoded data
# ---------------------------------------------------------------------------
# PoC Note: In production, replace these dicts with Azure SQL or Dataverse
# queries. The endpoint signatures and response schemas remain identical —
# only the data access layer changes. See IMPLEMENTATION_PLAN.md.

EMPLOYEES = {
    "jacob": {
        "name": "Jacob",
        "full_name": "Jacob George",
        "department": "Engineering",
        "manager": "Sarah Chen",
        "team": "Platform Infrastructure",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    "alex": {
        "name": "Alex",
        "full_name": "Alex Rivera",
        "department": "Sales",
        "manager": "Marcus Webb",
        "team": "Enterprise Accounts",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    "jordan": {
        "name": "Jordan",
        "full_name": "Jordan Kim",
        "department": "Marketing",
        "manager": "Priya Nair",
        "team": "Brand & Content",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
    "morgan": {
        "name": "Morgan",
        "full_name": "Morgan Patel",
        "department": "HR",
        "manager": "Linda Torres",
        "team": "People Operations",
        "start_date": "2026-03-01",
        "office": "Remote",
    },
}

TASKS = {
    "engineering": [
        {
            "id": "eng_001",
            "title": "Set up development environment",
            "description": "Install VS Code, Docker, Git, and clone the team repository. "
                           "Follow the README in the team repo for environment setup steps.",
            "order": 1,
        },
        {
            "id": "eng_002",
            "title": "Complete security training",
            "description": "Finish the mandatory security awareness module in the LMS. "
                           "Takes approximately 45 minutes. Certificate auto-uploads to your profile.",
            "order": 2,
        },
        {
            "id": "eng_003",
            "title": "Attend team architecture sync",
            "description": "Join the weekly architecture sync (Thursdays, 10am PT). "
                           "Calendar invite sent by your manager on Day 1.",
            "order": 3,
        },
        {
            "id": "eng_004",
            "title": "Submit your first pull request",
            "description": "Pick a 'good first issue' from the backlog, make the change, "
                           "and open a PR for review. This gets you familiar with the team's "
                           "code review process.",
            "order": 4,
        },
    ],
    "sales": [
        {
            "id": "sal_001",
            "title": "Complete CRM onboarding",
            "description": "Log in to Salesforce, complete the intro walkthrough, "
                           "and verify your assigned territory and accounts are correct.",
            "order": 1,
        },
        {
            "id": "sal_002",
            "title": "Shadow two discovery calls",
            "description": "Coordinate with your manager to shadow two live discovery calls "
                           "in your first week. Take notes and debrief afterward.",
            "order": 2,
        },
        {
            "id": "sal_003",
            "title": "Review product positioning deck",
            "description": "Read the latest competitive positioning deck in SharePoint. "
                           "Confirm with your manager which version is current before reading.",
            "order": 3,
        },
        {
            "id": "sal_004",
            "title": "Complete sales methodology certification",
            "description": "Finish the MEDDIC certification course in the LMS. "
                           "Required before leading your first customer call independently.",
            "order": 4,
        },
    ],
    "marketing": [
        {
            "id": "mkt_001",
            "title": "Access brand asset library",
            "description": "Log in to the DAM (Digital Asset Management) system and confirm "
                           "access to the brand kit, logo files, and approved templates.",
            "order": 1,
        },
        {
            "id": "mkt_002",
            "title": "Review content calendar",
            "description": "Access the shared content calendar in SharePoint and introduce "
                           "yourself in the #content-team Slack channel.",
            "order": 2,
        },
        {
            "id": "mkt_003",
            "title": "Complete data privacy training",
            "description": "Finish the GDPR and data privacy module in the LMS. "
                           "Required for anyone handling campaign data or contact lists.",
            "order": 3,
        },
        {
            "id": "mkt_004",
            "title": "Attend campaign planning standup",
            "description": "Join the weekly campaign planning standup (Tuesdays, 9am PT). "
                           "Calendar invite sent by your manager.",
            "order": 4,
        },
    ],
    "hr": [
        {
            "id": "hr_001",
            "title": "Complete HRIS system access",
            "description": "Log in to Workday and verify your employee profile is complete "
                           "and accurate. Flag any discrepancies to IT immediately.",
            "order": 1,
        },
        {
            "id": "hr_002",
            "title": "Review HR policy documentation",
            "description": "Read the current employee handbook and HR policy library "
                           "in SharePoint. Confirm version is current with your manager.",
            "order": 2,
        },
        {
            "id": "hr_003",
            "title": "Shadow a benefits enrollment session",
            "description": "Sit in on an upcoming benefits Q&A session to understand "
                           "the enrollment process from the employee perspective.",
            "order": 3,
        },
        {
            "id": "hr_004",
            "title": "Complete employment law training",
            "description": "Finish the employment law fundamentals module in the LMS. "
                           "Required for all HR team members before handling employee relations cases.",
            "order": 4,
        },
    ],
}

# In-memory task completion store.
# Structure: { "department:task_id": True }
# Resets on server restart — acceptable for a PoC demo session.
_completion_store: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def error_response(code: str, message: str, status: int, details=None):
    """Return a structured JSON error response Copilot Studio can parse."""
    return jsonify({"error": {"code": code, "message": message, "details": details}}), status


def _build_task_list(department: str) -> list:
    """Return tasks for a department with live completion state applied."""
    raw = TASKS.get(department.lower(), [])
    result = []
    for task in raw:
        key = f"{department.lower()}:{task['id']}"
        result.append({**task, "completed": _completion_store.get(key, False)})
    return result


def _completion_percentage(tasks: list) -> int:
    if not tasks:
        return 0
    completed = sum(1 for t in tasks if t["completed"])
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
            # Fail open with a warning during local development only.
            # In production, App Service will always have API_KEY set.
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
# Global error handler — ensures Flask never returns HTML to Power Platform
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

    Returns a mock employee record for the given first name.
    Called by the Copilot Studio agent at conversation start to personalize
    the greeting and pre-populate department context.

    Path param:
        name (str): Employee first name. Case-insensitive.

    Returns 200 with employee record or 404 if name not found.
    On 404, the agent falls back to asking the user for their department manually.
    """
    employee = EMPLOYEES.get(name.lower())
    if not employee:
        return error_response(
            code="EMPLOYEE_NOT_FOUND",
            message=f"No employee record found for '{name}'. "
                    f"The agent will ask the user to confirm their department.",
            status=404,
        )
    return jsonify(employee), 200


@app.route("/onboarding/<string:department>", methods=["GET"])
@require_api_key
def get_onboarding_tasks(department: str):
    """
    GET /onboarding/<department>

    Returns the ordered onboarding task checklist for the given department,
    with live completion state applied from the in-memory store.
    Called by the Copilot Studio agent to begin the checklist conversation act.

    Path param:
        department (str): One of Engineering, Sales, Marketing, HR. Case-insensitive.

    Returns 200 with task list and progress summary, or 404 for unknown departments.
    """
    valid = list(TASKS.keys())
    if department.lower() not in valid:
        return error_response(
            code="DEPARTMENT_NOT_FOUND",
            message=f"Department '{department}' is not recognized. "
                    f"Valid values: {', '.join(d.title() for d in valid)}.",
            status=404,
        )

    tasks = _build_task_list(department)
    next_task = next((t for t in tasks if not t["completed"]), None)

    return jsonify({
        "department": department.title(),
        "tasks": tasks,
        "total_tasks": len(tasks),
        "completion_percentage": _completion_percentage(tasks),
        "next_task": next_task,
    }), 200


@app.route("/complete-task", methods=["POST"])
@require_api_key
def complete_task():
    """
    POST /complete-task

    Marks a task as complete and returns the updated task list with
    new completion percentage and the next incomplete task.
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

    dept_tasks = TASKS.get(department.lower())
    if dept_tasks is None:
        return error_response(
            code="DEPARTMENT_NOT_FOUND",
            message=f"Department '{department}' is not recognized.",
            status=404,
        )

    task_ids = [t["id"] for t in dept_tasks]
    if task_id not in task_ids:
        return error_response(
            code="TASK_NOT_FOUND",
            message=f"Task '{task_id}' not found in department '{department}'. "
                    f"Valid task IDs: {', '.join(task_ids)}.",
            status=404,
        )

    # Mark complete in the in-memory store
    store_key = f"{department.lower()}:{task_id}"
    _completion_store[store_key] = True

    # Build updated task list
    tasks = _build_task_list(department)
    next_task = next((t for t in tasks if not t["completed"]), None)
    pct = _completion_percentage(tasks)

    return jsonify({
        "task_id": task_id,
        "completed": True,
        "department": department.title(),
        "completion_percentage": pct,
        "remaining_tasks": sum(1 for t in tasks if not t["completed"]),
        "all_complete": pct == 100,
        "next_task": next_task,
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
