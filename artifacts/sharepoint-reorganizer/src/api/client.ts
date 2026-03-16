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

function getHeaders(isFormData = false) {
  const headers: Record<string, string> = {
    "X-API-Key": KEY,
  };
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export async function checkHealth(): Promise<{ status: string }> {
  try {
    const res = await fetch(`${BASE}/health`);
    if (!res.ok) throw new Error("Health check failed");
    return res.json();
  } catch (err) {
    return { status: "error" };
  }
}

export async function testConnection(): Promise<{ success: boolean; message: string }> {
  try {
    const res = await fetch(`${BASE}/api/test-connection`, {
      method: "POST",
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error("Connection failed");
    return { success: true, message: "Successfully connected to SharePoint." };
  } catch (err: any) {
    return { success: false, message: err.message || "Failed to connect to SharePoint." };
  }
}

export async function runOrganize(file: File): Promise<Proposal> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${BASE}/api/organize`, {
    method: "POST",
    headers: getHeaders(true),
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
  onUpdate: (event: any) => void
): () => void {
  const abortController = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/api/execute`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ assignments, autoCreate }),
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
              const data = JSON.parse(line.slice(6));
              onUpdate(data);
            } catch (e) {
              // Ignore partial chunk parse errors
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        onUpdate({ phase: "error", message: "Execution cancelled by user." });
      } else {
        onUpdate({ phase: "error", message: err.message || "Stream failed" });
      }
    }
  })();

  return () => abortController.abort();
}
