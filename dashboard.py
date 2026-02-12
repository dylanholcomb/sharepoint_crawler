"""
SharePoint Reorganization Dashboard - Main Entry Point
A Streamlit multi-page app for managing SharePoint document reorganization.
Designed for California state agency IT administrators.
"""

import streamlit as st
import json
import csv
from io import StringIO, BytesIO
from typing import Optional, Dict, Any, List


# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="SharePoint Reorganization Dashboard",
    page_icon="📂",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# CUSTOM STYLING
# ============================================================================

def apply_custom_styling():
    """Apply professional, government-appropriate styling."""
    st.markdown(
        """
        <style>
        /* Main background */
        .main {
            background-color: #f8f9fa;
        }

        /* Sidebar styling */
        [data-testid="stSidebar"] {
            background-color: #ffffff;
            border-right: 1px solid #e0e0e0;
        }

        /* Headers */
        h1, h2, h3 {
            color: #1a1a1a;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }

        /* Status indicators */
        .status-connected {
            color: #2e8b57;
            font-weight: bold;
        }

        .status-disconnected {
            color: #dc3545;
            font-weight: bold;
        }

        /* Success messages */
        .success-box {
            padding: 12px;
            border-left: 4px solid #2e8b57;
            background-color: #f0f8f5;
            border-radius: 4px;
        }

        /* Info messages */
        .info-box {
            padding: 12px;
            border-left: 4px solid #0066cc;
            background-color: #f0f4f8;
            border-radius: 4px;
        }

        /* Warning messages */
        .warning-box {
            padding: 12px;
            border-left: 4px solid #ff9800;
            background-color: #fff8f0;
            border-radius: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_custom_styling()


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def initialize_session_state():
    """Initialize all required session state keys if not present."""
    defaults = {
        "proposal": None,
        "clean_assignments": [],
        "incremental_assignments": [],
        "approved_moves": set(),
        "rejected_moves": set(),
        "active_plan": "clean_slate",
        "authenticated": False,
        "migration_data": [],
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


initialize_session_state()


# ============================================================================
# AUTHENTICATION & SECRETS HELPERS
# ============================================================================

def check_admin_password() -> bool:
    """
    Check if admin password authentication is required and valid.
    Returns True if authenticated or no password is configured.
    """
    password_required = st.secrets.get("admin_password", "")

    # If no password configured, skip auth
    if not password_required:
        return True

    # If already authenticated, return True
    if st.session_state.get("authenticated", False):
        return True

    return False


def get_auth_client():
    """
    Build and return a GraphAuthClient from st.secrets.
    Returns None and displays error if secrets aren't configured.
    """
    try:
        from src.auth import GraphAuthClient

        tenant_id = st.secrets.get("azure_tenant_id", "")
        client_id = st.secrets.get("azure_client_id", "")
        client_secret = st.secrets.get("azure_client_secret", "")

        if not all([tenant_id, client_id, client_secret]):
            return None

        return GraphAuthClient(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    except Exception:
        return None


def check_connection_status() -> bool:
    """
    Check if Azure/SharePoint connection can be established.
    Returns True if connection is available, False otherwise.
    """
    auth_config = get_auth_client()
    return auth_config is not None


# ============================================================================
# FILE PARSING HELPERS
# ============================================================================

def parse_proposal_json(uploaded_file) -> Optional[Dict[str, Any]]:
    """
    Parse uploaded JSON proposal file.
    Returns the parsed proposal dict or None if parsing fails.
    """
    try:
        content = uploaded_file.read().decode("utf-8")
        proposal = json.loads(content)
        return proposal
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON format: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Error reading proposal file: {str(e)}")
        return None


def parse_migration_csv(uploaded_file) -> Optional[List[Dict[str, str]]]:
    """
    Parse uploaded CSV migration file.
    Returns list of dicts (one per row) or None if parsing fails.
    """
    try:
        content = uploaded_file.read().decode("utf-8")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        return rows if rows else None
    except Exception as e:
        st.error(f"Error reading CSV file {uploaded_file.name}: {str(e)}")
        return None


# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    # Header section
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; padding: 16px 0;">
            <h3 style="margin: 0; color: #1a1a1a;">Mosaic Data Solutions</h3>
            <p style="margin: 4px 0; font-size: 14px; color: #666;">SharePoint Reorganizer</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Authentication gate
    password_required = st.secrets.get("admin_password", "")
    if password_required:
        auth_header = st.empty()

        if not st.session_state.get("authenticated", False):
            auth_header.subheader("🔐 Authentication Required")
            password_input = st.text_input(
                "Admin Password",
                type="password",
                key="admin_password_input",
            )

            if st.button("Login", use_container_width=True):
                if password_input == password_required:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid password")
        else:
            auth_header.success("✓ Authenticated")
            if st.button("Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.rerun()

        st.markdown("---")
    else:
        # No password required
        st.session_state.authenticated = True

    # Only show file uploads if authenticated
    if st.session_state.get("authenticated", False):
        st.subheader("📋 Upload Files")

        # Proposal JSON uploader
        st.markdown("**Reorganization Proposal**")
        proposal_file = st.file_uploader(
            "Upload proposal JSON",
            type=["json"],
            key="proposal_uploader",
            help="JSON file containing the reorganization proposal structure",
        )

        if proposal_file:
            proposal = parse_proposal_json(proposal_file)
            if proposal:
                st.session_state.proposal = proposal
                st.success(f"✓ Proposal loaded")

        # Migration CSV uploader
        st.markdown("**Migration Data**")
        migration_files = st.file_uploader(
            "Upload migration CSVs",
            type=["csv"],
            accept_multiple_files=True,
            key="migration_uploader",
            help="CSV files containing migration assignments and metadata",
        )

        if migration_files:
            all_rows = []
            for mig_file in migration_files:
                rows = parse_migration_csv(mig_file)
                if rows:
                    all_rows.extend(rows)

            if all_rows:
                st.session_state.migration_data = all_rows
                st.success(f"✓ Loaded {len(all_rows)} rows from CSV(s)")

        st.markdown("---")

        # Connection status indicator
        st.markdown("**System Status**")
        is_connected = check_connection_status()
        status_text = "🟢 Connected" if is_connected else "🔴 Not Connected"
        status_class = "status-connected" if is_connected else "status-disconnected"
        st.markdown(
            f'<p class="{status_class}">{status_text}</p>',
            unsafe_allow_html=True,
        )

        if not is_connected:
            st.caption(
                "Azure/SharePoint credentials not configured. "
                "Check dashboard logs for details."
            )


# ============================================================================
# MAIN CONTENT AREA
# ============================================================================

st.title("📂 SharePoint Reorganization Dashboard")

# Only show content if authenticated
if not st.session_state.get("authenticated", False):
    st.warning("Please authenticate using the sidebar to access the dashboard.")
else:
    # Introduction text
    st.markdown(
        """
        Welcome to the SharePoint Reorganization Dashboard. This tool helps California state
        agency IT administrators plan, review, and execute large-scale SharePoint document
        reorganization migrations.

        **Use the navigation menu to:**
        - **Overview** — View the reorganization plan and statistics
        - **Review Moves** — Review and approve/reject individual document moves
        - **Execute** — Execute approved migrations
        """
    )

    st.markdown("---")

    # Status display
    col1, col2, col3 = st.columns(3)

    with col1:
        proposal = st.session_state.get("proposal")
        if proposal:
            doc_count = len(proposal.get("documents", []))
            st.metric("📄 Documents", doc_count)
        else:
            st.metric("📄 Documents", "—")

    with col2:
        migration_data = st.session_state.get("migration_data", [])
        st.metric("📊 Migration Rows", len(migration_data))

    with col3:
        approved = len(st.session_state.get("approved_moves", set()))
        st.metric("✓ Approved Moves", approved)

    st.markdown("---")

    # File status section
    st.subheader("📁 Loaded Files")

    col_proposal, col_migration = st.columns(2)

    with col_proposal:
        if st.session_state.get("proposal"):
            st.markdown(
                '<div class="success-box">✓ Reorganization proposal loaded</div>',
                unsafe_allow_html=True,
            )
            with st.expander("Proposal Details"):
                st.json(st.session_state.proposal, expanded=False)
        else:
            st.markdown(
                '<div class="info-box">📋 Upload a reorganization proposal (JSON) to get started</div>',
                unsafe_allow_html=True,
            )

    with col_migration:
        if st.session_state.get("migration_data"):
            st.markdown(
                f'<div class="success-box">✓ {len(st.session_state.migration_data)} migration rows loaded</div>',
                unsafe_allow_html=True,
            )
            with st.expander("First 5 Rows"):
                st.dataframe(
                    st.session_state.migration_data[:5],
                    use_container_width=True,
                    height=200,
                )
        else:
            st.markdown(
                '<div class="info-box">📊 Upload migration CSVs to populate migration data</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # Session state summary (for debugging)
    with st.expander("Session State (Debug)"):
        session_summary = {
            "authenticated": st.session_state.get("authenticated"),
            "active_plan": st.session_state.get("active_plan"),
            "approved_moves_count": len(st.session_state.get("approved_moves", set())),
            "rejected_moves_count": len(st.session_state.get("rejected_moves", set())),
            "clean_assignments_count": len(st.session_state.get("clean_assignments", [])),
            "incremental_assignments_count": len(st.session_state.get("incremental_assignments", [])),
        }
        st.json(session_summary)
