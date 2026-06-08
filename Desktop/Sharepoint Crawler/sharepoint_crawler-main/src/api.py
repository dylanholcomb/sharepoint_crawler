"""
Flask backend for the SharePoint Reorganization tool.

Rewritten from FastAPI to Flask for PythonAnywhere WSGI compatibility.
Flask is natively WSGI and works reliably on PythonAnywhere without
any ASGI/WSGI bridge layers.

Endpoints
---------
GET  /health                       – liveness probe
POST /api/test-connection          – verify Azure credentials
POST /api/analyze                  – full pipeline: crawl → classify → organize (SSE stream)
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
from src.classifier import DocumentClassifier
from src.crawler import SharePointCrawler
from src.exporter import CrawlExporter
from src.extractor import DocumentExtractor
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
        "tenant_id":         os.getenv("AZURE_TENANT_ID", ""),
        "client_id":         os.getenv("AZURE_CLIENT_ID", ""),
        "client_secret":     os.getenv("AZURE_CLIENT_SECRET", ""),
        "site_url":          os.getenv("SP_SITE_URL", ""),
        "openai_key":        os.getenv("AZURE_OPENAI_KEY", ""),
        "openai_endpoint":   os.getenv("AZURE_OPENAI_ENDPOINT", ""),
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


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    """Format a dict as a Server-Sent Events data line."""
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# /api/analyze  — full 3-phase pipeline streamed as SSE
# ---------------------------------------------------------------------------

@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Run the full crawl → classify → organize pipeline.

    Streams Server-Sent Events so the frontend can show real-time progress.

    Each event is a JSON object:
      phase     – "crawl" | "classify" | "organize" | "complete" | "error"
      status    – "running" | "complete" | "success" | "error"
      message   – human-readable status string
      progress  – float 0.0–1.0
      proposal  – (only on phase="complete") the full proposal JSON

    No request body required — all credentials come from the server .env.
    """
    err = check_api_key()
    if err:
        return err

    creds = _get_azure_credentials()

    missing_azure = [k for k in ("tenant_id", "client_id", "client_secret") if not creds.get(k)]
    if missing_azure:
        return jsonify({"detail": f"Missing Azure credentials: {', '.join(missing_azure)}"}), 503

    if not creds.get("site_url"):
        return jsonify({"detail": "SP_SITE_URL not configured"}), 503

    if not creds.get("openai_key") or not creds.get("openai_endpoint"):
        return jsonify({
            "detail": "Azure OpenAI credentials not configured "
                      "(AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT)"
        }), 503

    def generate():
        try:
            # ------------------------------------------------------------------
            # Phase 1 — Crawl
            # ------------------------------------------------------------------
            yield _sse({
                "phase": "crawl", "status": "running",
                "message": "Connecting to SharePoint...", "progress": 0.0,
            })

            auth = _build_auth_client(creds)
            crawler = SharePointCrawler(auth, creds["site_url"])

            yield _sse({
                "phase": "crawl", "status": "running",
                "message": "Scanning document libraries...", "progress": 0.05,
            })

            documents = crawler.crawl()

            if not documents:
                yield _sse({
                    "phase": "error", "status": "error",
                    "message": "No documents found in SharePoint site.", "progress": 0.0,
                })
                return

            yield _sse({
                "phase": "crawl", "status": "complete",
                "message": f"Found {len(documents)} documents", "progress": 0.20,
            })

            # ------------------------------------------------------------------
            # Phase 2 — Extract text + Classify
            # ------------------------------------------------------------------
            yield _sse({
                "phase": "classify", "status": "running",
                "message": "Extracting document content...", "progress": 0.25,
            })

            extractor = DocumentExtractor(auth)

            # Derive the fallback drive ID from the first document that has
            # one, avoiding a redundant _get_document_libraries() API call.
            primary_drive_id = ""
            for _d in documents:
                _path = _d.get("drive_item_path", "")
                if "/drives/" in _path:
                    try:
                        primary_drive_id = _path.split("/drives/")[1].split("/")[0]
                    except IndexError:
                        pass
                    break

            for i, doc in enumerate(documents):
                drive_item_path = doc.get("drive_item_path", "")
                drive_id = primary_drive_id
                if "/drives/" in drive_item_path:
                    try:
                        parts = drive_item_path.split("/drives/")[1].split("/")
                        drive_id = parts[0]
                    except (IndexError, KeyError):
                        pass

                text = extractor.extract_text(
                    drive_item_id=doc["item_id"],
                    drive_id=drive_id,
                    file_name=doc["file_name"],
                    extension=doc["extension"],
                )
                doc["extracted_text"] = text

                if i % 10 == 0:
                    progress = 0.25 + (i / len(documents)) * 0.20
                    yield _sse({
                        "phase": "classify", "status": "running",
                        "message": f"Extracting content: {i + 1}/{len(documents)}",
                        "progress": round(progress, 3),
                    })

            extracted_count = sum(1 for d in documents if d.get("extracted_text"))
            yield _sse({
                "phase": "classify", "status": "running",
                "message": f"Classifying {len(documents)} documents with AI "
                           f"({extracted_count} with extracted text)...",
                "progress": 0.47,
            })

            classifier = DocumentClassifier(
                api_key=creds["openai_key"],
                endpoint=creds["openai_endpoint"],
                deployment=creds["openai_deployment"],
            )
            documents = classifier.classify_batch(documents)

            # Strip raw text before export (not needed downstream)
            for doc in documents:
                doc.pop("extracted_text", None)

            yield _sse({
                "phase": "classify", "status": "complete",
                "message": "Classification complete", "progress": 0.65,
            })

            # ------------------------------------------------------------------
            # Phase 3 — Organize
            # Write enriched CSV to a temp file, run organizer, and yield the
            # complete event all inside the TemporaryDirectory context so
            # `proposal` is always in scope when it's referenced.
            # ------------------------------------------------------------------
            with tempfile.TemporaryDirectory() as tmp_dir:
                exporter = CrawlExporter(
                    documents=documents,
                    stats=crawler.stats,
                    output_dir=tmp_dir,
                )
                enriched_csv = exporter.export_enriched_csv()

                yield _sse({
                    "phase": "organize", "status": "running",
                    "message": "Designing folder structure with AI...", "progress": 0.70,
                })

                organizer = DocumentOrganizer(
                    api_key=creds["openai_key"],
                    endpoint=creds["openai_endpoint"],
                    deployment=creds["openai_deployment"],
                )
                proposal = organizer.organize(enriched_csv)

                yield _sse({
                    "phase": "complete", "status": "success",
                    "message": "Analysis complete — proposal ready",
                    "progress": 1.0,
                    "proposal": proposal,
                })

        except Exception as exc:
            logger.exception("Analyze pipeline failed")
            yield _sse({
                "phase": "error", "status": "error",
                "message": str(exc), "progress": 0.0,
            })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
            yield _sse({
                "phase": "error", "status": "error",
                "message": str(e), "progress": 0,
            })
            return

        for update in executor.execute_moves(
            assignments,
            auto_create_folders=auto_create_folders,
        ):
            yield _sse(update)

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
