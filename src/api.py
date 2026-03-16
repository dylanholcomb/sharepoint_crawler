"""
FastAPI backend for the SharePoint Reorganization tool.

Exposes the crawler, analyzer, organizer, and migration executor as a REST
API so that a separate frontend (e.g. React on Replit) can drive the full
workflow without running Python locally.

Deployment target: PythonAnywhere (or any WSGI/ASGI host).

Endpoints
---------
GET  /health                       – liveness probe
POST /api/test-connection          – verify Azure credentials
POST /api/organize                 – run Phase 3 organizer on an uploaded CSV
POST /api/execute                  – execute approved moves (streaming SSE)

Authentication
--------------
All /api/* endpoints require an X-API-Key header matching the API_KEY
environment variable.  Set this in your .env file.

CORS
----
Allowed origins are read from the ALLOWED_ORIGINS environment variable
(comma-separated).  Default: * (open — tighten before production).
"""

import csv
import io
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

# Lazy imports from the package (avoids loading heavy deps at import time)
from src.auth import GraphAuthClient
from src.migration_executor import MigrationExecutor
from src.organizer import DocumentOrganizer

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SharePoint Reorganization API",
    description="Backend for Mosaic Data Solutions SharePoint Reorganizer",
    version="1.0.0",
)

# CORS — tighten ALLOWED_ORIGINS in production
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------

API_KEY = os.getenv("API_KEY", "")


def verify_api_key(request: Request):
    if not API_KEY:
        # No key configured → open (dev mode)
        return
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_azure_credentials() -> dict:
    creds = {
        "tenant_id": os.getenv("AZURE_TENANT_ID", ""),
        "client_id": os.getenv("AZURE_CLIENT_ID", ""),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET", ""),
        "site_url": os.getenv("SP_SITE_URL", ""),
        "openai_key": os.getenv("AZURE_OPENAI_KEY", ""),
        "openai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "openai_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
    }
    return creds


def _build_auth_client(creds: dict) -> GraphAuthClient:
    missing = [
        k for k in ("tenant_id", "client_id", "client_secret")
        if not creds.get(k)
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Missing Azure credentials: {', '.join(missing)}",
        )
    return GraphAuthClient(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness probe — no auth required."""
    return {"status": "ok"}


@app.post("/api/test-connection")
def test_connection(_: None = Depends(verify_api_key)):
    """Test that Azure/SharePoint credentials are working.

    Returns site name and document library list on success.
    """
    creds = _get_azure_credentials()
    auth = _build_auth_client(creds)

    if not creds["site_url"]:
        raise HTTPException(status_code=503, detail="SP_SITE_URL not configured")

    try:
        site_info = auth.test_connection(creds["site_url"])
        site_id = site_info["id"]

        drives = auth.get_all_pages(f"/sites/{site_id}/drives")
        doc_libs = [
            {"id": d["id"], "name": d.get("name", "Unnamed")}
            for d in drives
            if d.get("driveType") == "documentLibrary"
        ]

        return {
            "status": "connected",
            "site_name": site_info.get("displayName", "Unknown"),
            "site_url": creds["site_url"],
            "document_libraries": doc_libs,
        }

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Connection failed: {str(e)}")


@app.post("/api/organize")
async def organize(
    file: UploadFile = File(..., description="Enriched CSV from Phase 2"),
    _: None = Depends(verify_api_key),
):
    """Run the Phase 3 organizer on an enriched CSV.

    Upload the enriched CSV produced by `main.py --analyze`.
    Returns the full proposal JSON (clean_slate + incremental + summary).

    The improved organizer:
    - Uses classifier's ai_suggested_folder as a strong signal
    - Assigns ALL documents (no 80-doc sampling cap)
    - Includes rich per-document context in batch assignments
    - Infers clients from file paths for Unknown-labeled documents
    """
    creds = _get_azure_credentials()

    if not creds["openai_key"] or not creds["openai_endpoint"]:
        raise HTTPException(
            status_code=503,
            detail="Azure OpenAI credentials (AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT) not configured",
        )

    # Save uploaded CSV to a temp file
    content = await file.read()
    with tempfile.NamedTemporaryFile(
        suffix=".csv", delete=False, mode="wb"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        organizer = DocumentOrganizer(
            api_key=creds["openai_key"],
            endpoint=creds["openai_endpoint"],
            deployment=creds["openai_deployment"],
        )
        proposal = organizer.organize(tmp_path)
        return JSONResponse(content=proposal)

    except Exception as e:
        logger.exception("Organize failed")
        raise HTTPException(status_code=500, detail=f"Organize failed: {str(e)}")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class Assignment(BaseModel):
    file_name: str
    current_path: str
    proposed_path: str
    reason: str = ""


class ExecuteRequest(BaseModel):
    assignments: List[Assignment]
    auto_create_folders: bool = True


@app.post("/api/execute")
def execute_moves(
    body: ExecuteRequest,
    _: None = Depends(verify_api_key),
):
    """Execute approved moves against SharePoint.

    Returns a Server-Sent Events stream so the frontend can display
    real-time progress without polling.

    Each SSE event is a JSON object with:
      progress  – float 0.0–1.0
      phase     – "folders" | "moves" | "summary"
      status    – "success" | "error" | "skip" | "complete"
      file_name – str or null
      message   – str
    """
    creds = _get_azure_credentials()
    auth = _build_auth_client(creds)

    if not creds["site_url"]:
        raise HTTPException(status_code=503, detail="SP_SITE_URL not configured")

    assignments_dicts = [a.model_dump() for a in body.assignments]

    def event_stream():
        try:
            executor = MigrationExecutor(
                auth_client=auth,
                site_url=creds["site_url"],
            )
        except Exception as e:
            payload = json.dumps(
                {"phase": "error", "status": "error", "message": str(e), "progress": 0}
            )
            yield f"data: {payload}\n\n"
            return

        for update in executor.execute_moves(
            assignments_dicts,
            auto_create_folders=body.auto_create_folders,
        ):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Entry point (for local dev: uvicorn src.api:app --reload)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
