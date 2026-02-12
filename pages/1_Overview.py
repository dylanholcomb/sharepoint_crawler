import streamlit as st
from typing import Dict, Any


def render_folder_tree(tree: Dict[str, Any], indent: int = 0) -> str:
    """
    Recursively render a folder tree structure as indented text with folder icons.

    Args:
        tree: Dictionary with folder names as keys and folder info dicts as values
        indent: Current indentation level (incremented recursively)

    Returns:
        Formatted string representation of the folder tree
    """
    lines = []
    indent_str = "  " * indent

    for folder_name, folder_info in tree.items():
        # Add folder line with icon and name
        lines.append(f"{indent_str}📁 **{folder_name}**")

        # Add description in smaller text if present
        if isinstance(folder_info, dict) and "description" in folder_info:
            description = folder_info["description"]
            lines.append(f"{indent_str}   _{description}_")

        # Recursively add subfolders if present
        if isinstance(folder_info, dict) and "subfolders" in folder_info:
            subfolders = folder_info["subfolders"]
            if subfolders:
                sub_lines = render_folder_tree(subfolders, indent + 1).split("\n")
                lines.extend(sub_lines)

    return "\n".join(lines)


def main():
    st.set_page_config(page_title="Overview - SP Reorganization", layout="wide")

    st.title("📊 Proposal Overview")

    # Check if proposal exists in session state
    if "proposal" not in st.session_state or not st.session_state["proposal"]:
        st.warning(
            "⚠️ **No proposal loaded.** Please upload a proposal from the sidebar to get started."
        )
        st.info(
            "Use the file uploader in the left sidebar to load a proposal JSON file, "
            "or generate one from the Analysis page."
        )
        return

    proposal = st.session_state["proposal"]
    summary = proposal.get("summary", {})

    # Display summary metrics
    st.subheader("Summary Metrics")
    metric_cols = st.columns(4)

    with metric_cols[0]:
        st.metric(
            "Total Documents",
            summary.get("total_documents", 0)
        )

    with metric_cols[1]:
        st.metric(
            "Documents That Would Move",
            summary.get("documents_that_would_move", 0)
        )

    with metric_cols[2]:
        st.metric(
            "New Folders Created",
            summary.get("new_folders_created", 0)
        )

    with metric_cols[3]:
        st.metric(
            "Folders Consolidated",
            summary.get("folders_consolidated", 0)
        )

    st.divider()

    # Side-by-side comparison of proposals
    st.subheader("Proposal Comparison")

    col_left, col_right = st.columns(2)

    # Clean Slate Proposal
    with col_left:
        st.markdown("### ✨ Clean Slate Proposal")

        clean_slate = proposal.get("clean_slate", {})

        # Description
        if clean_slate.get("description"):
            st.write(clean_slate["description"])

        # Folder tree
        if clean_slate.get("folder_tree"):
            st.markdown("**Folder Structure:**")
            tree_text = render_folder_tree(clean_slate["folder_tree"])
            st.markdown(tree_text)

        # Assignments count
        assignments = clean_slate.get("assignments", [])
        st.caption(f"📋 {len(assignments)} file assignments")

    # Incremental Proposal
    with col_right:
        st.markdown("### 🔄 Incremental Proposal")

        incremental = proposal.get("incremental", {})

        # Description
        if incremental.get("description"):
            st.write(incremental["description"])

        # Folder tree
        if incremental.get("folder_tree"):
            st.markdown("**Folder Structure:**")
            tree_text = render_folder_tree(incremental["folder_tree"])
            st.markdown(tree_text)

        # Assignments count
        assignments = incremental.get("assignments", [])
        st.caption(f"📋 {len(assignments)} file assignments")

    st.divider()

    # Plan selection and navigation
    st.subheader("Review Your Plan")

    plan_choice = st.radio(
        "Select plan for review:",
        options=["Clean Slate", "Incremental"],
        horizontal=True,
        help="Choose which proposal you'd like to review in detail"
    )

    # Store the active plan in session state
    if plan_choice == "Clean Slate":
        st.session_state["active_plan"] = "clean_slate"
    else:
        st.session_state["active_plan"] = "incremental"

    # Navigation button
    col_button, col_spacer = st.columns([1, 5])
    with col_button:
        if st.button("📋 Review Moves →", use_container_width=True):
            st.success(f"✓ '{plan_choice}' plan selected for review")
            st.info("👉 Navigate to the **Review Moves** page from the sidebar to see file assignments")


if __name__ == "__main__":
    main()
