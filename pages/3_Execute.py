import streamlit as st
import time

from src.auth import GraphAuthClient
from src.migration_executor import MigrationExecutor


st.title("Execute Migration")

# Initialize session state
if "proposal" not in st.session_state:
    st.session_state["proposal"] = None
if "active_plan" not in st.session_state:
    st.session_state["active_plan"] = "clean_slate"
if "approved_moves" not in st.session_state:
    st.session_state["approved_moves"] = set()
if "execution_results" not in st.session_state:
    st.session_state["execution_results"] = None
if "test_connection_result" not in st.session_state:
    st.session_state["test_connection_result"] = None

# Check if proposal is loaded
if st.session_state["proposal"] is None:
    st.warning("No proposal loaded. Please upload a proposal from the main dashboard page.")
    st.stop()

# Check if any moves are approved
if not st.session_state["approved_moves"]:
    st.warning("No approved moves found. Please go to 'Review Moves' to approve some moves first.")
    st.stop()

proposal = st.session_state["proposal"]
active_plan = st.session_state["active_plan"]
approved_moves = st.session_state["approved_moves"]

# Get assignments from the selected plan
all_assignments = proposal.get(active_plan, {}).get("assignments", [])

# Filter to only approved moves (only dicts with file_name)
approved_assignments = [
    a for a in all_assignments
    if isinstance(a, dict) and a.get("file_name") in approved_moves
]

# Summary section
st.subheader("Migration Summary")
plan_label = "Clean Slate" if active_plan == "clean_slate" else "Incremental"
st.info(f"**{len(approved_assignments)} approved moves** from the **{plan_label}** plan ready to execute.")

# Table showing approved moves
if approved_assignments:
    st.subheader("Approved Moves")
    with st.container(border=True):
        header_cols = st.columns([2, 3, 3, 2])
        header_cols[0].write("**Filename**")
        header_cols[1].write("**Current Path**")
        header_cols[2].write("**Proposed Path**")
        header_cols[3].write("**Reason**")

        for assignment in approved_assignments[:50]:  # Show first 50
            row = st.columns([2, 3, 3, 2])
            row[0].caption(assignment.get("file_name", ""))
            row[1].caption(assignment.get("current_path", ""))
            row[2].caption(assignment.get("proposed_path", ""))
            row[3].caption(assignment.get("reason", ""))

        if len(approved_assignments) > 50:
            st.caption(f"... and {len(approved_assignments) - 50} more")

st.divider()

# Preflight Check section
st.subheader("Preflight Check")

# Check if secrets are configured
try:
    tenant_id = st.secrets.get("azure_tenant_id")
    client_id = st.secrets.get("azure_client_id")
    client_secret = st.secrets.get("azure_client_secret")
    sp_site_url = st.secrets.get("sp_site_url")
    secrets_configured = all([tenant_id, client_id, client_secret, sp_site_url])
except Exception:
    secrets_configured = False

if not secrets_configured:
    st.error(
        "Streamlit secrets not configured. "
        "Add azure_tenant_id, azure_client_id, azure_client_secret, and sp_site_url "
        "to your Streamlit secrets (Settings → Secrets on Streamlit Cloud, "
        "or .streamlit/secrets.toml locally)."
    )
    st.stop()

# Test connection button
if st.button("Test SharePoint Connection"):
    with st.spinner("Testing connection..."):
        try:
            auth_client = GraphAuthClient(
                tenant_id=st.secrets["azure_tenant_id"],
                client_id=st.secrets["azure_client_id"],
                client_secret=st.secrets["azure_client_secret"],
            )
            site_info = auth_client.test_connection(st.secrets["sp_site_url"])
            site_name = site_info.get("displayName", "Unknown")
            st.session_state["test_connection_result"] = (
                "success",
                f"Connected to: {site_name}",
            )
        except Exception as e:
            st.session_state["test_connection_result"] = ("error", str(e))

# Display test result
if st.session_state["test_connection_result"]:
    status, message = st.session_state["test_connection_result"]
    if status == "success":
        st.success(f"✅ {message}")
    else:
        st.error(f"❌ {message}")

st.divider()

# Options
st.subheader("Execution Options")

col1, col2 = st.columns(2)
with col1:
    auto_create_folders = st.checkbox(
        "Auto-create missing folders",
        value=True,
        key="auto_create_folders",
    )
with col2:
    confirm_execution = st.checkbox(
        "I understand this will move files in SharePoint and cannot be easily undone",
        value=False,
        key="confirm_execution",
    )

# Execute button
st.divider()

if st.button(
    "Execute Approved Moves",
    disabled=not confirm_execution,
    use_container_width=True,
    type="primary",
):
    try:
        auth_client = GraphAuthClient(
            tenant_id=st.secrets["azure_tenant_id"],
            client_id=st.secrets["azure_client_id"],
            client_secret=st.secrets["azure_client_secret"],
        )

        with st.spinner("Initializing migration executor..."):
            executor = MigrationExecutor(
                auth_client=auth_client,
                site_url=st.secrets["sp_site_url"],
            )

        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.container(border=True)

        succeeded = []
        failed = []
        skipped = []

        with log_container:
            for update in executor.execute_moves(
                approved_assignments,
                auto_create_folders=auto_create_folders,
            ):
                progress_bar.progress(update["progress"])
                phase = update.get("phase", "")
                status = update.get("status", "")
                message = update.get("message", "")
                file_name = update.get("file_name", "")

                if phase == "folders":
                    status_text.write(f"Creating folders... {message}")
                elif phase == "moves":
                    if status == "success":
                        succeeded.append(
                            {"file_name": file_name, "message": message}
                        )
                        status_text.write(f"✅ {file_name}: {message}")
                    elif status == "error":
                        failed.append(
                            {"file_name": file_name, "message": message}
                        )
                        status_text.write(f"❌ {file_name}: {message}")
                    elif status == "skip":
                        skipped.append(
                            {"file_name": file_name, "message": message}
                        )
                        status_text.write(f"⏭️ {file_name}: {message}")
                elif phase == "summary":
                    status_text.write("Migration complete!")

        # Store results
        st.session_state["execution_results"] = {
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
        }

    except Exception as e:
        st.error(f"Failed to initialize migration: {str(e)}")

# Display execution summary if results available
if st.session_state["execution_results"]:
    results = st.session_state["execution_results"]

    st.divider()
    st.subheader("Execution Summary")

    col1, col2, col3 = st.columns(3)
    col1.metric("Succeeded", len(results["succeeded"]))
    col2.metric("Failed", len(results["failed"]))
    col3.metric("Skipped", len(results["skipped"]))

    if results["succeeded"]:
        with st.expander(
            f"Succeeded ({len(results['succeeded'])})", expanded=False
        ):
            for move in results["succeeded"]:
                st.caption(f"**{move['file_name']}**: {move['message']}")

    if results["failed"]:
        with st.expander(
            f"Failed ({len(results['failed'])})", expanded=True
        ):
            for move in results["failed"]:
                st.error(f"**{move['file_name']}**: {move['message']}")

    if results["skipped"]:
        with st.expander(
            f"Skipped ({len(results['skipped'])})", expanded=False
        ):
            for move in results["skipped"]:
                st.caption(f"**{move['file_name']}**: {move['message']}")
