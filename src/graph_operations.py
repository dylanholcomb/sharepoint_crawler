"""
Graph API wrapper for SharePoint file operations.

This module provides a GraphOperations class that handles common SharePoint
file operations through the Microsoft Graph API, including folder creation,
file movement, and path resolution.
"""

import logging
from typing import Optional, Tuple
from urllib.parse import quote

from src.auth import GraphAuthClient

logger = logging.getLogger(__name__)


class GraphOperations:
    """Wrapper for SharePoint Graph API operations."""

    def __init__(self, auth_client: GraphAuthClient) -> None:
        """
        Initialize GraphOperations with an authenticated client.

        Args:
            auth_client: GraphAuthClient instance for authenticated API calls.
        """
        self.auth_client = auth_client
        logger.debug("GraphOperations initialized with auth client")

    def resolve_site_and_drive(self, site_url: str) -> Tuple[str, str]:
        """
        Resolve a SharePoint site URL to site ID and primary drive ID.

        Args:
            site_url: SharePoint site URL (e.g., https://tenant.sharepoint.com/sites/mysite)

        Returns:
            Tuple of (site_id, drive_id) for the primary document library.

        Raises:
            ValueError: If site cannot be resolved or no document library found.
        """
        logger.info(f"Resolving site URL: {site_url}")

        try:
            # Test connection and get site info
            site_info = self.auth_client.test_connection(site_url)
            if not site_info or "id" not in site_info:
                logger.error(f"Failed to resolve site {site_url}")
                raise ValueError(f"Cannot resolve site: {site_url}")

            site_id = site_info["id"]
            logger.debug(f"Resolved site_id: {site_id}")

            # Get the primary document library
            drives_endpoint = f"/sites/{site_id}/drives"
            drives = self.auth_client.get(drives_endpoint, {})

            if not drives or "value" not in drives:
                logger.error(f"No drives found for site {site_id}")
                raise ValueError(f"No drives found for site: {site_url}")

            # Find the primary document library
            for drive in drives["value"]:
                if drive.get("driveType") == "documentLibrary":
                    drive_id = drive["id"]
                    logger.info(
                        f"Resolved site_id={site_id}, drive_id={drive_id}"
                    )
                    return site_id, drive_id

            logger.error(
                f"No document library drive found for site {site_id}"
            )
            raise ValueError(
                f"No document library found for site: {site_url}"
            )

        except Exception as e:
            logger.error(f"Error resolving site and drive: {e}", exc_info=True)
            raise

    def resolve_folder_path(self, drive_id: str, path: str) -> Optional[str]:
        """
        Resolve a folder path to its item ID.

        Walks the path segment by segment, starting from the root folder.
        Returns the final folder's item ID or None if any segment is not found.

        Args:
            drive_id: The drive ID to search in.
            path: Folder path (e.g., "Finance/Budget Reports").

        Returns:
            The item ID of the final folder, or None if path doesn't exist.
        """
        logger.debug(f"Resolving folder path: {path} in drive {drive_id}")

        try:
            # Start from root
            root_endpoint = f"/drives/{drive_id}/root"
            root_response = self.auth_client.get(root_endpoint, {})

            if not root_response or "id" not in root_response:
                logger.error(f"Failed to get root folder for drive {drive_id}")
                return None

            current_id = root_response["id"]
            logger.debug(f"Root folder ID: {current_id}")

            # Walk each segment
            segments = [s.strip() for s in path.split("/") if s.strip()]

            for segment in segments:
                logger.debug(f"Looking for segment: {segment}")

                # Search for child with matching name
                children_endpoint = f"/drives/{drive_id}/items/{current_id}/children"
                filter_param = f"name eq '{segment}'"

                try:
                    children = self.auth_client.get(
                        children_endpoint, {"$filter": filter_param}
                    )
                except Exception as e:
                    logger.warning(
                        f"Error searching for segment '{segment}': {e}"
                    )
                    return None

                if not children or "value" not in children or not children[
                    "value"
                ]:
                    logger.debug(f"Segment '{segment}' not found")
                    return None

                # Use the first match (should be unique)
                current_id = children["value"][0]["id"]
                logger.debug(f"Found segment '{segment}', ID: {current_id}")

            logger.info(f"Successfully resolved path '{path}' to ID: {current_id}")
            return current_id

        except Exception as e:
            logger.error(
                f"Error resolving folder path '{path}': {e}", exc_info=True
            )
            return None

    def create_folder_recursive(self, drive_id: str, path: str) -> str:
        """
        Create a folder path recursively, creating missing parent folders.

        Args:
            drive_id: The drive ID where folder should be created.
            path: Folder path (e.g., "Finance/Budget Reports").

        Returns:
            The item ID of the final (or existing) folder.

        Raises:
            ValueError: If folder creation fails.
        """
        logger.info(f"Creating folder path: {path} in drive {drive_id}")

        try:
            # Start from root
            root_endpoint = f"/drives/{drive_id}/root"
            root_response = self.auth_client.get(root_endpoint, {})

            if not root_response or "id" not in root_response:
                logger.error(f"Failed to get root folder for drive {drive_id}")
                raise ValueError(
                    f"Cannot access root folder of drive {drive_id}"
                )

            current_id = root_response["id"]
            segments = [s.strip() for s in path.split("/") if s.strip()]

            for segment in segments:
                logger.debug(f"Processing segment: {segment}")

                # Try to find existing folder
                existing_id = self._find_child_by_name(
                    drive_id, current_id, segment
                )

                if existing_id:
                    logger.debug(
                        f"Folder '{segment}' already exists, ID: {existing_id}"
                    )
                    current_id = existing_id
                else:
                    # Create new folder
                    logger.debug(f"Creating folder: {segment}")
                    new_folder = self._create_folder(
                        drive_id, current_id, segment
                    )

                    if not new_folder or "id" not in new_folder:
                        logger.error(f"Failed to create folder '{segment}'")
                        raise ValueError(f"Failed to create folder: {segment}")

                    current_id = new_folder["id"]
                    logger.info(
                        f"Created folder '{segment}', ID: {current_id}"
                    )

            logger.info(
                f"Successfully created/resolved path '{path}' with ID: {current_id}"
            )
            return current_id

        except Exception as e:
            logger.error(
                f"Error creating folder path '{path}': {e}", exc_info=True
            )
            raise

    def move_file(
        self, drive_id: str, item_id: str, target_folder_id: str
    ) -> dict:
        """
        Move a file to a target folder.

        Args:
            drive_id: The drive ID containing the file.
            item_id: The item ID of the file to move.
            target_folder_id: The item ID of the target folder.

        Returns:
            The updated item response from the API.

        Raises:
            ValueError: If move operation fails.
        """
        logger.info(
            f"Moving item {item_id} to folder {target_folder_id} in drive {drive_id}"
        )

        try:
            endpoint = f"/drives/{drive_id}/items/{item_id}"
            body = {"parentReference": {"id": target_folder_id}}

            response = self.auth_client.patch(endpoint, body)

            if not response or "id" not in response:
                logger.error(f"Failed to move item {item_id}")
                raise ValueError(f"Failed to move item {item_id}")

            logger.info(f"Successfully moved item {item_id}")
            return response

        except Exception as e:
            logger.error(
                f"Error moving item {item_id}: {e}", exc_info=True
            )
            raise

    def find_item_by_path(self, drive_id: str, path: str) -> Optional[dict]:
        """
        Find an item by its full path.

        Uses the path-based lookup endpoint which is more efficient for
        known paths. Handles URL encoding for special characters.

        Args:
            drive_id: The drive ID to search in.
            path: Full path to item (e.g., "Finance/Budget Reports/Q1.xlsx").

        Returns:
            The item dict from the API, or None if not found.
        """
        logger.debug(f"Finding item by path: {path} in drive {drive_id}")

        try:
            # URL encode the path for special characters
            encoded_path = quote(path, safe="/")
            endpoint = f"/drives/{drive_id}/root:/{encoded_path}"

            response = self.auth_client.get(endpoint, {})

            if not response or "id" not in response:
                logger.debug(f"Item not found at path: {path}")
                return None

            logger.info(f"Found item at path '{path}', ID: {response['id']}")
            return response

        except Exception as e:
            logger.debug(f"Error finding item by path '{path}': {e}")
            return None

    def _find_child_by_name(
        self, drive_id: str, parent_id: str, name: str
    ) -> Optional[str]:
        """
        Find a child item by name in a parent folder.

        Helper method for finding existing folders or files.

        Args:
            drive_id: The drive ID to search in.
            parent_id: The parent folder's item ID.
            name: The name to search for.

        Returns:
            The item ID if found, None otherwise.
        """
        try:
            endpoint = f"/drives/{drive_id}/items/{parent_id}/children"
            filter_param = f"name eq '{name}'"
            response = self.auth_client.get(endpoint, {"$filter": filter_param})

            if response and "value" in response and response["value"]:
                return response["value"][0]["id"]

            return None

        except Exception as e:
            logger.debug(
                f"Error finding child '{name}' in parent {parent_id}: {e}"
            )
            return None

    def _create_folder(
        self, drive_id: str, parent_id: str, name: str
    ) -> Optional[dict]:
        """
        Create a new folder in a parent directory.

        Helper method that handles folder creation with conflict resolution.

        Args:
            drive_id: The drive ID where folder should be created.
            parent_id: The parent folder's item ID.
            name: The folder name to create.

        Returns:
            The created item response, or None if creation fails.
        """
        try:
            endpoint = f"/drives/{drive_id}/items/{parent_id}/children"
            body = {
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            }

            response = self.auth_client.post(endpoint, body)
            return response if response else None

        except Exception as e:
            logger.warning(f"Error creating folder '{name}': {e}")
            return None
