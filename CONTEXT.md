# Copilot Studio Onboarding Agent — Session Context

## What This Project Is
A Microsoft AI Workforce PoC built to demonstrate Cloud Solution Architect skills for job #200029159.
End-to-end stack: Flask API → Power Platform Custom Connector → Power Automate → Copilot Studio agent.
Lives at: `Projects/copilot-onboarding-agent/`

---

## Current Status
Phase 2 complete. All backend files written and syntax-verified.

### Done
- `app.py` — Flask API with 3 endpoints + health check, API key auth decorator, structured JSON error handling
- `swagger.json` — OpenAPI 2.0 spec ready for Power Platform import
- `requirements.txt` — Flask 3.1.0 + gunicorn 23.0.0
- `startup.txt` — Azure App Service start command (`gunicorn --bind=0.0.0.0:8000 app:app`)
- `IMPLEMENTATION_PLAN.md` — Full senior-engineer-level plan covering architecture, design decisions, auth, error handling, ROI, CI/CD

### Not Started
- GitHub repo (init and push)
- Azure App Service provisioning + deploy
- M365 tenant setup (Business Basic trial + Copilot Studio trial + Power Apps Developer Plan)
- Power Platform Custom Connector (Phase 3)
- Power Automate flow (Phase 4)
- Copilot Studio agent (Phase 5)
- README + screenshots (Phase 6)

---

## One Thing To Do Before Deploying
In `swagger.json`, replace `YOUR-APP-NAME.azurewebsites.net` in the `host` field with the actual Azure App Service URL after provisioning.

---

## API Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/employee/<name>` | Fetch mock employee record for agent greeting |
| GET | `/onboarding/<department>` | Fetch task checklist (Engineering, Sales, Marketing, HR) |
| POST | `/complete-task` | Mark task complete, return updated progress |
| GET | `/health` | Azure App Service health check, no auth required |

---

## Auth
- API key via `X-API-Key` header
- Flask decorator reads from `API_KEY` environment variable
- Set in Azure App Service → Configuration → Application Settings
- Decorator skips auth if `API_KEY` is not set (safe for local dev)

---

## Key Decisions Made
- OpenAPI 2.0 (not 3.0) — Power Platform custom connector requires it
- Hardcoded data — PoC, no database needed; swap to Azure SQL in production
- Plain Flask over flask-restx — avoids OpenAPI 3.0 auto-generation issue
- API key over Entra ID — right for PoC, Entra ID is the production path

---

## M365 Tenant Setup (Phase 1 — still needed)
Dev Program sandbox was blocked. Plan:
1. M365 Business Basic trial — microsoft.com/en-us/microsoft-365/business
2. Azure free account — azure.microsoft.com/free
3. Copilot Studio trial — copilotstudio.microsoft.com (sign in with tenant account)
4. Power Apps Developer Plan — make.powerapps.com (unlocks premium connectors)

---

## How To Resume This Session
Mount the `Projects/` folder, open a new conversation, and say:
"Read CONTEXT.md in copilot-onboarding-agent and pick up where we left off."
