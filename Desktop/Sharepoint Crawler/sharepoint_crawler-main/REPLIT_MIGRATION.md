# SharePoint Reorganizer — Replit Frontend Migration Guide

**Stack:** React 18 + Tailwind CSS (Vite)  
**Backend:** Flask on PythonAnywhere (`src/api.py`)  
**Goal:** Replace the Streamlit multi-page app with a clean, modern single-page workflow

---

## Architecture Overview

```
PythonAnywhere (backend)              Replit (frontend)
────────────────────────────          ────────────────────────────
src/api.py  (Flask)          ◄──────  React + Tailwind SPA
  GET  /health                        Vite dev server / Replit hosting
  POST /api/test-connection
  POST /api/analyze   (SSE stream)  ← full 3-phase pipeline
  POST /api/organize                  (accepts enriched CSV, runs Phase 3 only)
  POST /api/execute   (SSE stream)
```

**Three paths into the proposal review screen:**

| User action | What happens |
|---|---|
| Click **"Analyze & Generate Proposal"** | `POST /api/analyze` SSE stream — crawl → classify → organize, returns proposal in final event |
| Upload `documents.csv` | `POST /api/organize` — skips crawl & classify, re-runs organizer only |
| Upload `proposal.json` | Loaded directly in the browser, no backend call |

The `/api/analyze` stream emits progress events throughout so the UI can show
a live status log. The final event (`phase: "complete"`) carries the full
`proposal` JSON.

---

## 1. Replit Project Setup

### 1.1 Create the Replit

1. Go to [replit.com](https://replit.com) → **Create Repl**
2. Choose **React** template (Vite)
3. Name it `sharepoint-reorganizer-ui`

### 1.2 Install dependencies

```bash
npm install tailwindcss @tailwindcss/vite lucide-react
```

---

## 2. Environment Variables

Set these in your Replit **Secrets** tab (or `.env` for local dev):

```
VITE_API_BASE=https://yourusername.pythonanywhere.com
VITE_API_KEY=your-api-key-here
```

The `VITE_API_KEY` must match the `API_KEY` env var on your PythonAnywhere backend.

---

## 3. Frontend API Client

Create `src/api.js`:

```js
const BASE = import.meta.env.VITE_API_BASE || '';
const API_KEY = import.meta.env.VITE_API_KEY || '';

const headers = () => ({
  'Content-Type': 'application/json',
  ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
});

export async function checkHealth() {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function testConnection() {
  const res = await fetch(`${BASE}/api/test-connection`, {
    method: 'POST',
    headers: headers(),
  });
  if (!res.ok) throw new Error((await res.json()).detail);
  return res.json();
}

export async function runOrganize(csvFile) {
  const form = new FormData();
  form.append('file', csvFile);
  const res = await fetch(`${BASE}/api/organize`, {
    method: 'POST',
    headers: { ...(API_KEY ? { 'X-API-Key': API_KEY } : {}) },
    body: form,
  });
  if (!res.ok) throw new Error((await res.json()).detail);
  return res.json();
}

// ── Full 3-phase pipeline: crawl → classify → organize (SSE stream) ─────────
// onUpdate(event) is called for each SSE message.
// Each event: { phase, status, message, progress, proposal? }
//   phase: "crawl" | "classify" | "organize" | "complete" | "error"
//   proposal is present only on the final phase="complete" event.
// Returns a cleanup function that aborts the stream.
export function analyzeStream(onUpdate) {
  const controller = new AbortController();

  fetch(`${BASE}/api/analyze`, {
    method: 'POST',
    headers: headers(),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json();
      onUpdate({ phase: 'error', status: 'error', message: err.detail });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            onUpdate(JSON.parse(line.slice(6)));
          } catch (parseErr) {
            // Malformed SSE frame — surface as an error so the UI doesn't stall
            onUpdate({ phase: 'error', status: 'error', message: `SSE parse error: ${parseErr.message}` });
          }
        }
      }
    }
  }).catch((e) => {
    if (e.name !== 'AbortError') {
      onUpdate({ phase: 'error', status: 'error', message: e.message });
    }
  });

  return () => controller.abort(); // returns a cleanup function
}

// ── Execute approved moves (SSE stream) ───────────────────────────────────
// onUpdate(event) is called for each SSE message.
// Returns a cleanup function that aborts the stream.
export function executeMovesStream(assignments, autoCreateFolders, onUpdate) {
  const controller = new AbortController();

  fetch(`${BASE}/api/execute`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      assignments,
      auto_create_folders: autoCreateFolders,
    }),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json();
      onUpdate({ phase: 'error', message: err.detail });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            onUpdate(JSON.parse(line.slice(6)));
          } catch (parseErr) {
            // Malformed SSE frame — surface as an error so the UI doesn't stall
            onUpdate({ phase: 'error', status: 'error', message: `SSE parse error: ${parseErr.message}` });
          }
        }
      }
    }
  }).catch((e) => {
    if (e.name !== 'AbortError') {
      onUpdate({ phase: 'error', message: e.message });
    }
  });

  return () => controller.abort(); // returns a cleanup function
}
```

> **Note:** `analyzeStream` sends no request body — all credentials are read
> from env vars on the backend. The `X-API-Key` header is the only
> client-supplied auth token.

---

## 4. Key Backend Notes (`src/api.py`)

The backend file lives at `src/api.py` in this repo and is already implemented.
A few design decisions worth knowing:

### 4.1 SSE stream design

Each event from `/api/analyze` and `/api/execute` is a JSON object:

```
data: {"phase":"crawl","status":"running","message":"Scanning...","progress":0.05}
```

The final event from `/api/analyze` carries the full proposal:

```
data: {"phase":"complete","status":"success","progress":1.0,"proposal":{...}}
```

### 4.2 `proposal` scoping

The `complete` SSE event is yielded **inside** the `TemporaryDirectory` context
where `proposal` is assigned. This is intentional — if the organizer raises
inside the `with` block, the outer `except` catches it cleanly without a
`NameError` on `proposal`.

### 4.3 Drive ID derivation

The extraction loop derives `primary_drive_id` from the first document's
`drive_item_path` rather than calling `crawler._get_document_libraries()` a
second time. This avoids a redundant Graph API round-trip since `crawl()` has
already fetched the libraries internally.

### 4.4 SSE parse errors (frontend)

Both `analyzeStream` and `executeMovesStream` surface `JSON.parse` failures via
`onUpdate({ phase: 'error', ... })` rather than silently swallowing them. A
malformed frame will show up in the UI status log rather than causing the
progress indicator to stall indefinitely.

---

## 5. Suggested React Component Structure

```
src/
  api.js                ← API client (code above)
  App.jsx               ← router / top-level state
  pages/
    Connect.jsx         ← test-connection form
    Analyze.jsx         ← trigger /api/analyze, show ProgressLog
    Review.jsx          ← proposal diff table, approve/reject moves
    Execute.jsx         ← trigger /api/execute, show live log
  components/
    ProgressLog.jsx     ← real-time SSE status list
    ProposalTable.jsx   ← sortable/filterable assignment table
```

### 5.1 `ProgressLog.jsx` — consuming SSE events

```jsx
import { useEffect, useRef, useState } from 'react';
import { analyzeStream } from '../api';

export default function ProgressLog({ onComplete }) {
  const [log, setLog] = useState([]);
  const [progress, setProgress] = useState(0);
  const cleanupRef = useRef(null);

  useEffect(() => {
    cleanupRef.current = analyzeStream((event) => {
      setLog((prev) => [...prev, event]);
      if (event.progress != null) setProgress(event.progress);
      if (event.phase === 'complete') onComplete(event.proposal);
    });
    return () => cleanupRef.current?.();
  }, []);

  return (
    <div>
      <progress value={progress} max={1} />
      <ul>
        {log.map((e, i) => (
          <li key={i} className={e.status === 'error' ? 'text-red-600' : ''}>
            {e.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

---

## 6. PythonAnywhere Deployment

See [`PYTHONANYWHERE_DEPLOY.md`](PYTHONANYWHERE_DEPLOY.md) for the full deploy
guide. Quick checklist:

- [ ] Upload `src/api.py` and all `src/` modules
- [ ] Install `flask flask-cors python-dotenv` in your virtualenv
- [ ] Configure your WSGI file to point at `src/api:app`
- [ ] Set all env vars in the PythonAnywhere **Web** tab → **Environment variables**
- [ ] Set `API_KEY` to a strong random string and mirror it in Replit Secrets as `VITE_API_KEY`

---

## 7. API Reference

```
GET  /health                       → { status: "ok" }
POST /api/test-connection          → { status, site_name, document_libraries }
POST /api/analyze                  → SSE stream (see §4.1)
POST /api/organize    (multipart)  → proposal JSON
POST /api/execute                  → SSE stream
```

All `/api/*` endpoints require `X-API-Key: <your key>` unless `API_KEY` is
unset on the server (dev mode).
