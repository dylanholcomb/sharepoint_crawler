"""
Document organizer that clusters classified documents into coherent
folder structures.

Takes the per-document AI classifications from Phase 2 and produces
two proposed folder structures:
  1. Clean Slate — ideal structure based purely on document content
  2. Incremental — improves the existing structure while preserving
     top-level folders that already make sense

Improvements over original:
  - Classifier's ai_suggested_folder field is used as a strong signal,
    not discarded.
  - All documents are assigned (no 80-doc sample cap for large sets).
  - Batch assignments carry richer context: subcategory, keywords,
    summary, classifier suggestion, and confidence score.
  - Unknown client/entity documents get a path-based inference pass
    before the AI sees them, reducing "Unsorted" pile-up.
  - Folder structure and per-doc assignments are split into two focused
    LLM calls, so neither call is overloaded.
  - Fallback proposal NameError bug fixed.
"""

import csv
import json
import logging
import time
from collections import Counter
from pathlib import Path
from datetime import datetime

from openai import AzureOpenAI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt: design folder trees only (no per-doc assignments here)
# ---------------------------------------------------------------------------

STRUCTURE_PROMPT = """You are a SharePoint document organization expert working with a consulting firm that serves multiple California state agency clients.

You have been given a full inventory summary of classified documents including their AI-assigned categories, subcategories, and CLIENT/ENTITY associations. You have also been given the distribution of per-document classifier folder suggestions to use as a strong signal.

## CRITICAL ORGANIZING PRINCIPLE: CLIENT FIRST, THEN DOCUMENT TYPE

Documents MUST be organized by CLIENT/ENTITY at the top level, then by document type within each client.

CORRECT structure:
  CDPH/
    Contracts/
    Deliverables/
    Correspondence/
  CalTrans/
    RFPs/
    Project Plans/
    Reports/
  Mosaic Internal/
    Finance/
    HR/
    Templates/

INCORRECT (do NOT do this):
  Finance/
    CDPH_invoice.pdf
    CalTrans_budget.xlsx

## YOUR TASK

Propose TWO folder trees only (no file assignments in this response):

1. **Clean Slate** — ideal structure from scratch, client-first
2. **Incremental** — improves the existing structure with client grouping while preserving well-organized areas

Rules:
- TOP LEVEL = Client/Entity names (from ai_client_or_entity field)
- SECOND LEVEL = Document type (Contracts, Deliverables, Correspondence, Finance, etc.)
- THIRD LEVEL = Only if needed (by year or project phase)
- Max depth: 3 levels
- Documents with Unknown client go in "Unsorted" or "General" top-level folder
- Internal company documents go under "Mosaic Internal"

Return ONLY valid JSON in this format:
{
  "clean_slate": {
    "description": "Brief explanation of organizing principle",
    "folder_tree": {
      "Folder Name": {
        "description": "What goes in this folder",
        "subfolders": {
          "Subfolder Name": {
            "description": "What goes here"
          }
        }
      }
    }
  },
  "incremental": {
    "description": "Brief explanation of what changes and what stays",
    "folder_tree": { ... same structure ... }
  }
}"""


# ---------------------------------------------------------------------------
# Prompt: assign a batch of documents to an established folder structure
# ---------------------------------------------------------------------------

ASSIGNMENT_SYSTEM_PROMPT = """You assign documents to folders in a SharePoint reorganization.
You will be given:
1. An available folder list (the target structure)
2. A list of documents with rich metadata including their classifier-suggested folder

Rules:
- Match each document's CLIENT/ENTITY to the correct top-level folder
- Use the classifier's suggested folder as a strong starting signal — it is usually close to correct
- Pick the most specific folder that fits; don't put everything in top-level client folders
- Return only valid JSON

Return JSON with this structure:
{
  "clean_slate": [
    {"file_name": "...", "current_path": "...", "proposed_path": "...", "reason": "..."},
    ...
  ],
  "incremental": [
    {"file_name": "...", "current_path": "...", "proposed_path": "...", "reason": "..."},
    ...
  ]
}"""


class DocumentOrganizer:
    """Clusters classified documents and proposes folder structures."""

    def __init__(self, api_key: str, endpoint: str,
                 deployment: str = "gpt-4o",
                 api_version: str = "2024-10-21"):
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        self.deployment = deployment

    def organize(self, enriched_csv_path: str) -> dict:
        """Read the enriched CSV and propose folder structures.

        Strategy:
          1. Load all documents from the CSV.
          2. Run a path-based inference pass to reduce Unknown clients.
          3. Build a rich inventory summary (including classifier folder signals).
          4. One focused LLM call to design the folder STRUCTURE only.
          5. Assign ALL documents to that structure in batches (no sampling cap).
          6. Compile and return the final proposal.

        Args:
            enriched_csv_path: Path to the Phase 2 enriched CSV file.

        Returns:
            Organization proposal dict with clean_slate and incremental plans.
        """
        logger.info("Loading classified document inventory...")
        documents = self._load_csv(enriched_csv_path)
        logger.info(f"Loaded {len(documents)} documents")

        # Step 1: Try to infer clients for Unknown-labeled docs using path heuristics
        documents = self._enrich_unknown_clients(documents)
        unknown_count = sum(
            1 for d in documents
            if d.get("ai_client_or_entity", "Unknown") in ("Unknown", "")
        )
        logger.info(
            f"After client inference: {len(documents) - unknown_count} with known client, "
            f"{unknown_count} still Unknown"
        )

        # Step 2: Build rich inventory summary
        inventory_summary = self._build_inventory_summary(documents)

        # Step 3: Generate folder structure (no per-doc assignments)
        logger.info("Generating folder structure proposals...")
        structure = self._generate_structure(inventory_summary)

        # Step 4: Assign ALL documents in batches using the proposed structure
        logger.info(f"Assigning all {len(documents)} documents to proposed structure...")
        clean_assignments, incr_assignments = self._assign_all_documents(
            documents, structure
        )

        # Step 5: Compile final proposal
        proposal = {
            "clean_slate": {
                "description": structure.get("clean_slate", {}).get("description", ""),
                "folder_tree": structure.get("clean_slate", {}).get("folder_tree", {}),
                "assignments": clean_assignments,
            },
            "incremental": {
                "description": structure.get("incremental", {}).get("description", ""),
                "folder_tree": structure.get("incremental", {}).get("folder_tree", {}),
                "assignments": incr_assignments,
            },
            "summary": {
                "total_documents": len(documents),
                "documents_that_would_move": sum(
                    1 for a in clean_assignments
                    if a.get("current_path", "").strip("/") !=
                    a.get("proposed_path", "").strip("/")
                ),
                "new_folders_created": len(
                    self._flatten_tree(
                        structure.get("clean_slate", {}).get("folder_tree", {})
                    )
                ),
                "folders_consolidated": 0,
            },
        }

        logger.info(
            f"Proposal complete — {len(clean_assignments)} clean-slate assignments, "
            f"{len(incr_assignments)} incremental assignments"
        )
        return proposal

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_csv(self, csv_path: str) -> list:
        """Load the enriched CSV into a list of dicts."""
        documents = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                documents.append(row)
        return documents

    # ------------------------------------------------------------------
    # Unknown-client inference
    # ------------------------------------------------------------------

    def _enrich_unknown_clients(self, documents: list) -> list:
        """Infer client/entity for Unknown-labeled documents using path and filename heuristics.

        Collects all distinct known clients (non-Unknown), then checks whether
        each Unknown document's folder path or filename contains that client name.
        This is purely text-based — no additional API calls.
        """
        # Build a map of lowercase → original client names from documents
        # that already have a confident assignment
        known_clients: dict[str, str] = {}
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown").strip()
            if client and client.lower() not in ("unknown", ""):
                known_clients[client.lower()] = client

        if not known_clients:
            return documents

        updated = 0
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown").strip()
            if client.lower() in ("unknown", ""):
                search_text = (
                    (doc.get("folder_path", "") or "") + "/" +
                    (doc.get("file_name", "") or "")
                ).lower()

                for client_lower, client_orig in known_clients.items():
                    # Handle multi-word clients (e.g. "Mosaic Internal")
                    # by checking that all words appear in the search text
                    words = client_lower.split()
                    if all(w in search_text for w in words):
                        doc["ai_client_or_entity"] = client_orig + " (inferred)"
                        updated += 1
                        break

        if updated:
            logger.info(f"Inferred client/entity for {updated} previously Unknown documents")

        return documents

    # ------------------------------------------------------------------
    # Inventory summary
    # ------------------------------------------------------------------

    def _build_inventory_summary(self, documents: list) -> str:
        """Build a rich text summary of the document inventory for the AI.

        Now includes the distribution of per-document classifier folder
        suggestions so the organizer can treat them as a strong signal.
        """
        clients = Counter(
            doc.get("ai_client_or_entity", "Unknown") for doc in documents
        )
        categories = Counter(
            doc.get("ai_category", "Unclassified") for doc in documents
        )
        subcategories = Counter(
            doc.get("ai_subcategory", "") for doc in documents
        )
        current_folders = Counter(
            doc.get("folder_path", "/") for doc in documents
        )
        extensions = Counter(
            doc.get("extension", "") for doc in documents
        )

        # Classifier-suggested folder distribution (top 30)
        suggested_folders = Counter(
            doc.get("ai_suggested_folder", "") for doc in documents
            if doc.get("ai_suggested_folder", "").strip()
        )

        # Cross-tabulation: client x category
        client_category: dict[str, Counter] = {}
        for doc in documents:
            c = doc.get("ai_client_or_entity", "Unknown")
            cat = doc.get("ai_category", "Unclassified")
            client_category.setdefault(c, Counter())[cat] += 1

        lines = [f"DOCUMENT INVENTORY SUMMARY ({len(documents)} documents)", ""]

        lines.append("CLIENT/ENTITY DISTRIBUTION (use these as TOP-LEVEL folders):")
        for client, count in clients.most_common():
            lines.append(f"  {client}: {count} documents")

        lines += ["", "DOCUMENTS BY CLIENT AND CATEGORY:"]
        for client, cat_counts in sorted(client_category.items()):
            lines.append(f"  {client}:")
            for cat, count in cat_counts.most_common():
                lines.append(f"    {cat}: {count}")

        lines += ["", "AI-CLASSIFIED CATEGORIES:"]
        for cat, count in categories.most_common():
            lines.append(f"  {cat}: {count} documents")

        lines += ["", "AI-CLASSIFIED SUBCATEGORIES (top 25):"]
        for subcat, count in subcategories.most_common(25):
            if subcat:
                lines.append(f"  {subcat}: {count} documents")

        lines += ["", "CLASSIFIER-SUGGESTED FOLDER PATHS (top 30 — use as strong signal):"]
        for folder, count in suggested_folders.most_common(30):
            lines.append(f"  {folder}: {count} documents")

        lines += ["", "CURRENT FOLDER STRUCTURE (top 30):"]
        for folder, count in current_folders.most_common(30):
            lines.append(f"  {folder}: {count} documents")

        lines += ["", "FILE TYPES:"]
        for ext, count in extensions.most_common():
            lines.append(f"  {ext}: {count} files")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Structure generation (focused LLM call — no per-doc assignments)
    # ------------------------------------------------------------------

    def _generate_structure(self, inventory_summary: str) -> dict:
        """Call the LLM to design folder trees only.

        Returns a dict with 'clean_slate' and 'incremental' keys, each
        containing 'description' and 'folder_tree'.  Falls back to the
        heuristic structure if the LLM call fails.
        """
        user_message = (
            f"{inventory_summary}\n\n"
            "Based on this inventory, design the two folder structures "
            "(Clean Slate and Incremental) as described in your instructions. "
            "DO NOT include per-document assignments — only the folder trees."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": STRUCTURE_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            logger.info("Folder structure generated successfully")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse structure response as JSON: {e}")
            return self._fallback_structure(inventory_summary)
        except Exception as e:
            logger.error(f"Failed to generate folder structure: {e}")
            return self._fallback_structure(inventory_summary)

    def _fallback_structure(self, inventory_summary: str) -> dict:
        """Build a basic client-first folder tree from the inventory summary
        without an LLM call.  Used when the structure LLM call fails.
        """
        # Re-parse clients/categories from summary text (quick heuristic)
        # We just return an empty-tree skeleton; _assign_all_documents will
        # create paths directly from each document's client/category.
        logger.info("Using fallback folder structure (heuristic client-first)")
        return {
            "clean_slate": {
                "description": "Client-first folder structure (heuristic fallback)",
                "folder_tree": {},
            },
            "incremental": {
                "description": "Client-first folder structure (heuristic fallback)",
                "folder_tree": {},
            },
        }

    # ------------------------------------------------------------------
    # Document assignment — all docs, batched, with rich context
    # ------------------------------------------------------------------

    def _assign_all_documents(
        self, documents: list, structure: dict
    ) -> tuple[list, list]:
        """Assign every document to both proposed structures.

        Processes ALL documents in batches of 30 — no sampling cap.
        Each document's batch entry includes subcategory, keywords,
        AI summary, classifier suggested folder, and confidence score
        so the LLM has strong signals for each decision.

        Returns:
            (clean_assignments, incremental_assignments) — two lists of
            assignment dicts each with file_name, current_path,
            proposed_path, and reason.
        """
        clean_folder_list = self._flatten_tree(
            structure.get("clean_slate", {}).get("folder_tree", {})
        )
        incr_folder_list = self._flatten_tree(
            structure.get("incremental", {}).get("folder_tree", {})
        )

        clean_assignments: list = []
        incr_assignments: list = []

        batch_size = 30
        total_batches = (len(documents) + batch_size - 1) // batch_size

        for batch_num, i in enumerate(range(0, len(documents), batch_size)):
            batch = documents[i: i + batch_size]
            logger.info(
                f"  Assigning batch {batch_num + 1}/{total_batches} "
                f"({len(batch)} documents)..."
            )

            result = self._assign_batch(batch, clean_folder_list, incr_folder_list)

            clean_batch = result.get("clean_slate", [])
            incr_batch = result.get("incremental", [])

            if isinstance(clean_batch, list):
                clean_assignments.extend(
                    a for a in clean_batch if isinstance(a, dict)
                )
            if isinstance(incr_batch, list):
                incr_assignments.extend(
                    a for a in incr_batch if isinstance(a, dict)
                )

            # Soft rate-limit between batches
            if i + batch_size < len(documents):
                time.sleep(0.5)

        logger.info(
            f"Assignment complete: {len(clean_assignments)} clean-slate, "
            f"{len(incr_assignments)} incremental"
        )
        return clean_assignments, incr_assignments

    def _assign_batch(
        self,
        documents: list,
        clean_folders: list,
        incr_folders: list,
    ) -> dict:
        """Assign a batch of documents to both folder structures.

        Each document line now carries:
          file_name | Client | Category | Subcategory | Keywords |
          AI Summary | Classifier Suggested | Confidence | Current Path

        If either folder list is empty (e.g. fallback structure), the AI
        infers appropriate paths from client/category directly.
        """
        doc_lines = []
        for doc in documents:
            keywords = (doc.get("ai_keywords") or "")[:120]
            summary = (doc.get("ai_summary") or "")[:200]
            suggested = doc.get("ai_suggested_folder") or ""
            confidence = doc.get("ai_confidence") or ""

            doc_lines.append(
                f"- File: {doc.get('file_name', 'Unknown')}"
                f" | Client: {doc.get('ai_client_or_entity', 'Unknown')}"
                f" | Category: {doc.get('ai_category', '')}"
                f" | Subcategory: {doc.get('ai_subcategory', '')}"
                f" | Keywords: {keywords}"
                f" | Summary: {summary}"
                f" | Classifier suggested: {suggested}"
                f" | Confidence: {confidence}"
                f" | Current: {doc.get('full_path', '')}"
            )

        doc_list_text = "\n".join(doc_lines)

        clean_folder_text = (
            "\n".join(f"  - {f}" for f in clean_folders)
            if clean_folders
            else "  (design client-first paths from the client and category fields)"
        )
        incr_folder_text = (
            "\n".join(f"  - {f}" for f in incr_folders)
            if incr_folders
            else "  (design client-first paths from the client and category fields)"
        )

        prompt = (
            "Assign each document to the most appropriate folder.\n\n"
            "RULE: CLIENT/ENTITY goes at the top level, then document type.\n"
            "Use the 'Classifier suggested' path as a strong starting point — "
            "adjust only when a better match exists in the available folders.\n\n"
            f"CLEAN SLATE folders:\n{clean_folder_text}\n\n"
            f"INCREMENTAL folders:\n{incr_folder_text}\n\n"
            f"Documents to assign:\n{doc_list_text}\n\n"
            "Return JSON with 'clean_slate' and 'incremental' keys, each "
            "containing a list of objects with: file_name, current_path, "
            "proposed_path, reason."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": ASSIGNMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=6000,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.warning(f"Batch assignment failed: {e}. Using heuristic fallback.")
            return self._heuristic_batch_assign(documents)

    def _heuristic_batch_assign(self, documents: list) -> dict:
        """Fallback: assign documents using classifier suggestion or client/category."""
        assignments = []
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            category = doc.get("ai_category", "Unclassified")
            suggested = doc.get("ai_suggested_folder", "").strip()

            # Prefer the classifier's suggested path when available
            if suggested:
                proposed = suggested
                reason = f"Classifier-suggested path (heuristic fallback)"
            else:
                proposed = f"{client}/{category}"
                reason = f"{category} document for {client} (heuristic fallback)"

            assignments.append({
                "file_name": doc.get("file_name", ""),
                "current_path": doc.get("full_path", ""),
                "proposed_path": proposed,
                "reason": reason,
            })

        return {"clean_slate": assignments, "incremental": assignments}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _flatten_tree(self, tree: dict, prefix: str = "") -> list:
        """Flatten a folder tree dict into a list of path strings."""
        paths = []
        for name, info in tree.items():
            current = f"{prefix}/{name}" if prefix else name
            paths.append(current)
            subfolders = (
                info.get("subfolders", {}) if isinstance(info, dict) else {}
            )
            paths.extend(self._flatten_tree(subfolders, current))
        return paths

    def _fallback_proposal(self, documents: list) -> dict:
        """Generate a basic proposal using client-first, then category.

        Used when the main organize() pipeline fails completely.
        Bug fix: replaced undefined `categories` reference with correct
        calculation of distinct folder count.
        """
        logger.info("Using full fallback proposal (heuristic client-first)...")

        client_categories: dict[str, Counter] = {}
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            cat = doc.get("ai_category", "Unclassified")
            client_categories.setdefault(client, Counter())[cat] += 1

        folder_tree = {}
        for client, cat_counts in sorted(client_categories.items()):
            subfolders = {
                cat: {"description": f"{count} documents classified as {cat}"}
                for cat, count in cat_counts.most_common()
            }
            folder_tree[client] = {
                "description": f"Documents for {client}",
                "subfolders": subfolders,
            }

        assignments = []
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            category = doc.get("ai_category", "Unclassified")
            suggested = doc.get("ai_suggested_folder", "").strip()
            proposed = suggested if suggested else f"{client}/{category}"

            assignments.append({
                "file_name": doc.get("file_name", ""),
                "current_path": doc.get("full_path", ""),
                "proposed_path": proposed,
                "reason": (
                    "Classifier-suggested path" if suggested
                    else f"{category} document for {client}"
                ),
            })

        # Bug fix: was `len(categories)` which raised NameError.
        total_subfolders = sum(
            len(cats) for cats in client_categories.values()
        )

        return {
            "clean_slate": {
                "description": "Client-first organization (heuristic fallback)",
                "folder_tree": folder_tree,
                "assignments": assignments,
            },
            "incremental": {
                "description": "Client-first organization (heuristic fallback)",
                "folder_tree": folder_tree,
                "assignments": assignments,
            },
            "summary": {
                "total_documents": len(documents),
                "documents_that_would_move": len(documents),
                "new_folders_created": total_subfolders,
                "folders_consolidated": 0,
            },
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_proposal(self, proposal: dict, output_dir: str) -> dict:
        """Export the organization proposal to JSON and CSV files.

        Args:
            proposal: The proposal dict from organize().
            output_dir: Directory to write output files.

        Returns:
            Dict with paths to created files.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Full JSON proposal
        json_file = output_path / f"sp_proposal_{timestamp}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2, default=str)
        logger.info(f"Proposal JSON: {json_file}")

        fieldnames = ["file_name", "current_path", "proposed_path", "reason"]

        # Clean slate CSV
        clean_csv = output_path / f"sp_migration_clean_{timestamp}.csv"
        assignments = [
            a for a in proposal.get("clean_slate", {}).get("assignments", [])
            if isinstance(a, dict)
        ]
        if assignments:
            with open(clean_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(assignments)
            logger.info(f"Clean slate migration CSV: {clean_csv}")

        # Incremental CSV
        incr_csv = output_path / f"sp_migration_incremental_{timestamp}.csv"
        assignments = [
            a for a in proposal.get("incremental", {}).get("assignments", [])
            if isinstance(a, dict)
        ]
        if assignments:
            with open(incr_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(assignments)
            logger.info(f"Incremental migration CSV: {incr_csv}")

        return {
            "proposal_json": str(json_file),
            "clean_slate_csv": str(clean_csv),
            "incremental_csv": str(incr_csv),
        }
