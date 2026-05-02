"""
Flask backend for the SharePoint Reorganization tool.

Rewritten from FastAPI to Flask for PythonAnywhere WSGI compatibility.
Flask is natively WSGI and works reliably on PythonAnywhere without
any ASGI/WSGI bridge layers.

Endpoints
---------
GET  /health                       – liveness probe
POST /api/test-connection          – verify Azure credentials
POST /api/organize                 – run Phase 3 organizer on an uploaded CSV
POST /api/execute                  – execute approved moves (SSE stream)

Authentication
--------------
All /api/* endpoints require an X-API-Key header matching the API_KEY
environment variable set in your .env file.

CORS
----
Allowed origins read from ALLOWED_ORIGINS env var (comma-separated).
Default: * (open — tighten before production).
"""

import csv
import io
import json
import logging
import os
import tempfile

from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

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

app = Flask(__name__)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
CORS(app, origins=allowed_origins)

# ---------------------------------------------------------------------------
# API key auth helper
# ---------------------------------------------------------------------------

API_KEY = os.getenv("API_KEY", "")


def check_api_key():
    """Return an error response if the API key is invalid, else None."""
    if not API_KEY:
        return None  # No key configured — open (dev mode)
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return jsonify({"detail": "Invalid or missing API key"}), 401
    return None


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_azure_credentials():
    return {
        "tenant_id":        os.getenv("AZURE_TENANT_ID", ""),
        "client_id":        os.getenv("AZURE_CLIENT_ID", ""),
        "client_secret":    os.getenv("AZURE_CLIENT_SECRET", ""),
        "site_url":         os.getenv("SP_SITE_URL", ""),
        "openai_key":       os.getenv("AZURE_OPENAI_KEY", ""),
        "openai_endpoint":  os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "openai_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
    }


def _build_auth_client(creds):
    missing = [k for k in ("tenant_id", "client_id", "client_secret") if not creds.get(k)]
    if missing:
        raise ValueError(f"Missing Azure credentials: {', '.join(missing)}")
    return GraphAuthClient(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Liveness probe — no auth required."""
    return jsonify({"status": "ok"})


@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    """Test that Azure/SharePoint credentials are working."""
    err = check_api_key()
    if err:
        return err

    creds = _get_azure_credentials()

    try:
        auth = _build_auth_client(creds)
    except ValueError as e:
        return jsonify({"detail": str(e)}), 503

    if not creds["site_url"]:
        return jsonify({"detail": "SP_SITE_URL not configured"}), 503

    try:
        site_info = auth.test_connection(creds["site_url"])
        site_id = site_info["id"]

        drives = auth.get_all_pages(f"/sites/{site_id}/drives")
        doc_libs = [
            {"id": d["id"], "name": d.get("name", "Unnamed")}
            for d in drives
            if d.get("driveType") == "documentLibrary"
        ]

        return jsonify({
            "status": "connected",
            "site_name": site_info.get("displayName", "Unknown"),
            "site_url": creds["site_url"],
            "document_libraries": doc_libs,
        })

    except Exception as e:
        logger.exception("Connection test failed")
        return jsonify({"detail": f"Connection failed: {str(e)}"}), 502


@app.route("/api/organize", methods=["POST"])
def organize():
    """Run the Phase 3 organizer on an uploaded enriched CSV.

    Upload the enriched CSV produced by main.py --analyze.
    Returns the full proposal JSON (clean_slate + incremental + summary).
    """
    err = check_api_key()
    if err:
        return err

    creds = _get_azure_credentials()

    if not creds["openai_key"] or not creds["openai_endpoint"]:
        return jsonify({
            "detail": "Azure OpenAI credentials not configured "
                      "(AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT)"
        }), 503

    if "file" not in request.files:
        return jsonify({"detail": "No file uploaded. Send the enriched CSV as 'file'."}), 400

    uploaded = request.files["file"]
    content = uploaded.read()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        organizer = DocumentOrganizer(
            api_key=creds["openai_key"],
            endpoint=creds["openai_endpoint"],
            deployment=creds["openai_deployment"],
        )
        proposal = organizer.organize(tmp_path)
        return jsonify(proposal)

    except Exception as e:
        logger.exception("Organize failed")
        return jsonify({"detail": f"Organize failed: {str(e)}"}), 500

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.route("/api/execute", methods=["POST"])
def execute_moves():
    """Execute approved moves against SharePoint.

    Streams a Server-Sent Events response so the frontend can display
    real-time progress. Each event is a JSON object with:
      progress  – float 0.0–1.0
      phase     – "folders" | "moves" | "summary"
      status    – "success" | "error" | "skip" | "complete"
      file_name – str or null
      message   – str
    """
    err = check_api_key()
    if err:
        return err

    body = request.get_json(force=True)
    if not body:
        return jsonify({"detail": "Request body must be JSON"}), 400

    assignments = body.get("assignments", [])
    auto_create_folders = body.get("auto_create_folders", True)

    creds = _get_azure_credentials()

    try:
        auth = _build_auth_client(creds)
    except ValueError as e:
        return jsonify({"detail": str(e)}), 503

    if not creds["site_url"]:
        return jsonify({"detail": "SP_SITE_URL not configured"}), 503

    def generate():
        try:
            executor = MigrationExecutor(
                auth_client=auth,
                site_url=creds["site_url"],
            )
        except Exception as e:
            payload = json.dumps({
                "phase": "error",
                "status": "error",
                "message": str(e),
                "progress": 0,
            })
            yield f"data: {payload}\n\n"
            return

        for update in executor.execute_moves(
            assignments,
            auto_create_folders=auto_create_folders,
        ):
            yield f"data: {json.dumps(update)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Entry point (local dev only — PythonAnywhere uses WSGI via wsgi.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=8000)
