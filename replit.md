# SharePoint Reorganizer — Project Context

## What this project is

A React web app that replaces a Streamlit app. It guides users through a 4-step workflow:
1. **Authenticate** — Sign in with Microsoft (MSAL/Azure OAuth)
2. **Connect** — Enter a SharePoint site URL and verify connection via backend
3. **Propose** — Upload a CSV to generate AI-powered file reorganization proposals
4. **Review & Execute** — Approve proposed file moves and stream execution via SSE

The frontend (this Replit project) connects to a Flask backend hosted on PythonAnywhere.

---

## Architecture

### Frontend — `artifacts/sharepoint-reorganizer`
- **Framework**: React + Vite (`@workspace/sharepoint-reorganizer`)
- **Routing**: `wouter` (not react-router-dom); base path from `import.meta.env.BASE_URL`
- **Auth**: MSAL (`@azure/msal-browser` v5, `@azure/msal-react`) — popup login flow
- **State**: `MigrationContext` (stores `accessToken`, `msalUser`, `siteUrl`, proposals, approved moves)
- **API client**: `src/api/client.ts` — all calls forward `Authorization: Bearer <token>`, `X-Site-URL`, `X-API-Key` headers
- **Local storage**: `"sp-approved-moves"` (approved moves), `"sp-site-url"` (site URL)
- **Production URL**: `https://replit-migration.replit.app/`
- **Dev URL**: `https://fcee1e27-9e52-4447-ad30-11c0dae73037-00-1bk5gm0jhbomi.riker.replit.dev`

### Backend — PythonAnywhere (Flask)
- **Base URL**: `https://dylanholcomb.pythonanywhere.com`
- **Framework**: Flask (NOT FastAPI — do not use FastAPI patterns)
- **API key**: passed as `X-API-Key` header (secret: `VITE_API_KEY`)
- **CORS**: PythonAnywhere Flask must have Replit domains in `ALLOWED_ORIGINS` env var
- **SSE**: `/execute` endpoint streams file move results via Server-Sent Events
- **Backend guide**: `attached_assets/api_py_changes.md` (Flask-compatible changes documented here)

---

## Azure / MSAL Configuration

- **Azure App name**: SP Document Crawler
- **Client ID**: `a16dee1e-dafd-4334-8e4f-95212e9389b6`
- **Tenant ID**: `4b443fe5-100a-489e-b6bb-b6685b55cd96`
- **Authority**: `https://login.microsoftonline.com/4b443fe5-100a-489e-b6bb-b6685b55cd96` (single-tenant, their org only)
- **Redirect URI** (registered as SPA in Azure Portal):
  - Dev: `https://fcee1e27-9e52-4447-ad30-11c0dae73037-00-1bk5gm0jhbomi.riker.replit.dev/auth/redirect`
  - Prod: `https://replit-migration.replit.app/auth/redirect`
- **MSAL config file**: `src/lib/msalConfig.ts`
- **Auth redirect page**: `src/pages/AuthRedirect.tsx` — minimal spinner shown in popup while MSAL processes token

---

## Environment Secrets

| Secret | Purpose |
|--------|---------|
| `VITE_API_BASE_URL` | PythonAnywhere backend base URL |
| `VITE_API_KEY` | API key forwarded as `X-API-Key` header |

---

## Pages

| Route | Component | Purpose |
|-------|-----------|---------|
| `/` | `Home.tsx` | 3-step: Sign In → Connect SharePoint → Upload CSV & Propose |
| `/overview` | `Overview.tsx` | View generated proposals |
| `/review` | `ReviewMoves.tsx` | Approve/reject individual moves |
| `/execute` | `Execute.tsx` | Stream execution of approved moves via SSE |
| `/auth/redirect` | `AuthRedirect.tsx` | Dedicated MSAL popup redirect handler |

---

## Monorepo Structure

```text
artifacts/
  sharepoint-reorganizer/   # Main React app
  api-server/               # Express server (not used by this app — legacy template artifact)
  mockup-sandbox/           # Vite component preview server (canvas prototyping)
lib/                        # Shared libraries (api-spec, api-client-react, api-zod, db)
scripts/                    # Utility scripts
```

---

## Known Issues / In Progress

- **MSAL login popup spinning**: After updating redirect URI to `/auth/redirect`, the popup spins but may not close. Azure needs the new `/auth/redirect` URIs registered as SPA type. Still being debugged.

---

## Pending Tasks (Backlog)

1. **Fix MSAL login** — resolve the popup spinning issue so auth completes cleanly
2. **GitHub sync** — push codebase to GitHub and keep it up to date as work progresses
3. **In-app proposal generation** — allow end users to trigger the AI proposal generation directly from this UI instead of going to PythonAnywhere manually; requires a backend endpoint that accepts the SharePoint site + parameters and streams/returns proposals
4. **Docs/context refresh** — keep this replit.md current after significant changes

---

## Key Files

```text
artifacts/sharepoint-reorganizer/
  src/
    api/client.ts              # All API calls to PythonAnywhere backend
    context/MigrationContext.tsx # Global state (auth, site URL, proposals, approved moves)
    lib/msalConfig.ts          # MSAL/Azure auth configuration
    pages/Home.tsx             # Main entry — 3-step auth + connect + upload flow
    pages/AuthRedirect.tsx     # MSAL popup redirect handler
    pages/Overview.tsx         # Proposal review overview
    pages/ReviewMoves.tsx      # Per-move approval UI
    pages/Execute.tsx          # SSE-streamed execution
    components/layout/Shell.tsx # App shell with nav + sign-out
attached_assets/
  api_py_changes.md            # Flask-compatible backend changes guide for PythonAnywhere
```
