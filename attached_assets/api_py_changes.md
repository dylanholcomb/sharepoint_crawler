# Changes needed in `src/api.py` — Flask version

Your backend runs Flask (not FastAPI). All code below uses Flask patterns.

---

## Priority 0: New `/api/analyze` endpoint (seamless proposal generation)

This is the key endpoint that replaces the manual `main.py --analyze` + CSV upload flow.
The frontend calls this when the user clicks "Analyze & Generate Proposal".

It should:
1. Use the SharePoint site URL from the `X-Site-URL` header
2. Crawl all files in the site's default document library via Graph API
3. Run the same AI analysis that `main.py --analyze` currently does
4. Return the proposal JSON in the same format as `/api/organize`

```python
@app.route("/api/analyze", methods=["POST"])
def analyze():
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)

    if not site_url:
        return jsonify({"detail": "No SharePoint site URL provided"}), 400

    # 1. Get site ID from the site URL
    parsed = site_url.rstrip("/").replace("https://", "")
    hostname, _, path = parsed.partition("/")
    graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{path}"
    site_resp = http_requests.get(graph_url, headers=headers)
    if site_resp.status_code != 200:
        return jsonify({"detail": "Could not connect to SharePoint site"}), site_resp.status_code
    site_id = site_resp.json()["id"]

    # 2. List all files in the default drive (recursive)
    #    This is equivalent to what main.py --analyze does when crawling
    drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/children"
    files = []
    _collect_files(drive_url, headers, files)  # implement recursion as needed

    # 3. Run your existing AI analysis on the file list
    #    (same logic as what main.py --analyze does before writing the CSV)
    proposal = run_ai_analysis(files, site_url)  # your existing function

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
            children_url = item.get("@microsoft.graph.downloadUrl") or \
                f"https://graph.microsoft.com/v1.0/drives/{item['parentReference']['driveId']}/items/{item['id']}/children"
            _collect_files(children_url, headers, files, depth + 1, max_depth)
```

**Response format** (same as `/api/organize` already returns):
```json
{
  "clean_slate": {
    "folder_tree": { ... },
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

> **Note:** This can take 30–120 seconds for large sites. Consider adding a loading
> message on the frontend (already done — the button shows "Scanning SharePoint…").
> If PythonAnywhere times out on long requests, consider streaming progress via SSE
> (same pattern as `/api/execute`).

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
