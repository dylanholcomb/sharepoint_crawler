"""
Export crawl results to CSV and JSON formats.

Generates structured output files from the document metadata collected
by the SharePoint crawler, including summary statistics.
"""

import csv
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CrawlExporter:
    """Exports crawl results to CSV and JSON files with summary stats."""

    # Column order for CSV output
    CSV_COLUMNS = [
        "file_name",
        "extension",
        "size_bytes",
        "size_readable",
        "mime_type",
        "library_name",
        "folder_path",
        "full_path",
        "depth",
        "created_date",
        "modified_date",
        "created_by",
        "modified_by",
        "web_url",
        "item_id",
    ]

    def __init__(self, documents: list, stats: dict, output_dir: str = "."):
        self.documents = documents
        self.stats = stats
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate a timestamp for filenames
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def export_csv(self) -> str:
        """Export document metadata to a CSV file.

        Returns:
            Path to the created CSV file.
        """
        filename = f"sp_crawl_{self.timestamp}.csv"
        filepath = self.output_dir / filename

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=self.CSV_COLUMNS, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(self.documents)

        logger.info(f"CSV exported: {filepath} ({len(self.documents)} rows)")
        return str(filepath)

    def export_json(self) -> str:
        """Export document metadata and summary to a JSON file.

        Returns:
            Path to the created JSON file.
        """
        filename = f"sp_crawl_{self.timestamp}.json"
        filepath = self.output_dir / filename

        summary = self._generate_summary()

        output = {
            "crawl_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_documents": len(self.documents),
                "stats": self.stats,
            },
            "summary": summary,
            "documents": self.documents,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)

        logger.info(f"JSON exported: {filepath}")
        return str(filepath)

    def export_structure_map(self) -> str:
        """Export a visual tree of the current folder structure.

        Produces a text file showing the folder hierarchy as an
        indented tree, which is useful for comparing before/after
        organization.

        Returns:
            Path to the created text file.
        """
        filename = f"sp_structure_{self.timestamp}.txt"
        filepath = self.output_dir / filename

        # Build the tree from document paths
        tree = {}
        for doc in self.documents:
            parts = doc["full_path"].split("/")
            current = tree
            for part in parts[:-1]:  # Exclude the filename
                if part not in current:
                    current[part] = {}
                current = current[part]
            # Mark files with their size
            current[parts[-1]] = doc["size_readable"]

        lines = []
        lines.append("SharePoint Document Structure")
        lines.append("=" * 50)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Total documents: {len(self.documents)}")
        lines.append("=" * 50)
        lines.append("")

        self._render_tree(tree, lines, prefix="")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Structure map exported: {filepath}")
        return str(filepath)

    def _render_tree(self, node: dict, lines: list, prefix: str):
        """Recursively render the folder tree as indented text."""
        entries = sorted(node.keys())

        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "`-- " if is_last else "|-- "
            child_prefix = "    " if is_last else "|   "

            value = node[name]
            if isinstance(value, dict):
                # It's a folder
                file_count = self._count_files(value)
                lines.append(f"{prefix}{connector}{name}/ ({file_count} files)")
                self._render_tree(value, lines, prefix + child_prefix)
            else:
                # It's a file (value is the size)
                lines.append(f"{prefix}{connector}{name} [{value}]")

    def _count_files(self, node: dict) -> int:
        """Count total files under a folder node."""
        count = 0
        for value in node.values():
            if isinstance(value, dict):
                count += self._count_files(value)
            else:
                count += 1
        return count

    def _generate_summary(self) -> dict:
        """Generate summary statistics about the crawled documents."""
        if not self.documents:
            return {"message": "No documents found"}

        # File type distribution
        ext_counts = Counter(doc["extension"] for doc in self.documents)

        # Size statistics
        sizes = [doc["size_bytes"] for doc in self.documents]
        total_size = sum(sizes)

        # Depth analysis
        depths = [doc["depth"] for doc in self.documents]
        max_depth = max(depths) if depths else 0
        avg_depth = sum(depths) / len(depths) if depths else 0

        # Library distribution
        lib_counts = Counter(doc["library_name"] for doc in self.documents)

        # Author distribution (top 10)
        author_counts = Counter(doc["created_by"] for doc in self.documents)

        # Folder analysis — identify potential problem areas
        folder_counts = Counter(doc["folder_path"] for doc in self.documents)
        large_folders = {
            path: count
            for path, count in folder_counts.most_common(20)
            if count > 20
        }

        deep_files = [
            doc["full_path"] for doc in self.documents if doc["depth"] > 5
        ]

        return {
            "file_types": dict(ext_counts.most_common()),
            "total_size_bytes": total_size,
            "total_size_readable": self._format_size(total_size),
            "avg_file_size_readable": self._format_size(
                total_size // len(self.documents) if self.documents else 0
            ),
            "max_folder_depth": max_depth,
            "avg_folder_depth": round(avg_depth, 1),
            "documents_per_library": dict(lib_counts),
            "top_authors": dict(author_counts.most_common(10)),
            "potential_issues": {
                "overstuffed_folders": large_folders,
                "deeply_nested_files_count": len(deep_files),
                "deeply_nested_examples": deep_files[:10],
            },
        }

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Convert bytes to human-readable string."""
        if size_bytes == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        return f"{size:.1f} {units[i]}"
