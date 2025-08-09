export type MethodInfo = { id: string; name: string; version: string };
export type MethodSpec = {
  id: string;
  name: string;
  version: string;
  accepts: string[];
  paramSchema: any;
  uiHints?: Record<string, any>;
};

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL!;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const api = {
  async listMethods(): Promise<MethodInfo[]> {
    return json(await fetch(`${BASE}/methods`));
  },
  async getSpec(id: string): Promise<MethodSpec> {
    return json(await fetch(`${BASE}/methods/${id}/spec`));
  },
  async createRun(methodId: string, data: FormData): Promise<{ run_id: string }> {
    return json(await fetch(`${BASE}/runs?method=${encodeURIComponent(methodId)}`, {
      method: "POST",
      body: data,
    }));
  },
  async getRunStatus(id: string): Promise<{ status: string; progress?: number; message?: string }> {
    return json(await fetch(`${BASE}/runs/${id}/status`));
  },
};
