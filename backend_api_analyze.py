"""
Background-job /api/analyze endpoint for the PythonAnywhere Flask backend.

Why a background job?
  PythonAnywhere kills HTTP requests after 5 min (free) / 15 min (paid). For
  any non-trivial SharePoint site, a single long-running request will time
  out mid-pipeline, leaving the UI stuck.

Architecture:
  POST /api/analyze
      Spawns a daemon thread that runs crawl -> extract -> classify ->
      organize. Returns {job_id} immediately (HTTP 200).

  GET  /api/analyze/<job_id>/stream?since=<event_id>
      Server-Sent Events stream that yields new progress events as they
      are produced. The optional 'since' query param lets the client
      reconnect after a connection drop and resume from where it left
      off — important because PA still kills *idle-ish* connections at
      the 5-min mark.

  GET  /api/analyze/<job_id>
      JSON snapshot of the job's current state. Used as a polling
      fallback if SSE fails entirely.

Job state is kept in an in-process dict (PA free runs a single worker so
this is safe). For multi-worker deployments later, swap _JOBS for a
shared store (Redis / SQLite).
"""

import csv
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Response, jsonify, request, stream_with_context

from src.crawler import SharePointCrawler
from src.extractor import DocumentExtractor
from src.classifier import DocumentClassifier
from src.organizer import DocumentOrganizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process job store
# ---------------------------------------------------------------------------

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

# How long to keep finished jobs in memory before garbage-collecting them.
_JOB_TTL_SECONDS = 60 * 30  # 30 minutes

# How often the SSE handler checks for new events (seconds).
_SSE_POLL_INTERVAL = 0.4

# Heartbeat comment cadence to keep proxies / load balancers from closing
# the connection during long quiet phases.
_SSE_HEARTBEAT_INTERVAL = 15.0


def _now() -> float:
    return time.time()


def _new_job() -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "status": "pending",  # pending | running | complete | error
            "events": [],         # [{id, phase, message, progress, ...}]
            "proposal": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        _gc_old_jobs_locked()
    return job_id


def _gc_old_jobs_locked() -> None:
    cutoff = _now() - _JOB_TTL_SECONDS
    stale = [
        jid for jid, j in _JOBS.items()
        if j["status"] in ("complete", "error") and j["updated_at"] < cutoff
    ]
    for jid in stale:
        _JOBS.pop(jid, None)


def _push_event(job_id: str, event: Dict[str, Any]) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        event["id"] = len(job["events"])
        job["events"].append(event)
        job["updated_at"] = _now()
        # Mirror the latest phase/progress on the job record for quick polling
        if "phase" in event:
            job["phase"] = event["phase"]
        if "progress" in event:
            job["progress"] = event["progress"]
        if event.get("phase") == "complete":
            job["status"] = "complete"
            job["proposal"] = event.get("proposal")
        elif event.get("phase") == "error":
            job["status"] = "error"
            job["error"] = event.get("message")


def _set_status(job_id: str, status: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["status"] = status
            job["updated_at"] = _now()


def _get_events_since(job_id: str, since: int) -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return []
        return list(job["events"][since + 1:]) if since >= 0 else list(job["events"])


def _get_status(job_id: str) -> Optional[str]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return job["status"] if job else None


# ---------------------------------------------------------------------------
# CSV helper for the organizer
# ---------------------------------------------------------------------------

ENRICHED_CSV_FIELDS = [
    "file_name", "extension", "size_bytes", "size_readable", "mime_type",
    "library_name", "folder_path", "full_path", "depth",
    "created_date", "modified_date", "created_by", "modified_by",
    "web_url", "item_id", "drive_item_path",
    "ai_category", "ai_subcategory", "ai_summary", "ai_keywords",
    "ai_confidence", "ai_suggested_folder", "ai_client_or_entity",
    "ai_sensitivity_flag",
]


def _write_enriched_csv(documents: list) -> str:
    tmp = tempfile.NamedTemporaryFile(
        prefix="sp_analysis_", suffix=".csv", delete=False, mode="w",
        encoding="utf-8", newline="",
    )
    writer = csv.DictWriter(
        tmp, fieldnames=ENRICHED_CSV_FIELDS, extrasaction="ignore"
    )
    writer.writeheader()
    for doc in documents:
        row = {k: ("" if v is None else v) for k, v in doc.items()}
        writer.writerow(row)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, creds: dict, auth) -> None:
    """Execute crawl -> extract -> classify -> organize, pushing progress
    events to the in-memory job record as it goes."""
    csv_path = None
    site_url = creds["site_url"]
    try:
        _set_status(job_id, "running")

        # ---------- Phase 1: CRAWL ----------
        _push_event(job_id, {
            "phase": "crawl",
            "message": f"Connecting to {site_url}...",
            "progress": 0.02,
        })

        crawler = SharePointCrawler(auth, site_url)
        documents = crawler.crawl()

        if not documents:
            _push_event(job_id, {
                "phase": "error",
                "message": "No documents found on the SharePoint site.",
            })
            return

        _push_event(job_id, {
            "phase": "crawl",
            "message": (
                f"Crawled {crawler.stats['libraries_found']} libraries, "
                f"{crawler.stats['folders_traversed']} folders, "
                f"{len(documents)} files."
            ),
            "progress": 0.25,
        })

        # ---------- Phase 2: EXTRACT + CLASSIFY ----------
        _push_event(job_id, {
            "phase": "classify",
            "message": f"Extracting text from {len(documents)} documents...",
            "progress": 0.27,
        })

        extractor = DocumentExtractor(auth)
        libraries = crawler._get_document_libraries()
        primary_drive_id = libraries[0]["id"] if libraries else ""

        total = len(documents)
        tick_every = max(1, total // 20)

        for i, doc in enumerate(documents):
            drive_item_path = doc.get("drive_item_path", "") or ""
            drive_id = primary_drive_id
            if "/drives/" in drive_item_path:
                try:
                    drive_id = drive_item_path.split("/drives/")[1].split("/")[0]
                except (IndexError, KeyError):
                    pass

            try:
                doc["extracted_text"] = extractor.extract_text(
                    drive_item_id=doc["item_id"],
                    drive_id=drive_id,
                    file_name=doc["file_name"],
                    extension=doc["extension"],
                )
            except Exception as ex:
                logger.warning(f"Extract failed for {doc.get('file_name')}: {ex}")
                doc["extracted_text"] = ""

            if (i + 1) % tick_every == 0 or (i + 1) == total:
                progress = 0.27 + 0.28 * ((i + 1) / total)
                _push_event(job_id, {
                    "phase": "classify",
                    "message": f"Extracted {i + 1}/{total} documents",
                    "progress": round(progress, 3),
                })

        _push_event(job_id, {
            "phase": "classify",
            "message": "Classifying documents with AI...",
            "progress": 0.58,
        })

        classifier = DocumentClassifier(
            api_key=creds["openai_key"],
            endpoint=creds["openai_endpoint"],
            deployment=creds["openai_deployment"],
        )
        documents = classifier.classify_batch(documents)

        _push_event(job_id, {
            "phase": "classify",
            "message": f"Classified {len(documents)} documents",
            "progress": 0.78,
        })

        # ---------- Phase 3: ORGANIZE ----------
        for doc in documents:
            doc.pop("extracted_text", None)

        csv_path = _write_enriched_csv(documents)

        _push_event(job_id, {
            "phase": "organize",
            "message": "Generating folder structure proposals...",
            "progress": 0.82,
        })

        organizer = DocumentOrganizer(
            api_key=creds["openai_key"],
            endpoint=creds["openai_endpoint"],
            deployment=creds["openai_deployment"],
        )
        proposal = organizer.organize(csv_path)

        # ---------- Phase 4: COMPLETE ----------
        _push_event(job_id, {
            "phase": "complete",
            "message": "Analysis complete.",
            "progress": 1.0,
            "proposal": proposal,
        })

    except Exception as e:
        logger.exception(f"Analyze job {job_id} failed")
        _push_event(job_id, {
            "phase": "error",
            "message": f"Analysis failed: {str(e)}",
        })
    finally:
        if csv_path:
            try:
                os.unlink(csv_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_analyze_route(app, check_api_key, _get_azure_credentials, _build_auth_client):
    """Wire the background-job analyze endpoints into a Flask app.

    Add to api.py (after _build_auth_client / check_api_key are defined):

        from .backend_api_analyze import register_analyze_route
        register_analyze_route(app, check_api_key, _get_azure_credentials, _build_auth_client)
    """

    @app.route("/api/analyze", methods=["POST"])
    def analyze_start():
        """Kick off a background analysis job. Returns {job_id} immediately."""
        err = check_api_key()
        if err:
            return err

        creds = _get_azure_credentials()
        if not creds["openai_key"] or not creds["openai_endpoint"]:
            return jsonify({
                "detail": "Azure OpenAI credentials not configured "
                          "(AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT)"
            }), 503
        if not creds["site_url"]:
            return jsonify({"detail": "SP_SITE_URL not configured"}), 503

        try:
            auth = _build_auth_client(creds)
        except ValueError as e:
            return jsonify({"detail": str(e)}), 503

        job_id = _new_job()

        thread = threading.Thread(
            target=_run_pipeline,
            args=(job_id, creds, auth),
            daemon=True,
            name=f"analyze-{job_id[:8]}",
        )
        thread.start()

        return jsonify({"job_id": job_id, "status": "pending"}), 202

    @app.route("/api/analyze/<job_id>", methods=["GET"])
    def analyze_status(job_id):
        """JSON snapshot of a job (polling fallback)."""
        err = check_api_key()
        if err:
            return err
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
            if not job:
                return jsonify({"detail": "Unknown job_id"}), 404
            # Return a shallow copy without the full events list to keep payload small
            snapshot = {
                "id": job["id"],
                "status": job["status"],
                "phase": job.get("phase"),
                "progress": job.get("progress"),
                "error": job.get("error"),
                "event_count": len(job["events"]),
                "last_event": job["events"][-1] if job["events"] else None,
                "proposal": job.get("proposal"),
            }
        return jsonify(snapshot)

    @app.route("/api/analyze/<job_id>/stream", methods=["GET"])
    def analyze_stream(job_id):
        """Resumable SSE stream of job progress events.

        Query params:
            since: integer event id to resume after (default -1 = from start)
        """
        err = check_api_key()
        if err:
            return err

        with _JOBS_LOCK:
            if job_id not in _JOBS:
                return jsonify({"detail": "Unknown job_id"}), 404

        try:
            since = int(request.args.get("since", "-1"))
        except (TypeError, ValueError):
            since = -1

        def generate():
            last_id = since
            last_heartbeat = _now()
            # Initial flush of any already-emitted events.
            pending = _get_events_since(job_id, last_id)
            for ev in pending:
                last_id = ev["id"]
                yield _sse(ev)

            while True:
                status = _get_status(job_id)
                if status is None:
                    yield _sse({"phase": "error", "message": "Job disappeared from server."})
                    return

                pending = _get_events_since(job_id, last_id)
                if pending:
                    for ev in pending:
                        last_id = ev["id"]
                        yield _sse(ev)
                    last_heartbeat = _now()

                if status in ("complete", "error"):
                    return

                if _now() - last_heartbeat >= _SSE_HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = _now()

                time.sleep(_SSE_POLL_INTERVAL)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return analyze_start
