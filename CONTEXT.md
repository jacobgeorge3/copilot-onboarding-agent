# Copilot Studio Onboarding Agent — Session Context

## What This Project Is
A Microsoft AI Workforce solution built to demonstrate Cloud Solution Architect skills for job #200029159.
End-to-end stack: Flask API → Power Platform Custom Connector → Power Automate → Copilot Studio agent.
Lives at: `Projects/copilot-onboarding-agent/`

---

## Current Status
**All 6 phases complete as of Session 3 — Feb 27, 2026.**
Project is a working PoC. Next focus: iterative improvement toward a production-grade, business-deployable HR onboarding platform.

---

## What Was Completed

### Phase 1 — M365 Tenant Setup ✅
- M365 Business Basic trial activated
- Copilot Studio trial activated at copilotstudio.microsoft.com
- Power Apps Developer Plan activated at make.powerapps.com
- Tenant: jacobcsa.onmicrosoft.com

### Phase 2 — GitHub + Azure Deploy ✅
- GitHub repo: https://github.com/jacobgeorge3/copilot-onboarding-agent
- Azure App Service: **autohire** (Free F1, Linux, Python 3.12, Central US)
- Live URL: `https://autohire-g8gbfzh4cfa2bdh2.centralus-01.azurewebsites.net`
- CI/CD via GitHub Actions on push to main
- API_KEY set in Azure App Service environment variables

### Phase 3 — Power Platform Custom Connector ✅
- Connector: **Onboarding Agent API** in make.powerapps.com
- Auth: API Key / X-API-Key / Header
- All 4 actions imported: GetEmployee, GetOnboardingTasks, CompleteTask, HealthCheck

### Phase 4 — Power Automate Flow ✅
- Instant cloud flow: **Onboarding Task Notification**
- Calls GetOnboardingTasks (Engineering), sends result via Send an Email (V2)
- Connected to JacobGeorge@jacobcsa.onmicrosoft.com M365 Outlook

### Phase 5 — Copilot Studio Agent ✅
- Agent: **Onboarding Assistant** at copilotstudio.microsoft.com
- Model: GPT-4.1 (Default)
- All 4 API tools connected and enabled (triggered by agent)
- Full conversation tested: greeted Jacob by name, walked through all 4 Engineering tasks, confirmed completion
- Screenshot captured showing activity trace + connector tool call details + live chat

### Phase 6 — README + Screenshot ✅
- README.md written and pushed to repo root
- Includes architecture diagram, API reference, local dev setup, Azure deploy steps, Power Platform setup, and production evolution path
- Screenshot saved showing agent mid-conversation with connector action trace visible

---

## Key Credentials & URLs
| Thing | Value |
|---|---|
| GitHub repo | https://github.com/jacobgeorge3/copilot-onboarding-agent |
| Azure App Service | https://autohire-g8gbfzh4cfa2bdh2.centralus-01.azurewebsites.net |
| Power Apps | make.powerapps.com |
| Power Automate | make.powerautomate.com |
| Copilot Studio | copilotstudio.microsoft.com |
| M365 Tenant | jacobcsa.onmicrosoft.com |

---

## API Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/employee/<name>` | Fetch mock employee record for agent greeting |
| GET | `/onboarding/<department>` | Fetch task checklist (Engineering, Sales, Marketing, HR) |
| POST | `/complete-task` | Mark task complete, return updated progress |
| GET | `/health` | Azure App Service health check, no auth required |

---

## Known Limitations (PoC)
- Task completion state is in-memory — resets on Azure App Service restart
- Only one employee per first name (Jacob, hardcoded)
- No persistent user sessions — agent starts fresh each conversation
- API key auth only — no Entra ID / identity-aware requests
- No logging, no observability, no error alerting

---

## Roadmap: PoC → Production-Grade Platform

The goal is to evolve this from a resume project into a genuinely deployable HR onboarding platform that a business could plug into their M365 tenant and use on day one.

Work items are grouped by theme and roughly ordered by impact vs. effort. Tackle them in any order but prioritize **Data Persistence** and **Auth** first — everything else builds on those two.

---

### 1. Data Persistence (High Priority)
**The problem:** In-memory state means every server restart wipes all task progress. Not viable for real onboarding.

**What to do:**
- Provision an **Azure SQL Database** (Basic tier, ~$5/mo) or use **Azure Cosmos DB** (serverless, cheaper at low volume)
- Replace the hardcoded Python dicts in `app.py` with SQLAlchemy models: `Employee`, `Department`, `Task`, `OnboardingSession`, `TaskCompletion`
- `OnboardingSession` tracks one employee's onboarding run — links employee, department, start date, and completion status per task
- Task completions persist across restarts and are tied to a session ID, not just an in-memory dict
- Add a simple **admin seed script** (`seed.py`) to populate tasks for each department on first deploy
- Connection string goes in Azure App Service environment variables as `DATABASE_URL`

**Resume/demo upgrade:** The agent now remembers where a user left off. A returning employee can say "what's my next task?" and get the right answer.

---

### 2. Authentication & Identity (High Priority)
**The problem:** A shared API key is not suitable for multi-tenant or enterprise use. Anyone with the key can call the API as any employee.

**What to do:**
- Register the Flask API as an **app registration in Entra ID** (Azure AD)
- Update the custom connector security tab to use **OAuth 2.0 / Entra ID** — this is a connector config change, not a code rewrite
- Replace the API key decorator in `app.py` with **token validation** using `azure-identity` or `msal` — validate the `Authorization: Bearer <token>` header and extract the caller's identity (`oid`, `upn`) from the token claims
- Use the caller's identity to scope data access — an employee can only see their own onboarding session, not others'
- Add **role-based access**: employees see their own tasks; HR admins can view all sessions and mark tasks complete on behalf of others

**Resume/demo upgrade:** The agent is now identity-aware. It can greet the user without asking their name — it already knows who they are from their Entra ID token. No more "Hi, what's your name?" prompt.

---

### 3. Real Employee Data via Microsoft Graph (High Impact)
**The problem:** Hardcoded employee records in `app.py` mean the agent only knows about Jacob. A real deployment needs to pull from the actual directory.

**What to do:**
- Add a `GET /employee/<upn>` path that calls the **Microsoft Graph API** (`/v1.0/users/{upn}`) to fetch real employee data: display name, department, manager, job title, office location
- Register a Graph API permission (`User.Read`, `User.ReadBasic.All`) on the app registration
- Use a **managed identity** on the App Service to authenticate to Graph — no secrets to rotate
- Fall back to the hardcoded data if Graph is unavailable (graceful degradation)

**Resume/demo upgrade:** The agent works for any employee in the tenant, not just Jacob. This is the step that makes it a real product.

---

### 4. Observability & Monitoring (Medium Priority)
**The problem:** Currently there is zero visibility into whether the agent is working, failing, or being used.

**What to do:**
- Enable **Azure Application Insights** on the App Service (one-click in the portal, free tier available)
- Add structured logging in `app.py` using Python's `logging` module — log every API call with endpoint, department, task_id, response time, and status code
- Use `opencensus-ext-azure` or `azure-monitor-opentelemetry` to ship logs to App Insights automatically
- Create an **App Insights dashboard** with: request volume, error rate, average response time, most-called endpoints, and most-completed tasks by department
- Set up an **alert rule**: email or Teams notification if error rate exceeds 5% or if `/health` returns non-200

**Resume/demo upgrade:** You can pull up a live dashboard during an interview and show real usage data. This is the difference between "I built it" and "I operate it."

---

### 5. Task Management Admin UI (Medium Priority)
**The problem:** To add or edit onboarding tasks, you currently have to edit Python code and redeploy. HR teams can't self-serve.

**What to do:**
- Build a simple **Power Apps canvas app** as an HR admin interface — no backend changes needed, it calls the same custom connector
- Screens: task list by department (read), add task (POST), edit task description, reorder tasks, deactivate a task without deleting it
- Add a `POST /tasks` and `PUT /tasks/<id>` endpoint to `app.py` (auth-gated to HR admin role)
- Store tasks in the database from step 1 — the admin UI edits live data

**Resume/demo upgrade:** Demonstrates the full Power Platform picture — not just Copilot Studio and Power Automate, but Power Apps too. Three pillars in one project.

---

### 6. Richer Agent Conversations (Medium Priority)
**The problem:** The agent currently delivers tasks as a flat list. It doesn't handle edge cases, doesn't provide contextual help, and doesn't support partial sessions.

**What to do:**
- **Session resumption:** When a returning user opens the agent, check their OnboardingSession and jump straight to their next incomplete task instead of starting over
- **Contextual help per task:** Each task record should have an optional `help_url` field — the agent surfaces it when the user says "I'm stuck" or "how do I do this?"
- **Deadline awareness:** Add a `due_days` field to tasks — the agent proactively reminds users of upcoming deadlines ("You have 2 days left to complete security training")
- **Fallback / escalation topic:** If the agent can't answer something, it should offer to send an email to HR using a Power Automate flow — not just say "contact HR"
- **Completion summary:** When all tasks are done, the agent sends a summary email to the employee's manager via Graph API or Power Automate

---

### 7. Multi-Tenant & Deployment Packaging (Lower Priority, High Value for CSA Story)
**The problem:** Right now this is a single-tenant deploy. A real ISV or enterprise deployment needs to work across multiple tenants.

**What to do:**
- Parameterize all tenant-specific config (tenant ID, connector URL, API key) into environment variables
- Package the Power Platform components as a **managed solution** — exportable from make.powerapps.com and importable into any tenant in minutes
- Write a **deployment runbook** (add to the repo as `DEPLOY.md`): step-by-step instructions for standing up a new tenant instance, including app registration, connector import, and agent publish
- Add a **Bicep template** (`infra/main.bicep`) that provisions the App Service, Application Insights, SQL Database, and Key Vault in one `az deployment` command

**Resume/demo upgrade:** You can now say "this solution can be deployed to a new M365 tenant in under an hour." That is a real CSA deliverable.

---

### 8. Security Hardening (Do Before Any Real Data)
**What to do:**
- Move the API key (and later, all secrets) to **Azure Key Vault** — App Service reads secrets via managed identity, nothing in environment variables or code
- Enable **HTTPS-only** on the App Service (already default, but verify)
- Add **CORS policy** to Flask — only allow requests from your Power Platform tenant's connector host
- Add **rate limiting** to the API using `flask-limiter` — prevent abuse and runaway Power Automate flows
- Run **Microsoft Defender for Cloud** on the App Service — free tier gives you a security score and actionable recommendations
- Add **input validation** to all endpoints using `marshmallow` or `pydantic` — right now malformed requests can cause unhandled exceptions

---

## How To Resume Next Session
Mount the `Projects/` folder, open a new conversation, and say:
"Read CONTEXT.md in copilot-onboarding-agent and pick up where we left off."

Suggested first task next session: **Data Persistence** — provision Azure SQL and replace the in-memory dicts. This unblocks everything else on the roadmap.
