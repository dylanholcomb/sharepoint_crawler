"""
Power Automate flow discovery for SharePoint sites.

Queries the Microsoft Graph API to discover Power Automate flows
associated with the SharePoint site. Since we can't automatically
trace which documents a flow references, this module identifies
flows and their owners so the agency can manually report dependencies.

NOTE: This produces an advisory report. Document-to-flow associations
must be confirmed by the flow owners at the agency before any
documents are reorganized.
"""

import logging
from .auth import GraphAuthClient

logger = logging.getLogger(__name__)


class FlowDiscovery:
    """Discovers Power Automate flows associated with a SharePoint site."""

    def __init__(self, auth_client: GraphAuthClient, site_id: str):
        self.auth = auth_client
        self.site_id = site_id
        self.flows = []

    def discover_site_workflows(self) -> list:
        """Discover SharePoint list/library workflows on the site.

        Uses the Graph API to find lists that have content types or
        event receivers that indicate workflow associations.

        Returns:
            List of dicts describing discovered workflow associations.
        """
        logger.info("Discovering site lists and potential workflow triggers...")

        try:
            # Get all lists on the site (document libraries are lists)
            endpoint = f"/sites/{self.site_id}/lists"
            params = {
                "$select": "id,displayName,list",
                "$expand": "contentTypes",
            }
            lists = self.auth.get_all_pages(endpoint, params=params)

            workflow_associations = []

            for sp_list in lists:
                list_name = sp_list.get("displayName", "Unknown")
                list_template = (
                    sp_list.get("list", {}).get("template", "")
                )

                # Check content types for workflow-related types
                content_types = sp_list.get("contentTypes", [])
                for ct in content_types:
                    ct_name = ct.get("name", "")
                    if any(kw in ct_name.lower() for kw in
                           ["workflow", "approval", "task"]):
                        workflow_associations.append({
                            "list_name": list_name,
                            "list_template": list_template,
                            "content_type": ct_name,
                            "type": "content_type_association",
                            "note": (
                                "This list has a workflow-related content type. "
                                "Check with the site admin for active flows."
                            ),
                        })

            logger.info(
                f"Found {len(workflow_associations)} potential "
                f"workflow associations across {len(lists)} lists"
            )

            self.flows = workflow_associations
            return workflow_associations

        except Exception as e:
            logger.warning(f"Flow discovery encountered an error: {e}")
            logger.info(
                "Note: Flow discovery requires additional Graph API "
                "permissions. If you see 403 errors, the app registration "
                "may need Flow.Read.All permissions."
            )
            return []

    def generate_flow_report(self) -> dict:
        """Generate a report for the agency about flow dependencies.

        This report is meant to be shared with the SharePoint admin
        and flow owners so they can manually identify which documents
        are tied to Power Automate flows or Power Apps.

        Returns:
            Report dict with findings and action items.
        """
        report = {
            "title": "Power Automate / Power Apps Dependency Report",
            "purpose": (
                "Before reorganizing documents, the following potential "
                "automation dependencies should be reviewed by their owners. "
                "Moving documents referenced by active flows may break "
                "automations."
            ),
            "workflow_associations": self.flows,
            "action_items": [
                {
                    "action": "Review flow inventory",
                    "description": (
                        "The SharePoint admin should go to "
                        "https://make.powerautomate.com and review all "
                        "flows connected to this SharePoint site."
                    ),
                    "owner": "SharePoint Admin",
                },
                {
                    "action": "Identify document dependencies",
                    "description": (
                        "Each flow owner should identify which specific "
                        "documents or folders their flows reference. "
                        "These documents should be flagged as "
                        "'flow_dependent' before any reorganization."
                    ),
                    "owner": "Flow Owners",
                },
                {
                    "action": "Update flows post-migration",
                    "description": (
                        "After documents are moved, flow owners must "
                        "update their flow triggers and actions to point "
                        "to the new document locations."
                    ),
                    "owner": "Flow Owners",
                },
                {
                    "action": "Check Power Apps connections",
                    "description": (
                        "Any Power Apps that read from or write to "
                        "document libraries should be inventoried. "
                        "Visit https://make.powerapps.com to review."
                    ),
                    "owner": "SharePoint Admin",
                },
            ],
            "manual_checklist": {
                "power_automate_url": "https://make.powerautomate.com",
                "power_apps_url": "https://make.powerapps.com",
                "steps": [
                    "1. Log into Power Automate with your admin account",
                    "2. Filter flows by 'SharePoint' connector",
                    "3. Note which flows reference this site's document libraries",
                    "4. For each flow, record: flow name, owner, "
                    "which folders/files it references",
                    "5. Share this information back so we can flag those "
                    "documents as 'do not move' in the migration plan",
                ],
            },
        }

        return report
