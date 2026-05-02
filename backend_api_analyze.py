"""
Drop-in /api/analyze streaming endpoint for the PythonAnywhere Flask backend.

Paste the imports, helper, and route into your existing src/api.py
(or copy this whole file's contents into api.py — they don't conflict
with anything that's already there).

This endpoint chains the three CLI phases (crawl -> extract -> classify -> organize)
into a single Server-Sent Events stream so the frontend can show live progress.
"""

import csv
import json
import logging
import os
import tempfile

from flask import Response, jsonify, request, stream_with_context

# --- These imports already exist in api.py; re-listed here for clarity ---
from src.auth import GraphAuthClient
from src.crawler import SharePointCrawler
from src.extractor import DocumentExtractor
from src.classifier import DocumentClassifier
from src.organizer import DocumentOrganizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: build a CSV row dict for the organizer
#
# DocumentOrganizer.organize(csv_path) reads these columns from the enriched
# CSV: file_name, folder_path, extension, ai_category, ai_subcategory,
# ai_client_or_entity, ai_suggested_folder.  We write a superset just to be
# safe — extra columns are ignored by csv.DictReader.
# ---------------------------------------------------------------------------

ENRICHED_CSV_FIELDS = [
    "file_name", "extension", "size_bytes", "size_readable", "mime_type",
    "library_name", "folder_path", "full_path", "depth",
    "created_date", "modified_date", "created_by", "modified_by",
    "web_url", "item_id", "drive_item_path",
    # AI enrichment fields written by DocumentClassifier:
    "ai_category", "ai_subcategory", "ai_client_or_entity",
    "ai_suggested_folder", "ai_keywords", "ai_summary", "ai_confidence",
]


def _write_enriched_csv(documents: list) -> str:
    """Write the enriched (post-classification) documents to a temp CSV.

    Returns the path so DocumentOrganizer.organize() can read it.
    """
    tmp = tempfile.NamedTemporaryFile(
        prefix="sp_analysis_", suffix=".csv", delete=False, mode="w",
        encoding="utf-8", newline="",
    )
    writer = csv.DictWriter(
        tmp, fieldnames=ENRICHED_CSV_FIELDS, extrasaction="ignore"
    )
    writer.writeheader()
    for doc in documents:
        # Stringify any non-scalar fields to keep the CSV happy
        row = {k: ("" if v is None else v) for k, v in doc.items()}
        writer.writerow(row)
    tmp.close()
    return tmp.name


def _sse(event: dict) -> str:
    """Format a dict as an SSE 'data:' line."""
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Add this route to your Flask app (alongside /api/organize, /api/execute)
# ---------------------------------------------------------------------------

def register_analyze_route(app, check_api_key, _get_azure_credentials, _build_auth_client):
    """Call this from api.py after the app is created:

        from backend_api_analyze import register_analyze_route
        register_analyze_route(app, check_api_key, _get_azure_credentials, _build_auth_client)

    Or just inline the @app.route block below directly into api.py.
    """

    @app.route("/api/analyze", methods=["POST"])
    def analyze():
        """End-to-end SharePoint analysis with SSE progress.

        Phases streamed to the frontend:
          - crawl     : walking the SharePoint document libraries
          - classify  : extracting text + AI classification per file
          - organize  : building the folder-structure proposal
          - complete  : final payload with the full proposal JSON
          - error     : any failure (terminal)
        """
        err = check_api_key()
        if err:
            return err

        creds = _get_azure_credentials()

        # Validate config up-front so we fail fast with a useful error.
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

        site_url = creds["site_url"]

        def generate():
            csv_path = None
            try:
                # ---------- Phase 1: CRAWL ----------
                yield _sse({
                    "phase": "crawl",
                    "message": f"Connecting to {site_url}...",
                    "progress": 0.02,
                })

                crawler = SharePointCrawler(auth, site_url)
                documents = crawler.crawl()

                if not documents:
                    yield _sse({
                        "phase": "error",
                        "message": "No documents found on the SharePoint site.",
                    })
                    return

                yield _sse({
                    "phase": "crawl",
                    "message": (
                        f"Crawled {crawler.stats['libraries_found']} libraries, "
                        f"{crawler.stats['folders_traversed']} folders, "
                        f"{len(documents)} files."
                    ),
                    "progress": 0.25,
                })

                # ---------- Phase 2: EXTRACT + CLASSIFY ----------
                yield _sse({
                    "phase": "classify",
                    "message": f"Extracting text from {len(documents)} documents...",
                    "progress": 0.27,
                })

                extractor = DocumentExtractor(auth)
                libraries = crawler._get_document_libraries()
                primary_drive_id = libraries[0]["id"] if libraries else ""

                total = len(documents)
                # Emit a progress tick roughly every 5% to avoid flooding the stream.
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
                        # Don't kill the whole stream on a single bad file
                        logger.warning(f"Extract failed for {doc.get('file_name')}: {ex}")
                        doc["extracted_text"] = ""

                    if (i + 1) % tick_every == 0 or (i + 1) == total:
                        # Extraction occupies progress 0.27 → 0.55
                        progress = 0.27 + 0.28 * ((i + 1) / total)
                        yield _sse({
                            "phase": "classify",
                            "message": f"Extracted {i + 1}/{total} documents",
                            "progress": round(progress, 3),
                        })

                yield _sse({
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

                yield _sse({
                    "phase": "classify",
                    "message": f"Classified {len(documents)} documents",
                    "progress": 0.78,
                })

                # ---------- Phase 3: ORGANIZE ----------
                # Strip extracted_text before writing the CSV (matches main.py)
                for doc in documents:
                    doc.pop("extracted_text", None)

                csv_path = _write_enriched_csv(documents)

                yield _sse({
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
                yield _sse({
                    "phase": "complete",
                    "message": "Analysis complete.",
                    "progress": 1.0,
                    "proposal": proposal,
                })

            except Exception as e:
                logger.exception("Analyze failed")
                yield _sse({
                    "phase": "error",
                    "message": f"Analysis failed: {str(e)}",
                })
            finally:
                if csv_path:
                    try:
                        os.unlink(csv_path)
                    except OSError:
                        pass

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return analyze
