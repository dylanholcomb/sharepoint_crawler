# Changes needed in `src/api.py` — Flask version

Your backend runs Flask (not FastAPI). All code below uses Flask patterns.

---

## Priority 1: Fix CORS (this is why prod fails)

Find your existing `flask_cors` setup and add your Replit deployed domain:

```python
from flask_cors import CORS

CORS(app, origins=[
    "http://localhost:5173",
    "http://localhost:21535",
    "https://*.replit.dev",
    "https://your-app-slug.replit.app",   # ← replace with your actual deployed domain
])
```

Or if you're using `ALLOWED_ORIGINS` from your `.env`, add the Replit domain there:

```
ALLOWED_ORIGINS=https://your-app-slug.replit.app
```

> This is almost certainly the entire reason "failed to fetch" happens in production
> but not in dev.

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

## Priority 4: Update your route handlers

Add `auth_ctx = get_auth_context()` at the top of each route, then pass
`graph_headers(auth_ctx)` and `auth_ctx["site_url"]` to your Graph API calls:

```python
@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)

    # Convert site URL to Graph API format:
    # https://org.sharepoint.com/sites/MySite
    # → https://graph.microsoft.com/v1.0/sites/org.sharepoint.com:/sites/MySite
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
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)
    file = request.files["file"]
    # ... rest of your existing organize logic,
    # replacing hardcoded SP_SITE_URL / token with site_url / headers


@app.route("/api/execute", methods=["POST"])
def execute():
    auth_ctx = get_auth_context()
    site_url = auth_ctx["site_url"]
    headers = graph_headers(auth_ctx)
    # ... rest of your existing execute logic
```

---

## Azure App Registration (only needed for full OAuth multi-tenant sign-in)

1. **Authentication tab** — add redirect URIs:
   - `https://your-app-slug.replit.app`
   - `http://localhost:21535`
   - Set to **"Multi-tenant"**
2. **API permissions** — add these as **Delegated** (not Application):
   - `User.Read`
   - `Sites.Read.All`
   - `Files.ReadWrite.All`
   - Click **"Grant admin consent"**

> This step is only needed if you want end-users signing in with their own
> Microsoft accounts. Your service-account approach still works fine for an
> admin tool — you can skip this for now and come back to it.

---

## Recommended order

1. **Fix CORS first** — update `ALLOWED_ORIGINS` in your `.env` on PythonAnywhere
   and reload the web app. This alone should fix the prod "failed to fetch" error.
2. **Test** — click "Test Connection" in the deployed app. It should reach your backend now.
3. **Add delegated auth later** — once CORS is working, apply the token/header
   changes above to enable real multi-tenant OAuth login.
