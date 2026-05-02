const BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";
const KEY = import.meta.env.VITE_API_KEY || "";

export interface ProposalAssignment {
  file_name: string;
  current_path: string;
  proposed_path: string;
  reason?: string;
  confidence?: number;
  drive_id?: string;
  item_id?: string;
  drive_item_path?: string;
}

export interface ProposalPlan {
  folder_tree: Record<string, any>;
  assignments: ProposalAssignment[];
}

export interface Proposal {
  clean_slate: ProposalPlan;
  incremental: ProposalPlan;
}

export interface AuthContext {
  token: string;
  siteUrl: string;
}

function getHeaders(auth?: AuthContext, isFormData = false): Record<string, string> {
  const headers: Record<string, string> = {
    "X-API-Key": KEY,
  };
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }
  if (auth?.token) {
    headers["Authorization"] = `Bearer ${auth.token}`;
  }
  if (auth?.siteUrl) {
    headers["X-Site-URL"] = auth.siteUrl;
  }
  return headers;
}

export async function checkHealth(): Promise<{ status: string }> {
  try {
    const res = await fetch(`${BASE}/health`);
    if (!res.ok) throw new Error("Health check failed");
    return res.json();
  } catch {
    return { status: "error" };
  }
}

export async function testConnection(
  auth?: AuthContext
): Promise<{ success: boolean; message: string }> {
  try {
    const res = await fetch(`${BASE}/api/test-connection`, {
      method: "POST",
      headers: getHeaders(auth),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Connection failed");
    }
    const data = await res.json();
    return {
      success: true,
      message: data.site_name
        ? `Connected to "${data.site_name}"`
        : "Successfully connected to SharePoint.",
    };
  } catch (err: any) {
    return { success: false, message: err.message || "Failed to connect to SharePoint." };
  }
}

export interface AnalyzeEvent {
  phase: "crawl" | "classify" | "organize" | "complete" | "error";
  status?: string;
  message: string;
  progress?: number;
  proposal?: Proposal;
}

const ANALYZE_JOB_KEY = "sp_reorg_analyze_job_id";

export function getStoredJobId(): string | null {
  try {
    return localStorage.getItem(ANALYZE_JOB_KEY);
  } catch {
    return null;
  }
}

export function clearStoredJobId(): void {
  try {
    localStorage.removeItem(ANALYZE_JOB_KEY);
  } catch {
    /* ignore */
  }
}

function setStoredJobId(jobId: string): void {
  try {
    localStorage.setItem(ANALYZE_JOB_KEY, jobId);
  } catch {
    /* ignore */
  }
}

export async function startAnalysis(auth?: AuthContext): Promise<string> {
  const res = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    headers: getHeaders(auth),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Failed to start analysis (HTTP ${res.status})`);
  }
  const data = await res.json();
  if (!data.job_id) {
    throw new Error("Server did not return a job_id");
  }
  setStoredJobId(data.job_id);
  return data.job_id as string;
}

/**
 * Stream events for an existing analysis job. Auto-reconnects on transient
 * connection drops (e.g. PythonAnywhere's 5-min request limit) using the
 * `since` query param to resume from the last received event id.
 *
 * Stops when the job reaches `complete` or `error`.
 */
export function streamAnalysisJob(
  jobId: string,
  onEvent: (event: AnalyzeEvent) => void,
  auth?: AuthContext
): () => void {
  const abortController = new AbortController();
  let lastEventId = -1;
  let stopped = false;
  let terminal = false;
  let reconnectAttempts = 0;
  const MAX_RECONNECTS = 10;

  const consumeStream = async () => {
    const url = `${BASE}/api/analyze/${jobId}/stream?since=${lastEventId}`;
    const res = await fetch(url, {
      method: "GET",
      headers: getHeaders(auth),
      signal: abortController.signal,
    });

    if (!res.ok) {
      if (res.status === 404) {
        clearStoredJobId();
        onEvent({ phase: "error", message: "Job not found on server (it may have expired)." });
        terminal = true;
        return;
      }
      const text = await res.text().catch(() => "");
      throw new Error(text || `Stream failed (HTTP ${res.status})`);
    }

    if (!res.body) {
      throw new Error("No response body from server.");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const ev = JSON.parse(line.slice(6)) as AnalyzeEvent & { id?: number };
          if (typeof ev.id === "number") {
            lastEventId = ev.id;
          }
          onEvent(ev);
          if (ev.phase === "complete" || ev.phase === "error") {
            terminal = true;
            clearStoredJobId();
          }
        } catch {
          /* ignore malformed chunks */
        }
      }
    }
  };

  (async () => {
    while (!stopped && !terminal) {
      try {
        await consumeStream();
        if (terminal || stopped) return;
        // Stream closed cleanly without a terminal event — likely a proxy
        // timeout. Reconnect with the resume cursor.
        reconnectAttempts = 0;
      } catch (err: any) {
        if (err.name === "AbortError" || stopped) {
          return;
        }
        reconnectAttempts++;
        if (reconnectAttempts > MAX_RECONNECTS) {
          onEvent({
            phase: "error",
            message: `Lost connection to server after ${MAX_RECONNECTS} reconnect attempts. ${err.message || ""}`.trim(),
          });
          return;
        }
        // Exponential backoff: 1s, 2s, 4s, capped at 8s
        const delay = Math.min(1000 * 2 ** (reconnectAttempts - 1), 8000);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  })();

  return () => {
    stopped = true;
    abortController.abort();
  };
}

/**
 * Convenience wrapper: starts a job and immediately streams its progress.
 * This preserves the original `analyzeStream` API used by Home.tsx.
 */
export function analyzeStream(
  onEvent: (event: AnalyzeEvent) => void,
  auth?: AuthContext
): () => void {
  let cancelStream: (() => void) | null = null;
  let cancelled = false;

  (async () => {
    try {
      const jobId = await startAnalysis(auth);
      if (cancelled) return;
      cancelStream = streamAnalysisJob(jobId, onEvent, auth);
    } catch (err: any) {
      onEvent({
        phase: "error",
        message: err.message || "Failed to start analysis.",
      });
    }
  })();

  return () => {
    cancelled = true;
    if (cancelStream) cancelStream();
  };
}

export async function runOrganize(file: File, auth?: AuthContext): Promise<Proposal> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${BASE}/api/organize`, {
    method: "POST",
    headers: getHeaders(auth, true),
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to generate proposal: ${text}`);
  }

  return res.json();
}

export function executeMovesStream(
  assignments: Pick<ProposalAssignment, "file_name" | "proposed_path" | "drive_id" | "item_id" | "drive_item_path">[],
  autoCreate: boolean,
  onUpdate: (event: any) => void,
  auth?: AuthContext
): () => void {
  const abortController = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/api/execute`, {
        method: "POST",
        headers: getHeaders(auth),
        body: JSON.stringify({ assignments, auto_create_folders: autoCreate }),
        signal: abortController.signal,
      });

      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              onUpdate(JSON.parse(line.slice(6)));
            } catch {
              // ignore partial chunks
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        onUpdate({ phase: "cancelled", message: "Execution cancelled." });
      } else {
        onUpdate({ phase: "error", message: err.message || "Stream failed" });
      }
    }
  })();

  return () => abortController.abort();
}
