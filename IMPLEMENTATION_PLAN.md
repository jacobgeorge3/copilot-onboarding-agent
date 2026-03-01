# Copilot Studio Customer Onboarding Agent — Implementation Plan

**Author:** Jacob George
**Role Target:** Microsoft Cloud Solution Architect – AI Business Solutions (Job #200029159)
**Last Updated:** March 2026

---

## Project Overview

This project demonstrates an end-to-end Microsoft AI Workforce solution: a Copilot Studio agent that guides new employees through a structured onboarding workflow, backed by a Python Flask API, automated via Power Automate, and deployed on Azure App Service. It is designed as a PoC that mirrors the integration patterns a Cloud Solution Architect would design and deploy for enterprise customers using Microsoft's AI Business Solutions stack.

---

## Architecture

### Level 1 — This Build (PoC → Persistent PoC)

```
Copilot Studio Agent
      │
      ▼
Power Platform Custom Connector
      │
      ▼
Flask API on Azure App Service   ←── SQLAlchemy ORM (SQLite local / Azure SQL prod)
      │                                   models.py, database.py, seed.py
      ▼
Power Automate Flow  ──►  M365 Outlook (welcome email)
                    └───►  Microsoft Planner (task creation)
```

**Data Persistence (completed March 2026):**
Task completion state and employee/task records are now stored in a database via
SQLAlchemy. Locally this is a zero-config SQLite file. In Azure it connects to
Azure SQL via the `DATABASE_URL` environment variable. All API contracts are
identical — the existing Copilot Studio connector requires no changes.

### Level 2 — Production Single Tenant

```
Copilot Studio Agent
      │
      ▼
Power Platform Custom Connector
      │
      ▼
Azure API Management (APIM)      ←── Auth, rate limiting, versioning
      │
      ▼
Flask API on Azure App Service   ←── Azure SQL Database
```

### Level 3 — Enterprise / Multi-Tenant

```
Copilot Studio Agent
      │
      ▼
Power Platform Custom Connector
      │
      ▼
Azure API Management (APIM)
      │
      ▼
Azure Functions (event-driven, scales to zero)
      │
      ├──► Dataverse  (if customer is on D365 HR)
      ├──► Azure SQL  (standalone employee/task store)
      └──► Microsoft Graph API  (Teams, SharePoint, Azure AD provisioning)
```

**When to recommend each level:** Level 1 for internal pilots and demos. Level 2 when a single tenant goes to production and needs credential management. Level 3 when the customer is already in the D365/Power Platform ecosystem or needs cross-tenant deployment.

---

## Design Decisions

### Data Layer — SQLAlchemy with SQLite / Azure SQL

Employee records, tasks, and completion state are stored via SQLAlchemy ORM in
four tables: `departments`, `tasks`, `employees`, `task_completions`. The
`TaskCompletion` model replaces the former `_completion_store` in-memory dict
and persists across Azure App Service restarts.

**Local dev (default):** SQLite file (`onboarding_dev.db`) — zero config, no
extra setup, created automatically on first startup.

**Production (Azure SQL):** Set `DATABASE_URL` in App Service Application
Settings. The app detects the URL and switches drivers automatically.

**Initial data:** Run `python seed.py` once after provisioning to populate
all departments, tasks, and employees. Safe to re-run (idempotent).

**Next phase (Entra ID):** When identity-aware auth is added, extend
`TaskCompletion` with an `employee_id` FK and add an `OnboardingSession` model
to track per-user onboarding runs. See the Entra ID section below.

### Plain Flask over flask-restx

`flask-restx` auto-generates OpenAPI specs but targets OpenAPI 3.0. Power Platform's custom connector importer was built against OpenAPI 2.0 (Swagger) and has silent, difficult-to-debug failures with 3.0 specs. Plain Flask with a hand-written `swagger.json` avoids this entirely and gives explicit control over the parameter descriptions that Copilot Studio uses to reason about when to call each action.

### OpenAPI 2.0 over 3.0

Power Platform requires a machine-readable API description to generate the custom connector — you cannot configure it manually without one. OpenAPI 2.0 is the target format because it is what Power Platform reliably ingests. Key fields beyond endpoint definitions: `description` on each operation and parameter, `operationId` (used as the action name in Copilot Studio), and `produces: ["application/json"]` to prevent Power Platform from attempting XML parsing.

### Authentication: API Key (PoC) → Entra ID (Production)

**For this build**, authentication uses a custom header API key (`X-API-Key`). This is the right choice for a PoC because Power Platform has native support for API key auth in custom connector settings — no OAuth dance, no token management, and the connector handles header injection automatically once configured.

Implementation: Flask reads `os.environ["API_KEY"]` on startup and validates it on every request via a decorator. The key is stored as an Azure App Service Application Setting (environment variable), never in source code.

**Path to Entra ID:** When moving to production, register the API as an app in Entra ID (Azure AD), configure the custom connector to use OAuth 2.0 with Entra as the identity provider, and replace the API key decorator with token validation using `msal` or `azure-identity`. Power Platform has a built-in Entra ID auth option in the custom connector security tab — this is a configuration change in the connector, not a rewrite of the API.

```
PoC:         Custom Connector → X-API-Key header → Flask decorator
Production:  Custom Connector → Entra ID OAuth 2.0 → Token validation middleware
```

### Error Handling: Structured JSON for Power Platform Compatibility

Power Platform and Copilot Studio behave predictably only when error responses are consistent, machine-readable JSON. Flask's default error responses are HTML — this will silently break the agent's flow with no useful message surfaced to the user.

**All error responses follow this schema:**

```json
{
  "error": {
    "code": "DEPARTMENT_NOT_FOUND",
    "message": "Department 'xyz' is not recognized. Valid values: Engineering, Sales, Marketing, HR.",
    "details": null
  }
}
```

HTTP status codes used:
- `400` — bad request (missing required field, invalid type)
- `404` — resource not found (unknown department, unknown employee)
- `500` — unhandled server error (caught by a global error handler)

In Copilot Studio, each action that calls the connector checks for error responses and routes to a dedicated fallback topic ("I wasn't able to retrieve your information — let me connect you with HR directly."). This is configured at the topic level, not in the API — the API's job is to return consistent, parseable errors; the agent's job is to decide what to say about them.

---

## Business Value & ROI

When presenting this to a hiring manager or customer, frame the architecture around outcomes, not technology.

**The problem it solves:** Manual onboarding is inconsistent, time-consuming for HR, and opaque to the new hire. Steps get missed. HR fields the same questions repeatedly. New hires reach full productivity later than they should.

**Measurable improvements this architecture drives:**

| Metric | Before | With This Solution |
|---|---|---|
| HR hours per onboarding | 4–6 hours (emails, follow-ups, reminders) | <1 hour (exception handling only) |
| Task completion rate | ~70% (manual tracking) | ~100% (agent-enforced checklist) |
| Time to first productive day | Varies by manager | Consistent across all departments |
| HR escalation tickets | High (repetitive questions) | Reduced by self-service agent |
| Onboarding data visibility | Spreadsheets / email | Real-time completion dashboard (via Dataverse/Power BI) |

**The ROI pitch in one sentence:** "This solution replaces 4–6 hours of HR coordination per hire with a consistent, auditable, AI-driven workflow — at scale, that's hundreds of hours recovered annually per thousand employees, with measurably higher completion rates and faster time-to-productivity."

---

## File Structure

```
copilot-onboarding-agent/
├── app.py                          # Flask API server
├── swagger.json                    # OpenAPI 2.0 spec for Power Platform custom connector
├── requirements.txt                # Python dependencies
├── startup.txt                     # Azure App Service start command
└── .github/
    └── workflows/
        └── deploy.yml              # GitHub Actions CI/CD to Azure App Service
```

---

## app.py — API Reference

The Flask application exposes three endpoints. All responses are `application/json`. All error responses follow the structured schema defined in the Design Decisions section.

### `GET /onboarding/<department>`

**Purpose:** Returns the ordered onboarding task checklist for a given department.
**Called by:** Copilot Studio agent at the start of the checklist conversation act.
**Path parameter:** `department` — one of `Engineering`, `Sales`, `Marketing`, `HR` (case-insensitive).

**Success response `200`:**
```json
{
  "department": "Engineering",
  "tasks": [
    {
      "id": "eng_001",
      "title": "Set up dev environment",
      "description": "Install required tools: VS Code, Docker, Git, and clone the team repo.",
      "completed": false,
      "order": 1
    }
  ],
  "total_tasks": 4,
  "completion_percentage": 0
}
```

**Error response `404`:** Department not found.

---

### `GET /employee/<name>`

**Purpose:** Returns a mock employee record for personalized agent greeting.
**Called by:** Copilot Studio agent immediately after the user provides their name.
**Path parameter:** `name` — employee first name (case-insensitive lookup).

**Success response `200`:**
```json
{
  "name": "Jacob",
  "full_name": "Jacob George",
  "department": "Engineering",
  "manager": "Sarah Chen",
  "team": "Platform Infrastructure",
  "start_date": "2026-03-01",
  "office": "Remote"
}
```

**Error response `404`:** Employee not found — agent falls back to asking the user to confirm their department manually.

---

### `POST /complete-task`

**Purpose:** Marks a task as complete and returns updated progress.
**Called by:** Copilot Studio agent when the user confirms a task is done.

**Request body:**
```json
{
  "task_id": "eng_001",
  "department": "Engineering"
}
```

**Success response `200`:**
```json
{
  "task_id": "eng_001",
  "completed": true,
  "department": "Engineering",
  "completion_percentage": 25,
  "remaining_tasks": 3,
  "next_task": {
    "id": "eng_002",
    "title": "Complete security training",
    "description": "Finish the mandatory security awareness module in the LMS."
  }
}
```

**Error responses:** `400` missing fields, `404` task not found.

---

## swagger.json — Key Fields

Beyond listing endpoints, the following fields are critical for Power Platform:

- **`operationId`** — becomes the action name in Copilot Studio. Use readable names: `GetOnboardingTasks`, `GetEmployee`, `CompleteTask`.
- **`description` on each operation** — Copilot Studio reads this to decide when to invoke the action. Be explicit: *"Retrieves the onboarding task checklist for a new employee based on their department."*
- **`description` on each parameter** — Also read by the agent. *"The employee's department. Valid values: Engineering, Sales, Marketing, HR."*
- **`produces: ["application/json"]`** — Required. Without this, Power Platform may attempt XML parsing.
- **`securityDefinitions`** — Defines the API key header. Power Platform reads this to auto-configure the connector's auth settings.

---

## Deployment

### Provision Azure SQL Database (for production persistence)

1. In the Azure Portal, create a new **Azure SQL Database** resource.
   - Subscription: your existing sub
   - Resource group: same as the App Service (e.g. `autohire-rg`)
   - Database name: `onboarding-db`
   - Server: create new → `autohire-sql.database.windows.net`, SQL auth, set admin user/password
   - Compute + storage: **Basic** tier (~$5/month) is sufficient for a demo
2. Under the SQL Server → **Networking**, add a firewall rule to allow Azure services access
   (toggle: "Allow Azure services and resources to access this server" → On).
3. Copy the ADO.NET connection string from the portal and reformat it for SQLAlchemy:
   ```
   mssql+pyodbc://<user>:<password>@autohire-sql.database.windows.net:1433/onboarding-db
   ?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
   ```
4. In Azure App Service → **Configuration → Application Settings**, add:
   - Name: `DATABASE_URL`
   - Value: the connection string above
5. Redeploy (push to `main` triggers GitHub Actions CI/CD).
6. In Azure App Service → **SSH console** (or Kudu), run once:
   ```bash
   python seed.py
   ```
   This creates all tables and inserts the initial departments, tasks, and employees.

### Manual — Azure App Service (Do This First)

1. Create a free Azure account at [azure.microsoft.com/free](https://azure.microsoft.com/free)
2. In the Azure Portal, create a new **App Service** resource (runtime: Python 3.11, tier: Free F1)
3. In App Service → **Configuration → Application Settings**, add `API_KEY` with your chosen key value
4. Deploy via VS Code Azure extension or `az webapp up --name <your-app-name>`
5. Confirm the API is live: `https://<your-app-name>.azurewebsites.net/employee/jacob`

`startup.txt` contains:
```
gunicorn --bind=0.0.0.0:8000 app:app
```

### Automated — GitHub Actions CI/CD

Once manual deployment is confirmed working, add the following workflow to auto-deploy on every push to `main`.

**Setup:** In Azure Portal → App Service → **Deployment Center**, download the publish profile. In GitHub → Settings → Secrets, add it as `AZURE_WEBAPP_PUBLISH_PROFILE`.

`.github/workflows/deploy.yml`:
```yaml
name: Deploy to Azure App Service

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Deploy to Azure App Service
        uses: azure/webapps-deploy@v3
        with:
          app-name: '<your-app-name>'
          publish-profile: ${{ secrets.AZURE_WEBAPP_PUBLISH_PROFILE }}
          package: .
```

Every push to `main` triggers a deploy. This gives you a working CI/CD story to mention in interviews — "changes to the API are tested and deployed automatically via GitHub Actions."

---

## Evolution Path (Interview Reference)

| Concern | PoC Answer | Production Answer |
|---|---|---|
| Data persistence | ~~Hardcoded dict~~ **SQLAlchemy (SQLite/Azure SQL)** ✅ | Dataverse (D365 customers) |
| Authentication | API key header | Entra ID OAuth 2.0 |
| Scale | Always-on App Service | Azure Functions (consumption plan) |
| API governance | Direct connector → API | APIM in front of all backends |
| M365 integration | Power Automate flow | Microsoft Graph API in backend |
| Observability | None | Azure Monitor + Application Insights |
