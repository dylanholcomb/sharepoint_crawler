"""
SharePoint Online authentication via Microsoft Graph API.

Uses MSAL (Microsoft Authentication Library) with client credentials flow
(app-only authentication) to get an access token for Microsoft Graph.
"""

import sys
import msal
import requests


class GraphAuthClient:
    """Handles authentication and authorized requests to Microsoft Graph API."""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    SCOPE = ["https://graph.microsoft.com/.default"]

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None

        self._app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )

    def get_token(self) -> str:
        """Acquire an access token using client credentials flow."""
        result = self._app.acquire_token_for_client(scopes=self.SCOPE)

        if "access_token" in result:
            self._token = result["access_token"]
            return self._token

        error = result.get("error", "unknown_error")
        error_desc = result.get("error_description", "No description available")
        raise RuntimeError(
            f"Failed to acquire token.\n  Error: {error}\n  Description: {error_desc}"
        )

    @property
    def headers(self) -> dict:
        """Return authorization headers, refreshing the token if needed."""
        if not self._token:
            self.get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def get(self, endpoint: str, params: dict = None) -> dict:
        """Make an authenticated GET request to Microsoft Graph.

        Args:
            endpoint: Graph API endpoint path (e.g., '/sites/...')
                      or a full URL (for pagination @odata.nextLink).
            params: Optional query parameters.

        Returns:
            Parsed JSON response as a dictionary.
        """
        if endpoint.startswith("https://"):
            url = endpoint
        else:
            url = f"{self.GRAPH_BASE_URL}{endpoint}"

        response = requests.get(url, headers=self.headers, params=params, timeout=30)

        if response.status_code == 401:
            # Token may have expired — refresh and retry once
            self.get_token()
            response = requests.get(
                url, headers=self.headers, params=params, timeout=30
            )

        response.raise_for_status()
        return response.json()

    def get_all_pages(self, endpoint: str, params: dict = None) -> list:
        """Follow pagination to retrieve all results from a Graph API endpoint.

        Microsoft Graph returns paginated results with @odata.nextLink.
        This method follows all pages and returns the combined 'value' list.

        Args:
            endpoint: Graph API endpoint path.
            params: Optional query parameters.

        Returns:
            Combined list of all items across all pages.
        """
        all_items = []
        data = self.get(endpoint, params=params)
        all_items.extend(data.get("value", []))

        while "@odata.nextLink" in data:
            data = self.get(data["@odata.nextLink"])
            all_items.extend(data.get("value", []))

        return all_items

    def test_connection(self, site_url: str) -> dict:
        """Test the connection by resolving a SharePoint site.

        Args:
            site_url: Full SharePoint site URL
                      (e.g., https://tenant.sharepoint.com/sites/MySite)

        Returns:
            Site information dict from Graph API, or raises on failure.
        """
        # Parse the site URL into Graph API format
        # Input:  https://tenant.sharepoint.com/sites/MySite
        # Output: /sites/tenant.sharepoint.com:/sites/MySite
        from urllib.parse import urlparse

        parsed = urlparse(site_url)
        hostname = parsed.netloc  # e.g., tenant.sharepoint.com
        site_path = parsed.path.rstrip("/")  # e.g., /sites/MySite

        endpoint = f"/sites/{hostname}:{site_path}"
        site_info = self.get(endpoint)

        return site_info
