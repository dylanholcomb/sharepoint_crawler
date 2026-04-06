const BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";
const KEY = import.meta.env.VITE_API_KEY || "";

export interface ProposalAssignment {
  file_name: string;
  current_path: string;
  proposed_path: string;
  reason?: string;
  confidence?: number;
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

export async function runAnalyze(auth?: AuthContext): Promise<Proposal> {
  const res = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    headers: getHeaders(auth),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to analyze SharePoint: ${text}`);
  }

  return res.json();
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
  assignments: { file_name: string; proposed_path: string }[],
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
