import type { AgentResponse, IntentKey, Item } from "./types";

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
if (apiBase) {
  const url = new URL(apiBase);
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("공개 API 주소에 계정 정보나 키를 넣을 수 없습니다.");
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
    throw new Error("API 서버는 HTTPS 또는 로컬 개발 주소를 사용해야 합니다.");
  }
}

// 이 서비스는 계정 로그인을 사용하지 않는다. 브라우저 쿠키를 API에 보내지 않는다.
function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${apiBase}${path}`, { ...init, credentials: "omit" });
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`서버 응답 오류 (${res.status})`);
  return (await res.json()) as T;
}

export async function fetchItems(): Promise<Item[]> {
  return json(await request("/api/items"));
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
    await request("/api/ask", {
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
  return json(await request("/api/briefing"));
}

export async function fetchHealth(): Promise<{ synthetic: boolean }> {
  return json(await request("/api/health"));
}
