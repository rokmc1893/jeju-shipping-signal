import type { AgentResponse, IntentKey, Item } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`서버 응답 오류 (${res.status})`);
  return (await res.json()) as T;
}

export async function fetchItems(): Promise<Item[]> {
  return json(await fetch("/api/items"));
}

export interface AskParams {
  item?: string;
  question?: string;
  intents?: IntentKey[];
  boxes?: number;
  use_llm_explain?: boolean;
}

export async function ask(params: AskParams): Promise<AgentResponse> {
  return json(
    await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );
}

export interface Briefing {
  asof: string;
  items: { item: string; name: string | null; ok: boolean; signal: AgentResponse["signal"]; headline: string | null; bullets: string[] }[];
}

export async function fetchBriefing(): Promise<Briefing> {
  return json(await fetch("/api/briefing"));
}

export async function fetchHealth(): Promise<{ synthetic: boolean }> {
  return json(await fetch("/api/health"));
}
