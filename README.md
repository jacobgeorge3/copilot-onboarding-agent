# Copilot Studio Customer Onboarding Agent

A proof-of-concept Microsoft AI Workforce solution demonstrating the Copilot + Power Platform integration pattern. A Copilot Studio agent guides new employees through a structured onboarding workflow, backed by a Python Flask API deployed on Azure App Service and automated via Power Automate.

Built as a portfolio project targeting the Microsoft Cloud Solution Architect – AI Business Solutions role.

---

## Architecture

```
Copilot Studio Agent
        │
        ▼
Power Platform Custom Connector ◄── Power Automate Flow ──► M365 Outlook
        │                                (task notification email)
        ▼
Flask API on Azure App Service
(Python 3.12, Free F1, Central US)
        └── In-memory data (resets on restart → Azure SQL in production)
```

**Data flow:**
1. User opens the Copilot Studio agent and provides their name
2. Agent calls `GetEmployee` via the custom connector to fetch their record
3. Agent calls `GetOnboardingTasks` to retrieve the department checklist
4. As the user completes each step, the agent calls `CompleteTask` and reports progress
5. Separately, a Power Automate flow calls the same connector to send a task notification email via M365 Outlook

---

## What It Does

The agent walks a new employee through their onboarding checklist in a conversational interface:

- Greets the user by name and identifies their department
- Presents tasks one at a time with detailed instructions
- Tracks completion percentage in real time via API calls
- Surfaces manager name and team context from the employee record
- Offers to escalate to HR if it can't help

Departments supported: Engineering, Sales, Marketing, HR.

---

## Live Demo

**API base URL:** `https://autohire-g8gbfzh4cfa2bdh2.centralus-01.azurewebsites.net`

Health check (no auth required):
```
GET /health
→ {"status": "ok"}
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/employee/<name>` | Fetch employee record by first name |
| GET | `/onboarding/<department>` | Fetch task checklist for a department |
| POST | `/complete-task` | Mark a task complete, return updated progress |
| GET | `/health` | Health check — no auth required |

All responses are `application/json`. All errors follow a structured schema:

```json
{
  "error": {
    "code": "DEPARTMENT_NOT_FOUND",
    "message": "Department 'xyz' is not recognized. Valid values: Engineering, Sales, Marketing, HR.",
    "details": null
  }
}
```

---

## Authentication

Requests are authenticated via an `X-API-Key` header. The Power Platform custom connector injects this automatically once configured.

The Flask app reads the key from the `API_KEY` environment variable. If the variable is not set (local dev), auth is skipped.

**Production path:** Replace API key with Entra ID OAuth 2.0 — the custom connector has a native Entra auth option that requires no API code changes, only connector reconfiguration.

---

## Running Locally

```bash
# Clone the repo
git clone https://github.com/jacobgeorge3/copilot-onboarding-agent
cd copilot-onboarding-agent

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the development server
flask run
```

The API will be available at `http://localhost:5000`.

Auth is skipped locally if `API_KEY` is not set. To test with auth:

```bash
export API_KEY=your-key-here
flask run
```

---

## Deploying to Azure

### First Deploy (Manual)

1. Create an Azure App Service (Python 3.12, Linux, Free F1)
2. In App Service → **Settings → Environment variables**, add `API_KEY`
3. Deploy:

```bash
az webapp up --name <your-app-name> --runtime "PYTHON:3.12"
```

4. Confirm the API is live:

```
GET https://<your-app-name>.azurewebsites.net/health
```

### CI/CD via GitHub Actions

The repo includes a GitHub Actions workflow that auto-deploys on every push to `main`.

**Setup:**
1. In Azure Portal → App Service → **Deployment Center**, download the publish profile
2. In GitHub → **Settings → Secrets**, add it as `AZURE_WEBAPP_PUBLISH_PROFILE`
3. Push to `main` — the workflow handles the rest

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | No (skipped in dev) | API key validated on every request via `X-API-Key` header |

---

## Power Platform Setup

### Custom Connector

1. Go to [make.powerapps.com](https://make.powerapps.com) → **Custom connectors → New connector → Import from OpenAPI**
2. Upload `swagger.json`
3. In the **Security** tab, confirm API Key / Header / `X-API-Key` is set
4. Enter your API key and save

### Power Automate Flow

A simple instant cloud flow calls `GetOnboardingTasks` and sends a task notification email via M365 Outlook. Trigger it manually from [make.powerautomate.com](https://make.powerautomate.com).

### Copilot Studio Agent

1. Go to [copilotstudio.microsoft.com](https://copilotstudio.microsoft.com)
2. Create a new agent — **Onboarding Assistant**
3. Under **Tools**, add all 4 actions from the **Onboarding Agent API** connector
4. The agent uses the instructions and tool descriptions to reason about when to call each action — no manual topic wiring required
5. Test in the built-in chat panel, then **Publish**

---

## Project Structure

```
copilot-onboarding-agent/
├── app.py              # Flask API — endpoints, hardcoded data, auth decorator
├── swagger.json        # OpenAPI 2.0 spec — consumed by Power Platform custom connector
├── requirements.txt    # Flask + Gunicorn
├── startup.txt         # Azure App Service start command (gunicorn)
└── .github/
    └── workflows/
        └── main_autohire.yml   # GitHub Actions CI/CD to Azure App Service
```

---

## Production Evolution Path

| Concern | This PoC | Production |
|---------|----------|------------|
| Data persistence | In-memory dict | Azure SQL / Dataverse |
| Authentication | API key header | Entra ID OAuth 2.0 |
| Scale | Always-on App Service | Azure Functions (consumption plan) |
| API governance | Direct connector → API | Azure API Management |
| M365 integration | Power Automate flow | Microsoft Graph API |
| Observability | None | Azure Monitor + Application Insights |

---

## Author

**Jacob George** — [jacobgeorge3.github.io](https://jacobgeorge3.github.io/)
