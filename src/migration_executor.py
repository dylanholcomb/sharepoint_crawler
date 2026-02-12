"""
Migration Executor Module

Orchestrates the full SharePoint migration workflow including preflight checks,
folder creation, file moves, and comprehensive logging.
"""

import logging
import time
from typing import Dict, List, Optional, Generator, Any
from dataclasses import dataclass

from src.graph_operations import GraphOperations
from src.auth import GraphAuthClient


logger = logging.getLogger(__name__)


@dataclass
class Assignment:
    """Represents a file migration assignment."""
    file_name: str
    current_path: str
    proposed_path: str
    reason: str


class MigrationExecutor:
    """
    Orchestrates the complete migration workflow for SharePoint files.

    Handles preflight validation, dry runs, and execution of file moves with
    proper error handling and progress tracking.
    """

    def __init__(self, auth_client: GraphAuthClient, site_url: str):
        """
        Initialize the MigrationExecutor.

        Args:
            auth_client: GraphAuthClient instance for authentication
            site_url: Target SharePoint site URL

        Raises:
            ValueError: If site_url is invalid or site cannot be resolved
        """
        self.auth_client = auth_client
        self.site_url = site_url
        self.graph_ops = GraphOperations(auth_client)

        logger.info(f"Initializing MigrationExecutor for site: {site_url}")

        try:
            self.site_id, self.drive_id = self.graph_ops.resolve_site_and_drive(site_url)
            logger.info(f"Resolved site_id={self.site_id}, drive_id={self.drive_id}")
        except Exception as e:
            logger.error(f"Failed to initialize MigrationExecutor: {e}")
            raise ValueError(f"Cannot resolve site and drive: {e}") from e

    def preflight_check(self) -> Dict[str, Any]:
        """
        Perform preflight checks to validate connectivity and access.

        Returns:
            dict with keys:
                - success: bool, overall success status
                - site_name: str, name of the resolved site
                - drive_name: str, name of the resolved drive
                - issues: list, any issues found during checks
        """
        logger.info("Starting preflight checks")
        issues = []
        site_name = None
        drive_name = None

        # Check 1: Token validity
        try:
            token = self.auth_client.get_token()
            if not token:
                issues.append("Failed to obtain authentication token")
                logger.warning("Preflight: No valid token obtained")
            else:
                logger.info("Preflight: Token obtained successfully")
        except Exception as e:
            issues.append(f"Token retrieval failed: {e}")
            logger.error(f"Preflight: Token error: {e}")

        # Check 2: Site resolution (already done in __init__, verify it worked)
        if not self.site_id or not self.drive_id:
            issues.append("Site and/or drive IDs not resolved")
            logger.warning("Preflight: Site/drive resolution failed")
        else:
            logger.info(f"Preflight: Site and drive resolved successfully")

        # Check 3: Site metadata (attempt to get site name)
        try:
            # Attempt to resolve root folder to validate drive access
            root_folder = self.graph_ops.resolve_folder_path(self.drive_id, "")
            if root_folder:
                drive_name = "Drive (accessible)"
                site_name = self.site_url.split('/')[-1] or "SharePoint Site"
                logger.info("Preflight: Drive access verified")
            else:
                issues.append("Cannot access drive root")
                logger.warning("Preflight: Drive root not accessible")
        except Exception as e:
            issues.append(f"Drive access check failed: {e}")
            logger.error(f"Preflight: Drive access error: {e}")

        success = len(issues) == 0
        result = {
            "success": success,
            "site_name": site_name or self.site_url,
            "drive_name": drive_name or "Unknown",
            "issues": issues
        }

        logger.info(f"Preflight check complete: success={success}, issues={len(issues)}")
        return result

    def dry_run(self, assignments: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Perform a dry run to validate assignments without making changes.

        Args:
            assignments: List of dicts with keys:
                - file_name: str, name of the file
                - current_path: str, full SharePoint path to file
                - proposed_path: str, target folder path (without filename)
                - reason: str, reason for the move

        Returns:
            dict with keys:
                - can_proceed: bool, whether migration can proceed
                - files_found: int, number of files found
                - files_missing: int, number of files not found
                - folders_exist: int, number of target folders that exist
                - folders_to_create: int, number of folders needed
                - missing_files: list, file names that were not found
                - folders_needed: list, folder paths that would need creation
        """
        logger.info(f"Starting dry run with {len(assignments)} assignments")

        files_found = 0
        files_missing = 0
        missing_files = []
        folders_needed = set()
        folders_exist = 0

        for idx, assignment in enumerate(assignments):
            file_name = assignment.get("file_name", "")
            current_path = assignment.get("current_path", "")
            proposed_path = assignment.get("proposed_path", "")
            reason = assignment.get("reason", "")

            # Check if file exists
            try:
                item = self.graph_ops.find_item_by_path(self.drive_id, current_path)
                if item:
                    files_found += 1
                    logger.debug(f"Dry run: Found file '{file_name}' at '{current_path}'")
                else:
                    files_missing += 1
                    missing_files.append(file_name)
                    logger.warning(f"Dry run: File '{file_name}' not found at '{current_path}'")
            except Exception as e:
                files_missing += 1
                missing_files.append(file_name)
                logger.warning(f"Dry run: Error checking file '{file_name}': {e}")

            # Check if target folder exists
            try:
                folder_id = self.graph_ops.resolve_folder_path(self.drive_id, proposed_path)
                if folder_id:
                    folders_exist += 1
                    logger.debug(f"Dry run: Target folder '{proposed_path}' exists")
                else:
                    folders_needed.add(proposed_path)
                    logger.info(f"Dry run: Target folder '{proposed_path}' does not exist (will be created)")
            except Exception as e:
                folders_needed.add(proposed_path)
                logger.warning(f"Dry run: Error checking folder '{proposed_path}': {e}")

        can_proceed = files_missing == 0

        result = {
            "can_proceed": can_proceed,
            "files_found": files_found,
            "files_missing": files_missing,
            "folders_exist": folders_exist,
            "folders_to_create": len(folders_needed),
            "missing_files": missing_files,
            "folders_needed": sorted(list(folders_needed))
        }

        logger.info(
            f"Dry run complete: can_proceed={can_proceed}, "
            f"files_found={files_found}, files_missing={files_missing}, "
            f"folders_exist={folders_exist}, folders_to_create={len(folders_needed)}"
        )

        return result

    def execute_moves(
        self,
        assignments: List[Dict[str, str]],
        auto_create_folders: bool = True
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Execute the file migration.

        Yields progress updates as operations are performed. Handles folder
        creation, file moves, error handling, and throttling.

        Args:
            assignments: List of dicts with keys:
                - file_name: str, name of the file
                - current_path: str, full SharePoint path to file
                - proposed_path: str, target folder path (without filename)
                - reason: str, reason for the move
            auto_create_folders: bool, whether to create missing target folders

        Yields:
            dict with keys:
                - progress: float, 0.0-1.0 completion percentage
                - phase: str, "folders" or "moves"
                - status: str, "success", "error", or "skip"
                - file_name: str, name of current file (if applicable)
                - message: str, status message
                - current: int, current operation number
                - total: int, total operations
        """
        logger.info(f"Starting execute_moves with {len(assignments)} assignments")

        # Phase 1: Collect unique target folders
        target_folders = set()
        for assignment in assignments:
            proposed_path = assignment.get("proposed_path", "")
            if proposed_path:
                target_folders.add(proposed_path)

        target_folders = sorted(list(target_folders))
        logger.info(f"Identified {len(target_folders)} unique target folders")

        successes = 0
        failures = 0
        skips = 0
        created_folders = 0
        folder_creation_errors = []

        # Phase 1: Create target folders
        if auto_create_folders:
            logger.info(f"Phase 1: Creating {len(target_folders)} target folders")

            for idx, folder_path in enumerate(target_folders):
                try:
                    folder_id = self.graph_ops.create_folder_recursive(
                        self.drive_id,
                        folder_path
                    )
                    if folder_id:
                        created_folders += 1
                        logger.info(f"Created folder: '{folder_path}'")
                        yield {
                            "progress": (idx + 1) / len(target_folders),
                            "phase": "folders",
                            "status": "success",
                            "file_name": None,
                            "message": f"Created folder: {folder_path}",
                            "current": idx + 1,
                            "total": len(target_folders)
                        }
                    else:
                        folder_creation_errors.append(folder_path)
                        logger.error(f"Failed to create folder: '{folder_path}' (returned None)")
                        yield {
                            "progress": (idx + 1) / len(target_folders),
                            "phase": "folders",
                            "status": "error",
                            "file_name": None,
                            "message": f"Failed to create folder: {folder_path}",
                            "current": idx + 1,
                            "total": len(target_folders)
                        }
                except Exception as e:
                    folder_creation_errors.append(folder_path)
                    logger.error(f"Error creating folder '{folder_path}': {e}")
                    yield {
                        "progress": (idx + 1) / len(target_folders),
                        "phase": "folders",
                        "status": "error",
                        "file_name": None,
                        "message": f"Error creating folder {folder_path}: {str(e)}",
                        "current": idx + 1,
                        "total": len(target_folders)
                    }

        # Phase 2: Move files
        logger.info(f"Phase 2: Moving {len(assignments)} files")

        for idx, assignment in enumerate(assignments):
            file_name = assignment.get("file_name", "")
            current_path = assignment.get("current_path", "")
            proposed_path = assignment.get("proposed_path", "")
            reason = assignment.get("reason", "")

            try:
                # Find source file
                source_item = self.graph_ops.find_item_by_path(self.drive_id, current_path)
                if not source_item:
                    skips += 1
                    logger.warning(f"File not found: '{current_path}' (skipping)")
                    yield {
                        "progress": (idx + 1) / len(assignments),
                        "phase": "moves",
                        "status": "skip",
                        "file_name": file_name,
                        "message": f"Source file not found: {current_path}",
                        "current": idx + 1,
                        "total": len(assignments)
                    }
                    continue

                source_item_id = source_item.get("id")

                # Find target folder
                target_folder = self.graph_ops.resolve_folder_path(
                    self.drive_id,
                    proposed_path
                )
                if not target_folder:
                    failures += 1
                    logger.error(f"Target folder not found: '{proposed_path}' for file '{file_name}'")
                    yield {
                        "progress": (idx + 1) / len(assignments),
                        "phase": "moves",
                        "status": "error",
                        "file_name": file_name,
                        "message": f"Target folder not found: {proposed_path}",
                        "current": idx + 1,
                        "total": len(assignments)
                    }
                    continue

                # Move the file
                moved_item = self.graph_ops.move_file(
                    self.drive_id,
                    source_item_id,
                    target_folder
                )

                if moved_item:
                    successes += 1
                    logger.info(
                        f"Moved file '{file_name}' from '{current_path}' to '{proposed_path}'"
                    )
                    yield {
                        "progress": (idx + 1) / len(assignments),
                        "phase": "moves",
                        "status": "success",
                        "file_name": file_name,
                        "message": f"Moved to: {proposed_path}",
                        "current": idx + 1,
                        "total": len(assignments)
                    }
                else:
                    failures += 1
                    logger.error(f"Failed to move file '{file_name}' (move_file returned None)")
                    yield {
                        "progress": (idx + 1) / len(assignments),
                        "phase": "moves",
                        "status": "error",
                        "file_name": file_name,
                        "message": f"Failed to move file {file_name}",
                        "current": idx + 1,
                        "total": len(assignments)
                    }

                # Throttle to avoid rate limiting
                time.sleep(0.3)

            except Exception as e:
                failures += 1
                logger.error(f"Exception moving file '{file_name}': {e}")
                yield {
                    "progress": (idx + 1) / len(assignments),
                    "phase": "moves",
                    "status": "error",
                    "file_name": file_name,
                    "message": f"Error: {str(e)}",
                    "current": idx + 1,
                    "total": len(assignments)
                }

        # Final summary
        total_operations = successes + failures + skips
        logger.info(
            f"Migration complete: successes={successes}, failures={failures}, skips={skips}"
        )

        yield {
            "progress": 1.0,
            "phase": "summary",
            "status": "complete",
            "file_name": None,
            "message": "Migration completed",
            "current": total_operations,
            "total": total_operations,
            "summary": {
                "successes": successes,
                "failures": failures,
                "skips": skips,
                "folders_created": created_folders,
                "folder_errors": len(folder_creation_errors),
                "total_assignments": len(assignments)
            }
        }
