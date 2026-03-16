# SharePoint Reorganizer — Replit Frontend Migration Guide

**Stack:** React 18 + Tailwind CSS (Vite)
**Backend:** FastAPI on PythonAnywhere (`src/api.py`)
**Goal:** Replace the clunky Streamlit multi-page app with a clean, modern single-page workflow

---

## Architecture Overview

```
PythonAnywhere (backend)              Replit (frontend)
────────────────────────────          ────────────────────────────
src/api.py  (FastAPI)        ◄──────  React + Tailwind SPA
  POST /api/test-connection           Vite dev server / Replit hosting
  POST /api/organize
  POST /api/execute  (SSE stream)
  GET  /health
```

The backend stays on PythonAnywhere where the long-running Python processes
(crawl, classify, organize) live. The React frontend is purely a **file
consumer and executor**: users upload the JSON/CSV outputs, review and approve
moves, then trigger live execution via the SSE stream.

---

## 1. Replit Project Setup

### 1.1 Create the Replit

1. Go to [replit.com](https://replit.com) → **Create Repl**
2. Choose **React (Vite)** template
3. Name it something like `sharepoint-reorganizer-ui`

### 1.2 Install dependencies

In the Replit Shell:

```bash
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install lucide-react
npm install react-router-dom
```

### 1.3 Configure Tailwind

In `tailwind.config.js`:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

In `src/index.css` (replace everything):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### 1.4 Environment variable

In Replit → **Secrets** (padlock icon), add:

| Key | Value |
|-----|-------|
| `VITE_API_BASE_URL` | `https://yourusername.pythonanywhere.com` |
| `VITE_API_KEY` | your secret API key (must match `API_KEY` in PythonAnywhere .env) |

---

## 2. File Structure

```
src/
  api/
    client.js          ← all fetch calls to FastAPI
  components/
    Layout.jsx         ← sidebar + top bar shell
    FolderTree.jsx     ← recursive folder tree display
    MoveRow.jsx        ← single file assignment row (approve/reject/edit)
    ProgressLog.jsx    ← real-time SSE execution log
    StatusBadge.jsx    ← Approved / Rejected / Pending chip
  pages/
    Home.jsx           ← upload landing page
    Overview.jsx       ← proposal comparison (Clean Slate vs Incremental)
    ReviewMoves.jsx    ← approve / reject / edit moves
    Execute.jsx        ← preflight + live execution
  App.jsx
  main.jsx
```

---

## 3. API Client (`src/api/client.js`)

```js
const BASE = import.meta.env.VITE_API_BASE_URL;
const KEY  = import.meta.env.VITE_API_KEY;

const headers = () => ({
  "Content-Type": "application/json",
  "X-API-Key": KEY,
});

// ── Health check ──────────────────────────────────────────────────────────
export async function checkHealth() {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

// ── Test Azure connection ─────────────────────────────────────────────────
export async function testConnection() {
  const res = await fetch(`${BASE}/api/test-connection`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error((await res.json()).detail);
  return res.json();
}

// ── Upload enriched CSV and run organizer ─────────────────────────────────
export async function runOrganize(csvFile) {
  const form = new FormData();
  form.append("file", csvFile);
  const res = await fetch(`${BASE}/api/organize`, {
    method: "POST",
    headers: { "X-API-Key": KEY },   // no Content-Type — FormData sets it
    body: form,
  });
  if (!res.ok) throw new Error((await res.json()).detail);
  return res.json();   // returns the full proposal JSON
}

// ── Execute approved moves (SSE stream) ───────────────────────────────────
// onUpdate(event) is called for each SSE message
export function executeMovesStream(assignments, autoCreateFolders, onUpdate) {
  const controller = new AbortController();

  fetch(`${BASE}/api/execute`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      assignments,
      auto_create_folders: autoCreateFolders,
    }),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json();
      onUpdate({ phase: "error", message: err.detail });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();  // keep incomplete line in buffer
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            onUpdate(JSON.parse(line.slice(6)));
          } catch {}
        }
      }
    }
  }).catch((e) => {
    if (e.name !== "AbortError") onUpdate({ phase: "error", message: e.message });
  });

  return () => controller.abort();  // returns a cleanup function
}
```

---

## 4. Page Designs

### 4.1 `Home.jsx` — Upload + Connection

Key UX improvements over Streamlit:
- Drag-and-drop zones for JSON proposal and CSV files
- Connection status shown as a real-time badge, not a sidebar note
- "Run Organizer" button (uploads CSV → calls `/api/organize` → stores result in state)

**State managed here:**
- `proposal` – the JSON from `/api/organize` (or manually uploaded)
- `connectionStatus` – result of `/api/test-connection`

```jsx
import { useState, useCallback } from "react";
import { Upload, CheckCircle, XCircle } from "lucide-react";
import { testConnection, runOrganize } from "../api/client";

export default function Home({ setProposal }) {
  const [csvFile, setCsvFile] = useState(null);
  const [jsonFile, setJsonFile] = useState(null);
  const [connStatus, setConnStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleTestConnection = async () => {
    setLoading(true);
    try {
      const result = await testConnection();
      setConnStatus({ ok: true, ...result });
    } catch (e) {
      setConnStatus({ ok: false, message: e.message });
    } finally {
      setLoading(false);
    }
  };

  const handleOrganize = async () => {
    if (!csvFile) return;
    setLoading(true);
    try {
      const proposal = await runOrganize(csvFile);
      setProposal(proposal);
      // navigate to /overview
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">
        SharePoint Reorganizer
      </h1>

      {/* Connection test */}
      <div className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium text-gray-700">1. Verify Connection</h2>
        <button
          onClick={handleTestConnection}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Test SharePoint Connection
        </button>
        {connStatus && (
          <div className={`flex items-center gap-2 text-sm ${connStatus.ok ? "text-green-700" : "text-red-600"}`}>
            {connStatus.ok
              ? <><CheckCircle className="w-4 h-4" /> Connected to {connStatus.site_name}</>
              : <><XCircle className="w-4 h-4" /> {connStatus.message}</>
            }
          </div>
        )}
      </div>

      {/* CSV upload → organize */}
      <div className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium text-gray-700">2. Run Organizer</h2>
        <p className="text-sm text-gray-500">
          Upload the enriched CSV from <code>main.py --analyze</code> to generate folder proposals.
        </p>
        <input
          type="file"
          accept=".csv"
          onChange={(e) => setCsvFile(e.target.files[0])}
          className="block text-sm text-gray-600"
        />
        <button
          onClick={handleOrganize}
          disabled={!csvFile || loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? "Analyzing..." : "Generate Proposals"}
        </button>
      </div>

      {/* Manual JSON upload */}
      <div className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium text-gray-700">
          Or upload an existing proposal
        </h2>
        <input
          type="file"
          accept=".json"
          onChange={(e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (ev) => {
              try { setProposal(JSON.parse(ev.target.result)); } catch {}
            };
            reader.readAsText(file);
          }}
          className="block text-sm text-gray-600"
        />
      </div>
    </div>
  );
}
```

---

### 4.2 `Overview.jsx` — Proposal Comparison

Key improvements over Streamlit:
- Side-by-side folder trees rendered as collapsible tree nodes (not raw markdown)
- Summary metrics in a clean stat bar
- Plan selection persists in URL (`?plan=clean_slate`)

**FolderTree component** (in `components/FolderTree.jsx`):

```jsx
import { useState } from "react";
import { Folder, FolderOpen, ChevronRight, ChevronDown } from "lucide-react";

function TreeNode({ name, info, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2);
  const subfolders = info?.subfolders || {};
  const hasChildren = Object.keys(subfolders).length > 0;

  return (
    <div className="text-sm">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 py-0.5 hover:bg-gray-100 rounded w-full text-left"
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
      >
        {hasChildren
          ? (open ? <ChevronDown className="w-3 h-3 flex-shrink-0" /> : <ChevronRight className="w-3 h-3 flex-shrink-0" />)
          : <span className="w-3" />
        }
        {open
          ? <FolderOpen className="w-4 h-4 text-amber-500 flex-shrink-0" />
          : <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
        }
        <span className="font-medium text-gray-800">{name}</span>
        {info?.description && (
          <span className="ml-2 text-gray-400 text-xs truncate">{info.description}</span>
        )}
      </button>
      {open && hasChildren && Object.entries(subfolders).map(([k, v]) => (
        <TreeNode key={k} name={k} info={v} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function FolderTree({ tree }) {
  if (!tree || Object.keys(tree).length === 0) {
    return <p className="text-sm text-gray-400 italic">No folder structure available.</p>;
  }
  return (
    <div className="border rounded-lg p-3 bg-gray-50 max-h-96 overflow-y-auto">
      {Object.entries(tree).map(([k, v]) => (
        <TreeNode key={k} name={k} info={v} depth={0} />
      ))}
    </div>
  );
}
```

---

### 4.3 `ReviewMoves.jsx` — Approve / Reject / Edit

Key improvements over Streamlit:
- **Inline path editing** — click the proposed path to correct it before approving
- **Keyboard shortcuts** — `A` to approve, `R` to reject the focused row
- **Confidence chip** — show low-confidence assignments in amber so reviewers prioritize them
- **Group by client** — instead of a flat paginated list, group rows by client folder
- Persistent state via `localStorage` so refreshing doesn't lose your reviews

**MoveRow component** (in `components/MoveRow.jsx`):

```jsx
import { useState } from "react";
import { Check, X, Pencil, ChevronRight } from "lucide-react";

export default function MoveRow({ assignment, status, onApprove, onReject, onEditPath }) {
  const [editing, setEditing] = useState(false);
  const [draftPath, setDraftPath] = useState(assignment.proposed_path);

  const bg =
    status === "approved" ? "bg-green-50 border-green-200"
    : status === "rejected" ? "bg-red-50 border-red-200"
    : "bg-white border-gray-200";

  return (
    <div className={`border rounded-lg p-3 mb-2 flex items-start gap-3 ${bg}`}>
      {/* Status buttons */}
      <div className="flex flex-col gap-1 flex-shrink-0">
        <button
          onClick={() => onApprove(assignment.file_name)}
          className={`p-1 rounded ${status === "approved" ? "bg-green-500 text-white" : "hover:bg-green-100 text-green-600"}`}
          title="Approve"
        >
          <Check className="w-4 h-4" />
        </button>
        <button
          onClick={() => onReject(assignment.file_name)}
          className={`p-1 rounded ${status === "rejected" ? "bg-red-500 text-white" : "hover:bg-red-100 text-red-600"}`}
          title="Reject"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="font-medium text-gray-900 text-sm truncate">
          {assignment.file_name}
        </div>
        <div className="flex items-center gap-1 text-xs text-gray-400 mt-0.5">
          <span className="truncate">{assignment.current_path}</span>
          <ChevronRight className="w-3 h-3 flex-shrink-0" />
          {editing ? (
            <input
              autoFocus
              value={draftPath}
              onChange={(e) => setDraftPath(e.target.value)}
              onBlur={() => {
                onEditPath(assignment.file_name, draftPath);
                setEditing(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onEditPath(assignment.file_name, draftPath);
                  setEditing(false);
                }
                if (e.key === "Escape") setEditing(false);
              }}
              className="border-b border-blue-400 bg-transparent focus:outline-none text-blue-700 min-w-0 flex-1"
            />
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="text-blue-600 hover:underline truncate flex items-center gap-0.5"
            >
              {assignment.proposed_path}
              <Pencil className="w-3 h-3 ml-0.5" />
            </button>
          )}
        </div>
        {assignment.reason && (
          <div className="text-xs text-gray-400 mt-0.5 italic truncate">
            {assignment.reason}
          </div>
        )}
      </div>
    </div>
  );
}
```

---

### 4.4 `Execute.jsx` — Live Progress via SSE

Key improvements over Streamlit:
- Real-time progress bar driven by SSE — no polling, no page refreshes
- Separate counters for folders created, files moved, errors, skips
- Log entries scrollable with color-coded status icons
- Cancel button that aborts the stream

```jsx
import { useState, useRef } from "react";
import { executeMovesStream } from "../api/client";
import { CheckCircle, XCircle, SkipForward, Folder } from "lucide-react";

export default function Execute({ assignments }) {
  const [log, setLog] = useState([]);
  const [progress, setProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState(null);
  const [autoCreate, setAutoCreate] = useState(true);
  const cancelRef = useRef(null);
  const logEndRef = useRef(null);

  const start = () => {
    setLog([]);
    setProgress(0);
    setSummary(null);
    setRunning(true);

    const cancel = executeMovesStream(assignments, autoCreate, (event) => {
      setProgress(event.progress ?? 0);
      if (event.phase === "summary") {
        setSummary(event.summary);
        setRunning(false);
        return;
      }
      if (event.phase === "error") {
        setLog((l) => [...l, { status: "error", message: event.message, file_name: null }]);
        setRunning(false);
        return;
      }
      setLog((l) => [...l, event]);
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    });

    cancelRef.current = cancel;
  };

  const stop = () => {
    cancelRef.current?.();
    setRunning(false);
  };

  const iconFor = (ev) => {
    if (ev.phase === "folders") return <Folder className="w-4 h-4 text-amber-500" />;
    if (ev.status === "success") return <CheckCircle className="w-4 h-4 text-green-500" />;
    if (ev.status === "error") return <XCircle className="w-4 h-4 text-red-500" />;
    return <SkipForward className="w-4 h-4 text-gray-400" />;
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Execute Migration</h1>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input
            type="checkbox"
            checked={autoCreate}
            onChange={(e) => setAutoCreate(e.target.checked)}
            className="rounded"
          />
          Auto-create missing folders
        </label>
        <div className="flex-1" />
        {!running ? (
          <button
            onClick={start}
            disabled={assignments.length === 0}
            className="px-5 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
          >
            Execute {assignments.length} Approved Moves
          </button>
        ) : (
          <button
            onClick={stop}
            className="px-5 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Cancel
          </button>
        )}
      </div>

      {/* Progress bar */}
      {(running || progress > 0) && (
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Succeeded", value: summary.successes, color: "text-green-700" },
            { label: "Failed",    value: summary.failures,  color: "text-red-600" },
            { label: "Skipped",   value: summary.skips,     color: "text-gray-500" },
            { label: "Folders Created", value: summary.folders_created, color: "text-amber-600" },
          ].map(({ label, value, color }) => (
            <div key={label} className="border rounded-lg p-3 text-center">
              <div className={`text-2xl font-bold ${color}`}>{value}</div>
              <div className="text-xs text-gray-500">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Log */}
      {log.length > 0 && (
        <div className="border rounded-lg p-3 max-h-72 overflow-y-auto text-sm space-y-1 bg-gray-50">
          {log.map((ev, i) => (
            <div key={i} className="flex items-center gap-2">
              {iconFor(ev)}
              <span className="text-gray-700 truncate">
                {ev.file_name && <span className="font-medium">{ev.file_name}: </span>}
                {ev.message}
              </span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
    </div>
  );
}
```

---

## 5. App Shell (`src/App.jsx`)

```jsx
import { useState } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Overview from "./pages/Overview";
import ReviewMoves from "./pages/ReviewMoves";
import Execute from "./pages/Execute";

export default function App() {
  const [proposal, setProposal] = useState(null);
  const [approvedMoves, setApprovedMoves] = useState({});  // { file_name: proposed_path }
  const [activePlan, setActivePlan] = useState("clean_slate");

  const navItem = (to, label) => (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 text-sm rounded ${isActive ? "bg-blue-100 text-blue-700 font-medium" : "text-gray-600 hover:bg-gray-100"}`
      }
    >
      {label}
    </NavLink>
  );

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 flex flex-col">
        {/* Top nav */}
        <header className="bg-white border-b px-6 py-3 flex items-center gap-6">
          <span className="font-semibold text-gray-900">
            📂 SP Reorganizer
          </span>
          <nav className="flex gap-1">
            {navItem("/", "Upload")}
            {navItem("/overview", "Overview")}
            {navItem("/review", "Review Moves")}
            {navItem("/execute", "Execute")}
          </nav>
          {proposal && (
            <span className="ml-auto text-xs text-green-600 font-medium">
              ✓ Proposal loaded
            </span>
          )}
        </header>

        {/* Page content */}
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Home setProposal={setProposal} />} />
            <Route
              path="/overview"
              element={
                <Overview
                  proposal={proposal}
                  activePlan={activePlan}
                  setActivePlan={setActivePlan}
                />
              }
            />
            <Route
              path="/review"
              element={
                <ReviewMoves
                  proposal={proposal}
                  activePlan={activePlan}
                  approvedMoves={approvedMoves}
                  setApprovedMoves={setApprovedMoves}
                />
              }
            />
            <Route
              path="/execute"
              element={
                <Execute
                  assignments={Object.entries(approvedMoves).map(
                    ([file_name, proposed_path]) => ({ file_name, proposed_path })
                  )}
                />
              }
            />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

---

## 6. PythonAnywhere Backend Setup

### 6.1 Add FastAPI dependencies to `requirements.txt`

```txt
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
```

### 6.2 WSGI entry point for PythonAnywhere

PythonAnywhere uses WSGI. Create `wsgi.py` in the project root:

```python
# wsgi.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.api import app

# PythonAnywhere passes the WSGI app as 'application'
application = app
```

In PythonAnywhere → **Web** tab:
- WSGI configuration file → point to `wsgi.py`
- Python version → 3.11
- Source code → your project directory
- Virtualenv → your venv path

### 6.3 `.env` additions for the API

```env
# Existing vars
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
SP_SITE_URL=...
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# New for the API
API_KEY=choose-a-strong-secret-key
ALLOWED_ORIGINS=https://your-replit-slug.replit.app
```

---

## 7. Key UX Improvements Summary

| Feature | Streamlit (current) | React + Tailwind |
|---|---|---|
| Folder tree | Raw markdown with emoji | Collapsible interactive tree |
| File approval | Checkbox + separate Reject button | Approve/Reject side-by-side, inline path edit |
| Execution progress | Spinner + text area | Real-time progress bar + color-coded log |
| State persistence | Lost on page reload | `localStorage` keeps approvals across sessions |
| Mobile | Broken layout | Responsive |
| Large file sets | Slow full-page rerenders | Virtualized list, no rerenders |
| Path correction | Not possible | Click proposed path to edit inline before approving |
| Grouping | Flat paginated list | Grouped by client folder, collapsible |

---

## 8. What Stays on PythonAnywhere

- `main.py` — CLI pipeline (crawl, analyze, organize)
- `src/crawler.py` — SharePoint traversal
- `src/extractor.py` — document text extraction
- `src/classifier.py` — per-document AI classification
- `src/organizer.py` — folder structure proposals **(now improved)**
- `src/flow_discovery.py` — Power Automate flow discovery
- `src/api.py` — FastAPI wrapper **(new)**

The React frontend only needs `src/auth.py`, `src/migration_executor.py`, and
`src/graph_operations.py` transitively through the API — it never runs Python itself.
