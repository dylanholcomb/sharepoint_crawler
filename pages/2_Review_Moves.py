import streamlit as st
from typing import Set, List, Dict, Any

st.set_page_config(page_title="Review Proposed Moves", layout="wide")

st.title("Review Proposed Moves")

# Initialize session state if needed
if "proposal" not in st.session_state:
    st.session_state["proposal"] = None
if "active_plan" not in st.session_state:
    st.session_state["active_plan"] = "clean_slate"
if "approved_moves" not in st.session_state:
    st.session_state["approved_moves"] = set()
if "rejected_moves" not in st.session_state:
    st.session_state["rejected_moves"] = set()
if "current_page" not in st.session_state:
    st.session_state["current_page"] = 0
if "search_filter" not in st.session_state:
    st.session_state["search_filter"] = ""
if "status_filter" not in st.session_state:
    st.session_state["status_filter"] = "All"

# Check if proposal is loaded
if st.session_state["proposal"] is None:
    st.warning("⚠️ No proposal loaded. Please go to the 'Scan & Analyze' page to load a proposal first.")
    st.stop()

proposal = st.session_state["proposal"]

# Plan selector
st.subheader("Plan Selection")
plan_choice = st.radio(
    "Select reorganization plan:",
    options=["clean_slate", "incremental"],
    format_func=lambda x: "Clean Slate" if x == "clean_slate" else "Incremental",
    horizontal=True,
    key="plan_selector"
)
st.session_state["active_plan"] = plan_choice

# Get assignments from the selected plan
assignments = proposal.get(plan_choice, {}).get("assignments", [])

if not assignments:
    st.info("No assignments found in the selected plan.")
    st.stop()

# Filter controls in a row
st.subheader("Filters")
col1, col2 = st.columns([2, 1])

with col1:
    search_text = st.text_input(
        "Search by filename",
        value=st.session_state["search_filter"],
        placeholder="Enter filename to filter...",
        key="search_input"
    )
    st.session_state["search_filter"] = search_text

with col2:
    status_filter = st.selectbox(
        "Filter by status",
        options=["All", "Pending", "Approved", "Rejected"],
        key="status_filter_select"
    )
    st.session_state["status_filter"] = status_filter

# Apply filters
filtered_assignments = []
for assignment in assignments:
    file_name = assignment.get("file_name", "")

    # Apply text search
    if search_text and search_text.lower() not in file_name.lower():
        continue

    # Apply status filter
    if status_filter != "All":
        if status_filter == "Approved" and file_name not in st.session_state["approved_moves"]:
            continue
        elif status_filter == "Rejected" and file_name not in st.session_state["rejected_moves"]:
            continue
        elif status_filter == "Pending" and (file_name in st.session_state["approved_moves"] or file_name in st.session_state["rejected_moves"]):
            continue

    filtered_assignments.append(assignment)

# Calculate stats
total = len(assignments)
approved = len(st.session_state["approved_moves"])
rejected = len(st.session_state["rejected_moves"])
pending = total - approved - rejected

# Stats bar
st.subheader("Summary")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Approved", approved)
with col2:
    st.metric("Rejected", rejected)
with col3:
    st.metric("Pending", pending)
with col4:
    st.metric("Total", total)

# Bulk actions
st.subheader("Bulk Actions")
col1, col2 = st.columns(2)

with col1:
    if st.button("✅ Approve All Visible", use_container_width=True):
        for assignment in filtered_assignments:
            file_name = assignment.get("file_name", "")
            st.session_state["approved_moves"].add(file_name)
            st.session_state["rejected_moves"].discard(file_name)
        st.success(f"Approved {len(filtered_assignments)} visible moves")
        st.rerun()

with col2:
    if st.button("❌ Reject All Visible", use_container_width=True):
        for assignment in filtered_assignments:
            file_name = assignment.get("file_name", "")
            st.session_state["rejected_moves"].add(file_name)
            st.session_state["approved_moves"].discard(file_name)
        st.success(f"Rejected {len(filtered_assignments)} visible moves")
        st.rerun()

# Pagination
items_per_page = 25
total_pages = (len(filtered_assignments) + items_per_page - 1) // items_per_page

if total_pages == 0:
    st.info("No moves match the current filters.")
    st.stop()

# Ensure current page is valid
if st.session_state["current_page"] >= total_pages:
    st.session_state["current_page"] = total_pages - 1

start_idx = st.session_state["current_page"] * items_per_page
end_idx = min(start_idx + items_per_page, len(filtered_assignments))
page_assignments = filtered_assignments[start_idx:end_idx]

st.subheader(f"Assignments (Page {st.session_state['current_page'] + 1} of {total_pages})")

# Display assignments
for assignment in page_assignments:
    file_name = assignment.get("file_name", "")
    current_path = assignment.get("current_path", "")
    proposed_path = assignment.get("proposed_path", "")
    reason = assignment.get("reason", "")

    # Determine status
    if file_name in st.session_state["approved_moves"]:
        status = "Approved"
        status_color = "🟢"
    elif file_name in st.session_state["rejected_moves"]:
        status = "Rejected"
        status_color = "🔴"
    else:
        status = "Pending"
        status_color = "⚪"

    # Create a container for each row
    with st.container(border=True):
        # Create columns for the layout
        col_checkbox, col_filename, col_current, col_proposed, col_reason, col_status, col_actions = st.columns(
            [0.8, 1.5, 1.5, 1.5, 1.5, 0.8, 0.8]
        )

        with col_checkbox:
            is_checked = file_name in st.session_state["approved_moves"]
            checkbox_state = st.checkbox(
                "Approve",
                value=is_checked,
                key=f"checkbox_{file_name}",
                label_visibility="collapsed"
            )

            if checkbox_state and file_name not in st.session_state["approved_moves"]:
                st.session_state["approved_moves"].add(file_name)
                st.session_state["rejected_moves"].discard(file_name)
                st.rerun()
            elif not checkbox_state and file_name in st.session_state["approved_moves"]:
                st.session_state["approved_moves"].discard(file_name)
                st.rerun()

        with col_filename:
            st.text(file_name)

        with col_current:
            st.caption(current_path)

        with col_proposed:
            st.caption(proposed_path)

        with col_reason:
            st.caption(reason)

        with col_status:
            st.markdown(f"{status_color} {status}")

        with col_actions:
            if st.button("Reject", key=f"reject_{file_name}", use_container_width=True):
                st.session_state["rejected_moves"].add(file_name)
                st.session_state["approved_moves"].discard(file_name)
                st.rerun()

# Pagination controls
st.subheader("Navigation")
col1, col2, col3 = st.columns([1, 1, 1])

with col1:
    if st.button("⬅️ Previous", disabled=(st.session_state["current_page"] == 0), use_container_width=True):
        st.session_state["current_page"] -= 1
        st.rerun()

with col2:
    st.text(f"Page {st.session_state['current_page'] + 1} of {total_pages}")

with col3:
    if st.button("Next ➡️", disabled=(st.session_state["current_page"] >= total_pages - 1), use_container_width=True):
        st.session_state["current_page"] += 1
        st.rerun()

# Bottom summary and call to action
st.divider()
st.subheader("Ready to Execute?")

summary_text = f"""
You have configured **{approved} approved moves** and **{rejected} rejected moves** out of **{total} total**.
"""
st.markdown(summary_text)

if approved > 0:
    if st.button("Proceed to Execute →", use_container_width=True, type="primary"):
        st.switch_page("pages/3_Execute.py")
else:
    st.warning("Please approve at least one move before proceeding to execution.")
