# Changes needed in `src/api.py` — Flask version

Your backend runs Flask (not FastAPI). All code below uses Flask patterns.

---

## Priority 0: New `/api/analyze` endpoint (seamless proposal generation)

### How the pipeline works (important context)

There are two intermediate artifacts in the current `main.py` workflow:

| File | What it is | Role |
|------|-----------|------|
| `documents.csv` | Raw crawl + per-file AI classification | **Input** to the organizer. Columns: `file_name`, `file_path`, `size`, `last_modified`, `client`, `subcategory`, `keywords`, `summary`, `ai_suggested_folder`, `confidence` |
| `proposal.json` | Folder tree + move plan | **Output** of the organizer. This is what the React frontend displays. |

The pipeline is: **Crawl SharePoint → Classify each file (AI) → Organize into proposal**

The `/api/analyze` endpoint should run all three phases and return `proposal.json` directly.
The `documents.csv` becomes an internal intermediate — the user never needs to see it.

### Frontend behaviour (already implemented)

The frontend handles three paths automatically based on file type:
- **"Analyze & Generate" button** → calls `POST /api/analyze` → full pipeline, returns proposal
- **Upload `documents.csv`** → calls `POST /api/organize` (existing) → skips crawl+classify, re-runs organizer only
- **Upload `proposal.json`** → loads directly, no backend call needed

### The new endpoint

```python
@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    Full pipeline: crawl SharePoint → classify files → organize → return proposal.
    This combines what main.py --crawl, --classify, and --organize do separately.
    """
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)

    if not site_url:
        return jsonify({"detail": "No SharePoint site URL provided"}), 400

    # Phase 1: Crawl — get all files from SharePoint via Graph API
    parsed = site_url.rstrip("/").replace("https://", "")
    hostname, _, path = parsed.partition("/")
    graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{path}"
    site_resp = http_requests.get(graph_url, headers=headers)
    if site_resp.status_code != 200:
        return jsonify({"detail": "Could not connect to SharePoint site"}), site_resp.status_code
    site_id = site_resp.json()["id"]

    drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/children"
    raw_files = []
    _collect_files(drive_url, headers, raw_files)

    # Phase 2: Classify — run your existing per-file AI classification
    # This is what main.py --classify does; it adds ai_suggested_folder + confidence to each file
    # Your existing classify function takes the raw file list and returns enriched rows
    classified = classify_files(raw_files)   # ← your existing function

    # Phase 3: Organize — run your existing organizer on the enriched data
    # This is what main.py --organize does (same as /api/organize but without a CSV upload)
    # Your existing organizer function takes classified rows and returns the proposal dict
    proposal = build_proposal(classified)    # ← your existing function

    return jsonify(proposal)


def _collect_files(url, headers, files, depth=0, max_depth=10):
    """Recursively collect all files from a SharePoint drive folder."""
    if depth > max_depth:
        return
    resp = http_requests.get(url, headers=headers)
    if resp.status_code != 200:
        return
    items = resp.json().get("value", [])
    for item in items:
        if "file" in item:
            files.append({
                "name": item["name"],
                "path": item.get("parentReference", {}).get("path", ""),
                "size": item.get("size", 0),
                "lastModified": item.get("lastModifiedDateTime", ""),
                "webUrl": item.get("webUrl", ""),
                "id": item["id"],
            })
        elif "folder" in item:
            children_url = (
                f"https://graph.microsoft.com/v1.0/drives/"
                f"{item['parentReference']['driveId']}/items/{item['id']}/children"
            )
            _collect_files(children_url, headers, files, depth + 1, max_depth)
```

**Response format** (same as `/api/organize` already returns):
```json
{
  "clean_slate": {
    "folder_tree": { "Finance": { "2024": {} }, "HR": {} },
    "assignments": [
      {
        "file_name": "Budget 2024.xlsx",
        "current_path": "/Documents/old folder/Budget 2024.xlsx",
        "proposed_path": "/Finance/2024/Budget 2024.xlsx",
        "reason": "Financial document grouped by year",
        "confidence": 0.92
      }
    ]
  },
  "incremental": {
    "folder_tree": { ... },
    "assignments": [ ... ]
  }
}
```

> **Timing note:** This can take 30–120 seconds for large sites (crawl + AI classify).
> The frontend already shows "Scanning SharePoint & generating proposals…" during the wait.
> PythonAnywhere free tier has a 5-minute request timeout — if sites are very large,
> consider streaming progress updates via SSE (same pattern as `/api/execute`).

### Also update `/api/organize` to accept rows directly (optional)

Currently `/api/organize` reads a CSV file upload. If you want to also support the
case where `documents.csv` is uploaded from the frontend, make sure your route reads
`request.files["file"]` and parses it as CSV — which it likely already does.

---

## Priority 1: Fix CORS (this is why prod fails)

Find your existing `flask_cors` setup and add your Replit deployed domain:

```python
from flask_cors import CORS

CORS(app, origins=[
    "http://localhost:5173",
    "http://localhost:21535",
    "https://*.replit.dev",
    "https://replit-migration.replit.app",
])
```

Or if you're using `ALLOWED_ORIGINS` from your `.env`, add the Replit domain there:

```
ALLOWED_ORIGINS=https://replit-migration.replit.app
```

---

## Priority 2: Accept Bearer token + site URL from headers (OAuth support)

In Flask, headers come from `request.headers`. Add a helper function to extract
the auth context at the top of each route:

```python
import os
from flask import request, jsonify, abort

API_KEY = os.getenv("API_KEY", "")

def get_auth_context():
    """
    Extract auth info from request headers.
    Returns a dict with 'token' and 'site_url'.
    Aborts with 401 if the API key is missing or wrong.
    """
    api_key = request.headers.get("X-API-Key")
    if not API_KEY or api_key != API_KEY:
        abort(401, description="Invalid or missing API key")

    # Bearer token from Microsoft OAuth (optional — only present when user signed in)
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]

    # SharePoint site URL sent by the frontend
    site_url = request.headers.get("X-Site-URL") or os.getenv("SP_SITE_URL", "")

    return {"token": token, "site_url": site_url}
```

---

## Priority 3: Update Graph API calls to use delegated token

Replace wherever you currently call `msal_app.acquire_token_for_client()` and
use hardcoded env-var credentials with this helper:

```python
import msal
import requests as http_requests   # rename to avoid clash with flask's request

def get_graph_token(auth_ctx: dict) -> str:
    """
    Return an access token for Microsoft Graph.
    - Uses the user's delegated token when available (OAuth sign-in).
    - Falls back to service-account token (your existing MSAL setup).
    """
    if auth_ctx.get("token"):
        return auth_ctx["token"]   # delegated — use as-is

    # Service-account fallback (your existing approach)
    msal_app = msal.ConfidentialClientApplication(
        os.getenv("AZURE_CLIENT_ID"),
        authority=f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID')}",
        client_credential=os.getenv("AZURE_CLIENT_SECRET"),
    )
    result = msal_app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        abort(500, description="Could not acquire service token")
    return result["access_token"]


def graph_headers(auth_ctx: dict) -> dict:
    return {"Authorization": f"Bearer {get_graph_token(auth_ctx)}"}
```

---

## Priority 4: Update your existing route handlers

Add `auth_ctx = get_auth_context()` at the top of each route:

```python
@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)

    parsed = site_url.rstrip("/").replace("https://", "")
    hostname, _, path = parsed.partition("/")
    graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{path}"

    resp = http_requests.get(graph_url, headers=headers)
    if resp.status_code != 200:
        return jsonify({"detail": "Could not connect to SharePoint site"}), resp.status_code

    data = resp.json()
    return jsonify({"site_name": data.get("displayName", site_url), "site_id": data.get("id")})


@app.route("/api/organize", methods=["POST"])
def organize():
    auth_ctx = get_auth_context()
    file = request.files["file"]
    # ... rest of your existing organize logic


@app.route("/api/execute", methods=["POST"])
def execute():
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)
    # ... rest of your existing execute logic
```

---

## Recommended order

1. **Add `/api/analyze`** — this is the biggest UX improvement; users no longer need to run `main.py` manually
2. **Fix CORS** — update `ALLOWED_ORIGINS` to include `https://replit-migration.replit.app`
3. **Test connection** — click "Test Connection" in the deployed app
4. **Wire up delegated auth later** — once CORS + analyze work, apply the token/header changes for OAuth
