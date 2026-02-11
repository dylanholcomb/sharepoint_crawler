"""
SharePoint Online document crawler using Microsoft Graph API.

Recursively traverses all document libraries, folders, and files on a
SharePoint site, collecting metadata for every document found.
"""

import logging
from datetime import datetime
from urllib.parse import urlparse

from .auth import GraphAuthClient

logger = logging.getLogger(__name__)


class SharePointCrawler:
    """Crawls a SharePoint Online site and collects document metadata."""

    # File extensions we consider "documents" vs system/config files
    DOCUMENT_EXTENSIONS = {
        # Office documents
        ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".one", ".onetoc2", ".vsdx", ".vsd",
        # PDF
        ".pdf",
        # Text / markup
        ".txt", ".rtf", ".csv", ".md", ".html", ".htm", ".xml",
        # Images (may be relevant for some agencies)
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg",
        # Other common formats
        ".zip", ".msg", ".eml",
    }

    def __init__(self, auth_client: GraphAuthClient, site_url: str):
        self.auth = auth_client
        self.site_url = site_url.rstrip("/")
        self.site_id = None
        self.documents = []
        self.stats = {
            "libraries_found": 0,
            "folders_traversed": 0,
            "files_found": 0,
            "files_skipped": 0,
            "errors": 0,
        }

    def _resolve_site(self):
        """Resolve the SharePoint site URL to a Graph site ID."""
        parsed = urlparse(self.site_url)
        hostname = parsed.netloc
        site_path = parsed.path.rstrip("/")

        endpoint = f"/sites/{hostname}:{site_path}"
        site_info = self.auth.get(endpoint)

        self.site_id = site_info["id"]
        site_name = site_info.get("displayName", "Unknown")
        logger.info(f"Resolved site: {site_name} (ID: {self.site_id})")

        return site_info

    def _get_document_libraries(self) -> list:
        """Get all document libraries (drives) on the site."""
        endpoint = f"/sites/{self.site_id}/drives"
        drives = self.auth.get_all_pages(endpoint)

        # Filter to only documentLibrary type drives
        doc_libraries = [
            d for d in drives if d.get("driveType") == "documentLibrary"
        ]

        self.stats["libraries_found"] = len(doc_libraries)
        logger.info(f"Found {len(doc_libraries)} document libraries")

        for lib in doc_libraries:
            logger.info(f"  - {lib.get('name', 'Unnamed')} ({lib['id'][:8]}...)")

        return doc_libraries

    def _crawl_folder(
        self,
        drive_id: str,
        folder_path: str,
        library_name: str,
        depth: int = 0,
        folder_id: str = None,
    ):
        """Recursively crawl a folder and its subfolders.

        Uses item ID-based traversal instead of path-based URLs to avoid
        issues with special characters (#, %, etc.) in folder names.

        Args:
            drive_id: The Graph drive ID for this document library.
            folder_path: Current folder path (for display/metadata only).
            library_name: Human-readable name of the document library.
            depth: Current folder nesting depth (0 = library root).
            folder_id: Graph item ID of the folder (None = drive root).
        """
        self.stats["folders_traversed"] += 1

        # Use item ID-based endpoint to avoid URL encoding issues with
        # special characters like # in folder names
        if folder_id is None:
            endpoint = f"/drives/{drive_id}/root/children"
        else:
            endpoint = f"/drives/{drive_id}/items/{folder_id}/children"

        # Request specific fields to reduce payload
        params = {
            "$select": (
                "id,name,size,file,folder,createdDateTime,lastModifiedDateTime,"
                "createdBy,lastModifiedBy,webUrl,parentReference"
            ),
            "$top": "200",
        }

        try:
            items = self.auth.get_all_pages(endpoint, params=params)
        except Exception as e:
            logger.error(f"Error crawling {library_name}{folder_path}: {e}")
            self.stats["errors"] += 1
            return

        for item in items:
            if "folder" in item:
                # It's a folder — recurse using the item's ID
                child_count = item["folder"].get("childCount", 0)
                subfolder_name = item["name"]
                subfolder_id = item["id"]

                if folder_path == "/":
                    subfolder_path = f"/{subfolder_name}"
                else:
                    subfolder_path = f"{folder_path}/{subfolder_name}"

                logger.debug(
                    f"{'  ' * depth}[Folder] {subfolder_name} "
                    f"({child_count} items)"
                )

                self._crawl_folder(
                    drive_id=drive_id,
                    folder_path=subfolder_path,
                    library_name=library_name,
                    depth=depth + 1,
                    folder_id=subfolder_id,
                )

            elif "file" in item:
                # It's a file — extract metadata
                self._process_file(item, library_name, folder_path, depth)

    def _process_file(
        self, item: dict, library_name: str, folder_path: str, depth: int
    ):
        """Extract metadata from a file item and add it to the results.

        Args:
            item: Graph API driveItem dict for the file.
            library_name: Name of the parent document library.
            folder_path: Path of the containing folder.
            depth: Folder nesting depth.
        """
        file_name = item.get("name", "Unknown")
        extension = ""
        if "." in file_name:
            extension = "." + file_name.rsplit(".", 1)[-1].lower()

        # Extract author information safely
        created_by = (
            item.get("createdBy", {})
            .get("user", {})
            .get("displayName", "Unknown")
        )
        modified_by = (
            item.get("lastModifiedBy", {})
            .get("user", {})
            .get("displayName", "Unknown")
        )

        # Build the full SharePoint path
        parent_path = (
            item.get("parentReference", {}).get("path", "")
        )

        doc_record = {
            "file_name": file_name,
            "extension": extension,
            "size_bytes": item.get("size", 0),
            "size_readable": self._format_size(item.get("size", 0)),
            "mime_type": item.get("file", {}).get("mimeType", ""),
            "library_name": library_name,
            "folder_path": folder_path if folder_path != "/" else "/",
            "full_path": f"{library_name}{folder_path}/{file_name}",
            "depth": depth,
            "created_date": item.get("createdDateTime", ""),
            "modified_date": item.get("lastModifiedDateTime", ""),
            "created_by": created_by,
            "modified_by": modified_by,
            "web_url": item.get("webUrl", ""),
            "item_id": item.get("id", ""),
            "drive_item_path": parent_path,
        }

        self.documents.append(doc_record)
        self.stats["files_found"] += 1

        logger.debug(
            f"{'  ' * depth}[File] {file_name} "
            f"({doc_record['size_readable']}, {extension})"
        )

    def crawl(self) -> list:
        """Execute the full crawl of the SharePoint site.

        Returns:
            List of document metadata dictionaries.
        """
        start_time = datetime.now()
        logger.info(f"Starting crawl of {self.site_url}")
        logger.info("=" * 60)

        # Step 1: Resolve the site
        self._resolve_site()

        # Step 2: Get all document libraries
        libraries = self._get_document_libraries()

        # Step 3: Crawl each library
        for lib in libraries:
            drive_id = lib["id"]
            lib_name = lib.get("name", "Unnamed Library")

            logger.info(f"\nCrawling library: {lib_name}")
            logger.info("-" * 40)

            self._crawl_folder(
                drive_id=drive_id,
                folder_path="/",
                library_name=lib_name,
                depth=0,
            )

        elapsed = (datetime.now() - start_time).total_seconds()

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("CRAWL COMPLETE")
        logger.info(f"  Time elapsed:       {elapsed:.1f} seconds")
        logger.info(f"  Libraries found:    {self.stats['libraries_found']}")
        logger.info(f"  Folders traversed:  {self.stats['folders_traversed']}")
        logger.info(f"  Files found:        {self.stats['files_found']}")
        logger.info(f"  Errors:             {self.stats['errors']}")
        logger.info("=" * 60)

        return self.documents

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Convert bytes to a human-readable string."""
        if size_bytes == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        return f"{size:.1f} {units[i]}"
