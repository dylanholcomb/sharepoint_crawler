"""
Document organizer that clusters classified documents into coherent
folder structures.

Takes the per-document AI classifications from Phase 2 and produces
two proposed folder structures:
  1. Clean Slate — ideal structure based purely on document content
  2. Incremental — improves the existing structure while preserving
     top-level folders that already make sense

Uses Azure OpenAI to analyze all classifications holistically and
propose a unified structure rather than per-document suggestions.
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


ORGANIZER_PROMPT = """You are a SharePoint document organization expert working with a consulting firm that serves multiple California state agency clients. You've been given a complete inventory of documents with their AI-classified categories, subcategories, keywords, and CLIENT/ENTITY associations.

## CRITICAL ORGANIZING PRINCIPLE: CLIENT FIRST, THEN DOCUMENT TYPE

This is a consulting firm's SharePoint. Documents MUST be organized by CLIENT/ENTITY at the top level, then by document type within each client. This is the single most important rule.

CORRECT structure example:
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

INCORRECT structure (DO NOT do this):
  Finance/
    CDPH_invoice.pdf
    CalTrans_budget.xlsx
    Mosaic_payroll.csv
  Contracts/
    CDPH_contract.docx
    CalTrans_agreement.pdf

The INCORRECT approach lumps all clients' finance docs together, making it impossible for the team to find all materials for a specific client engagement.

Your job is to propose TWO folder structures:

## PROPOSAL 1: CLEAN SLATE
Design the ideal folder structure from scratch. Use the ai_client_or_entity field to group documents by client at the top level. Within each client folder, create subfolders by document type/category. Rules:
- TOP LEVEL = Client/Entity names (from ai_client_or_entity field)
- SECOND LEVEL = Document type (Contracts, Deliverables, Correspondence, Finance, etc.)
- THIRD LEVEL = Only if needed (e.g., by year or project phase)
- Keep depth to 3 levels maximum
- Documents marked "Unknown" client should go in an "Unsorted" or "General" top-level folder
- Internal company documents (HR, templates, policies) go under "Mosaic Internal" or similar

## PROPOSAL 2: INCREMENTAL IMPROVEMENT
Improve the existing structure by introducing client-based grouping where missing:
- If client folders already exist and are well-organized, keep them
- Move documents that are grouped by type (across clients) into client-first folders
- Consolidate redundant folders
- Flatten unnecessarily deep nesting
- Create new client folders only where there's a clear gap

For EACH proposal, return a JSON object with this structure:
{
  "clean_slate": {
    "description": "Brief explanation of the organizing principle",
    "folder_tree": {
      "Folder Name": {
        "description": "What goes in this folder",
        "subfolders": {
          "Subfolder Name": {
            "description": "What goes here"
          }
        }
      }
    },
    "assignments": [
      {
        "file_name": "example.docx",
        "current_path": "Documents/Old Stuff/Misc",
        "proposed_path": "CDPH/Budget Reports",
        "reason": "CDPH budget report — grouped under client folder"
      }
    ]
  },
  "incremental": {
    "description": "Brief explanation of what changes and what stays",
    "folder_tree": { ... same structure ... },
    "assignments": [ ... same structure ... ]
  },
  "summary": {
    "total_documents": 0,
    "documents_that_would_move": 0,
    "new_folders_created": 0,
    "folders_consolidated": 0
  }
}

Return ONLY valid JSON."""


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

        Args:
            enriched_csv_path: Path to the Phase 2 enriched CSV file.

        Returns:
            Organization proposal dict with clean_slate and incremental plans.
        """
        logger.info("Loading classified document inventory...")
        documents = self._load_csv(enriched_csv_path)
        logger.info(f"Loaded {len(documents)} documents")

        # Build a summary of categories and current structure
        # to send to the AI (full doc list may exceed token limits)
        inventory_summary = self._build_inventory_summary(documents)

        # For smaller sets (< 100 docs), send full details
        # For larger sets, send the summary + a sample
        if len(documents) <= 100:
            doc_details = self._format_all_documents(documents)
        else:
            doc_details = self._format_document_sample(documents, sample_size=80)

        logger.info("Generating folder structure proposals...")
        proposal = self._generate_proposals(inventory_summary, doc_details,
                                             documents)

        # Enrich the proposal with documents that weren't in the sample
        if len(documents) > 100:
            logger.info("Assigning remaining documents to proposed structure...")
            proposal = self._assign_remaining(proposal, documents)

        return proposal

    def _load_csv(self, csv_path: str) -> list:
        """Load the enriched CSV into a list of dicts."""
        documents = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                documents.append(row)
        return documents

    def _build_inventory_summary(self, documents: list) -> str:
        """Build a text summary of the document inventory for the AI."""
        # Client/Entity distribution (PRIMARY grouping)
        clients = Counter(doc.get("ai_client_or_entity", "Unknown")
                         for doc in documents)

        # Category distribution
        categories = Counter(doc.get("ai_category", "Unclassified")
                           for doc in documents)

        # Subcategory distribution
        subcategories = Counter(doc.get("ai_subcategory", "")
                               for doc in documents)

        # Current folder structure
        current_folders = Counter(doc.get("folder_path", "/")
                                 for doc in documents)

        # File type distribution
        extensions = Counter(doc.get("extension", "")
                            for doc in documents)

        # Cross-tabulation: client x category
        client_category = {}
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            cat = doc.get("ai_category", "Unclassified")
            if client not in client_category:
                client_category[client] = Counter()
            client_category[client][cat] += 1

        lines = []
        lines.append(f"DOCUMENT INVENTORY SUMMARY ({len(documents)} documents)")

        lines.append("")
        lines.append("CLIENT/ENTITY DISTRIBUTION (use these as TOP-LEVEL folders):")
        for client, count in clients.most_common():
            lines.append(f"  {client}: {count} documents")

        lines.append("")
        lines.append("DOCUMENTS BY CLIENT AND CATEGORY:")
        for client, cat_counts in sorted(client_category.items()):
            lines.append(f"  {client}:")
            for cat, count in cat_counts.most_common():
                lines.append(f"    {cat}: {count}")

        lines.append("")
        lines.append("AI-CLASSIFIED CATEGORIES:")
        for cat, count in categories.most_common():
            lines.append(f"  {cat}: {count} documents")

        lines.append("")
        lines.append("AI-CLASSIFIED SUBCATEGORIES:")
        for subcat, count in subcategories.most_common(20):
            if subcat:
                lines.append(f"  {subcat}: {count} documents")

        lines.append("")
        lines.append("CURRENT FOLDER STRUCTURE:")
        for folder, count in current_folders.most_common():
            lines.append(f"  {folder}: {count} documents")

        lines.append("")
        lines.append("FILE TYPES:")
        for ext, count in extensions.most_common():
            lines.append(f"  {ext}: {count} files")

        return "\n".join(lines)

    def _format_all_documents(self, documents: list) -> str:
        """Format all documents for the AI prompt."""
        lines = []
        lines.append("FULL DOCUMENT LIST:")
        for doc in documents:
            lines.append(
                f"  - File: {doc.get('file_name', 'Unknown')}"
                f" | Client/Entity: {doc.get('ai_client_or_entity', 'Unknown')}"
                f" | Current: {doc.get('full_path', 'Unknown')}"
                f" | Category: {doc.get('ai_category', 'Unknown')}"
                f" | Subcategory: {doc.get('ai_subcategory', '')}"
                f" | Keywords: {doc.get('ai_keywords', '')}"
                f" | Sensitivity: {doc.get('ai_sensitivity_flag', 'unknown')}"
            )
        return "\n".join(lines)

    def _format_document_sample(self, documents: list,
                                 sample_size: int = 80) -> str:
        """Format a representative sample of documents."""
        # Take a stratified sample — some from each category
        by_category = {}
        for doc in documents:
            cat = doc.get("ai_category", "Unclassified")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(doc)

        sample = []
        per_category = max(1, sample_size // len(by_category))
        for cat, docs in by_category.items():
            sample.extend(docs[:per_category])

        # Fill remaining quota
        if len(sample) < sample_size:
            remaining = [d for d in documents if d not in sample]
            sample.extend(remaining[:sample_size - len(sample)])

        lines = []
        lines.append(f"DOCUMENT SAMPLE ({len(sample)} of {len(documents)}):")
        for doc in sample:
            lines.append(
                f"  - File: {doc.get('file_name', 'Unknown')}"
                f" | Client/Entity: {doc.get('ai_client_or_entity', 'Unknown')}"
                f" | Current: {doc.get('full_path', 'Unknown')}"
                f" | Category: {doc.get('ai_category', 'Unknown')}"
                f" | Subcategory: {doc.get('ai_subcategory', '')}"
                f" | Keywords: {doc.get('ai_keywords', '')}"
            )
        return "\n".join(lines)

    def _generate_proposals(self, summary: str, doc_details: str,
                            documents: list) -> dict:
        """Send the inventory to Azure OpenAI and get proposals."""
        user_message = (
            f"{summary}\n\n{doc_details}\n\n"
            f"Based on this inventory, propose two folder structures "
            f"as described in your instructions. Make sure every document "
            f"in the list gets an assignment in both proposals."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": ORGANIZER_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=16000,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            proposal = json.loads(result_text)

            logger.info("Folder structure proposals generated successfully")
            return proposal

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return self._fallback_proposal(documents)
        except Exception as e:
            logger.error(f"Failed to generate proposals: {e}")
            return self._fallback_proposal(documents)

    def _assign_remaining(self, proposal: dict, documents: list) -> dict:
        """Assign documents that weren't in the sample to the proposed structure."""
        # Get the list of already-assigned filenames
        assigned_clean = {
            a["file_name"]
            for a in proposal.get("clean_slate", {}).get("assignments", [])
        }
        assigned_incr = {
            a["file_name"]
            for a in proposal.get("incremental", {}).get("assignments", [])
        }

        unassigned = [
            d for d in documents
            if d.get("file_name") not in assigned_clean
        ]

        if not unassigned:
            return proposal

        logger.info(f"Assigning {len(unassigned)} remaining documents...")

        # Get the folder tree from clean_slate proposal
        folder_tree = proposal.get("clean_slate", {}).get("folder_tree", {})
        folder_list = self._flatten_tree(folder_tree)

        # Use AI to assign remaining docs in batches
        batch_size = 30
        for i in range(0, len(unassigned), batch_size):
            batch = unassigned[i:i + batch_size]
            batch_assignments = self._assign_batch(batch, folder_list)

            for plan_key in ["clean_slate", "incremental"]:
                if plan_key in proposal and "assignments" in proposal[plan_key]:
                    batch_result = batch_assignments.get(plan_key, [])
                    if isinstance(batch_result, dict):
                        batch_list = batch_result.get("assignments", [])
                    elif isinstance(batch_result, list):
                        batch_list = batch_result
                    else:
                        batch_list = []
                    proposal[plan_key]["assignments"].extend(
                        [a for a in batch_list if isinstance(a, dict)]
                    )

            time.sleep(0.5)

        return proposal

    def _assign_batch(self, documents: list, available_folders: list) -> dict:
        """Assign a batch of documents to the proposed folder structure."""
        doc_list = "\n".join(
            f"- {d.get('file_name')} | Client: {d.get('ai_client_or_entity', 'Unknown')} "
            f"| Category: {d.get('ai_category')} "
            f"| Current: {d.get('full_path')}"
            for d in documents
        )

        folder_options = "\n".join(f"- {f}" for f in available_folders)

        prompt = (
            f"Assign each document to the most appropriate folder. "
            f"IMPORTANT: Documents should go in folders matching their "
            f"CLIENT/ENTITY first, then by document type.\n\n"
            f"Available folders:\n{folder_options}\n\n"
            f"Documents to assign:\n{doc_list}\n\n"
            f"Return JSON with 'clean_slate' and 'incremental' keys, "
            f"each containing an 'assignments' list with file_name, "
            f"current_path, proposed_path, and reason."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You assign documents to folders. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Batch assignment failed: {e}")
            return {}

    def _flatten_tree(self, tree: dict, prefix: str = "") -> list:
        """Flatten a folder tree into a list of paths."""
        paths = []
        for name, info in tree.items():
            current = f"{prefix}/{name}" if prefix else name
            paths.append(current)
            subfolders = info.get("subfolders", {}) if isinstance(info, dict) else {}
            paths.extend(self._flatten_tree(subfolders, current))
        return paths

    def _fallback_proposal(self, documents: list) -> dict:
        """Generate a basic proposal using client-first, then category."""
        logger.info("Using fallback client-first organization...")

        # Group by client, then by category within each client
        client_categories = {}
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            cat = doc.get("ai_category", "Unclassified")
            if client not in client_categories:
                client_categories[client] = Counter()
            client_categories[client][cat] += 1

        folder_tree = {}
        for client, cat_counts in sorted(client_categories.items()):
            subfolders = {}
            for cat, count in cat_counts.most_common():
                subfolders[cat] = {
                    "description": f"{count} documents classified as {cat}",
                }
            folder_tree[client] = {
                "description": f"Documents for {client}",
                "subfolders": subfolders,
            }

        assignments = []
        for doc in documents:
            client = doc.get("ai_client_or_entity", "Unknown")
            category = doc.get("ai_category", "Unclassified")
            assignments.append({
                "file_name": doc.get("file_name", ""),
                "current_path": doc.get("full_path", ""),
                "proposed_path": f"{client}/{category}",
                "reason": f"{category} document for {client}",
            })

        return {
            "clean_slate": {
                "description": "Category-based organization (fallback)",
                "folder_tree": folder_tree,
                "assignments": assignments,
            },
            "incremental": {
                "description": "Category-based organization (fallback)",
                "folder_tree": folder_tree,
                "assignments": assignments,
            },
            "summary": {
                "total_documents": len(documents),
                "documents_that_would_move": len(documents),
                "new_folders_created": len(categories),
                "folders_consolidated": 0,
            },
        }

    def export_proposal(self, proposal: dict, output_dir: str) -> dict:
        """Export the organization proposal to JSON and readable text files.

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

        # Clean slate migration plan as CSV
        clean_csv = output_path / f"sp_migration_clean_{timestamp}.csv"
        assignments = [
            a for a in proposal.get("clean_slate", {}).get("assignments", [])
            if isinstance(a, dict)
        ]
        if assignments:
            with open(clean_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["file_name", "current_path",
                               "proposed_path", "reason"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(assignments)
            logger.info(f"Clean slate migration CSV: {clean_csv}")

        # Incremental migration plan as CSV
        incr_csv = output_path / f"sp_migration_incremental_{timestamp}.csv"
        assignments = [
            a for a in proposal.get("incremental", {}).get("assignments", [])
            if isinstance(a, dict)
        ]
        if assignments:
            with open(incr_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["file_name", "current_path",
                               "proposed_path", "reason"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(assignments)
            logger.info(f"Incremental migration CSV: {incr_csv}")

        return {
            "proposal_json": str(json_file),
            "clean_slate_csv": str(clean_csv),
            "incremental_csv": str(incr_csv),
        }
