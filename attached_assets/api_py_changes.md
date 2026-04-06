# Changes needed in `src/api.py` — Multi-tenant OAuth support

These are the exact modifications to make your FastAPI backend accept delegated
Microsoft OAuth tokens from the React frontend instead of (or alongside) the
hardcoded service-account credentials.

---

## 1. Add new imports (top of file)

```python
from fastapi import Header, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import httpx  # if not already installed: pip install httpx
```

---

## 2. Update CORS origins

Find your existing `CORSMiddleware` setup (or add it if missing) and add your
Replit app domain to the allowed origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",                      # local dev
        "http://localhost:21535",                     # Replit dev port
        "https://*.replit.dev",                       # Replit preview domains
        "https://your-app-slug.replit.app",           # ← replace with your actual .replit.app domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

> **Tip:** Your deployed Replit domain is shown in the browser address bar when
> you click "Open in new tab" on the published app.

---

## 3. Add an auth dependency

This replaces the simple API key check and also captures the user's Bearer token
and site URL from the request headers.

```python
import os

API_KEY = os.getenv("API_KEY", "")  # already in your .env


class AuthContext:
    def __init__(self, token: Optional[str], site_url: Optional[str]):
        self.token = token
        self.site_url = site_url


async def require_auth(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    x_site_url: Optional[str] = Header(None, alias="X-Site-URL"),
) -> AuthContext:
    # Validate the app-level API key (keeps random callers out)
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # Extract Bearer token if the frontend sent one
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]

    return AuthContext(token=token, site_url=x_site_url)
```

---

## 4. Update your Graph API helper to use the delegated token

When `auth.token` is present, use it directly in the Authorization header for
all Microsoft Graph calls. Fall back to your service-account credentials only
when no token is provided (useful for CLI / testing).

```python
def get_graph_headers(auth: AuthContext) -> dict:
    """
    Return Authorization headers for Microsoft Graph API calls.

    - If the user signed in via OAuth on the frontend, use their delegated token.
    - Otherwise fall back to the service-account token from MSAL client-credentials.
    """
    if auth.token:
        # Delegated flow — use the frontend's OAuth token directly
        return {"Authorization": f"Bearer {auth.token}"}
    else:
        # Service-account fallback (your existing MSAL logic)
        from msal import ConfidentialClientApplication
        msal_app = ConfidentialClientApplication(
            os.getenv("AZURE_CLIENT_ID"),
            authority=f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID')}",
            client_credential=os.getenv("AZURE_CLIENT_SECRET"),
        )
        result = msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise HTTPException(status_code=500, detail="Could not acquire service token")
        return {"Authorization": f"Bearer {result['access_token']}"}


def get_site_url(auth: AuthContext) -> str:
    """Return the SharePoint site URL — from the request header or .env fallback."""
    return auth.site_url or os.getenv("SP_SITE_URL", "")
```

---

## 5. Update your endpoint signatures

Add `auth: AuthContext = Depends(require_auth)` to each endpoint and replace
hardcoded site-URL / token logic with the helpers above.

### `POST /api/test-connection`

```python
@app.post("/api/test-connection")
async def test_connection(auth: AuthContext = Depends(require_auth)):
    site_url = get_site_url(auth)
    headers = get_graph_headers(auth)

    # Example: call Graph to verify the site exists
    # Extract hostname and site path from site_url
    # e.g. https://org.sharepoint.com/sites/MySite
    async with httpx.AsyncClient() as client:
        # Convert SharePoint site URL → Graph API site ID endpoint
        # https://graph.microsoft.com/v1.0/sites/{hostname}:/{site-path}
        parsed = site_url.rstrip("/").replace("https://", "")
        hostname, _, path = parsed.partition("/")
        graph_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{path}"
        resp = await client.get(graph_url, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Could not connect to SharePoint site")

    data = resp.json()
    return {"site_name": data.get("displayName", site_url), "site_id": data.get("id")}
```

### `POST /api/organize` and `POST /api/execute`

Same pattern — add `auth: AuthContext = Depends(require_auth)` and pass
`get_graph_headers(auth)` and `get_site_url(auth)` to wherever your existing
code currently uses hardcoded credentials or `SP_SITE_URL`.

```python
@app.post("/api/organize")
async def organize(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_auth),
):
    site_url = get_site_url(auth)
    headers = get_graph_headers(auth)
    # ... rest of your existing organize logic, but use site_url and headers
    # instead of the hardcoded env vars / MSAL client
```

---

## 6. Azure App Registration changes (one-time, in Azure Portal)

1. Go to **Azure Active Directory → App registrations → your app**
2. **Authentication tab:**
   - Add redirect URI: `https://your-app-slug.replit.app` (your deployed URL)
   - Also add: `http://localhost:21535` for dev testing
   - Enable **"Accounts in any organizational directory (Multi-tenant)"**
3. **API permissions tab:**
   - Ensure these **Delegated** permissions are added (not Application):
     - `User.Read`
     - `Sites.Read.All`
     - `Files.ReadWrite.All`
   - Click **"Grant admin consent"** for your tenant

> **Application vs Delegated permissions:** Your existing setup likely uses
> Application permissions (service account). For OAuth login, you need the same
> permissions as **Delegated** so they work with user tokens. You can keep both.

---

## Summary of what happens in the flow

```
User clicks "Sign in with Microsoft"
    → MSAL popup (frontend)
    → User authenticates with their Microsoft 365 account
    → Frontend gets access_token with Sites.Read.All + Files.ReadWrite.All scopes
    → Frontend sends: Authorization: Bearer <token>  +  X-Site-URL: https://...

Backend receives request
    → Validates X-API-Key (app-level gate)
    → Extracts Bearer token + site URL
    → Uses token directly in Microsoft Graph API calls
    → Graph API enforces the user's own permissions — they can only access
       SharePoint sites they already have access to in Microsoft 365
```
