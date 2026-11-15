export type Color = "green" | "yellow" | "red";

export interface Condition {
  key: string;
  label: string;
  met: boolean | null;
  detail: string;
  value: number | null;
}

export interface Signal {
  color: Color;
  label: string;
  score: number;
  conditions: Condition[];
  notes: string[];
  confidence: "high" | "mid" | "low" | "none";
}

export interface SeriesPoint {
  date: string;
  price: number | null;
  volume?: number | null;
}

export interface Tools {
  price_now?: { ok: boolean; date?: string; price_kg?: number; dod_pct?: number | null; is_asof_closed?: boolean; reason?: string };
  trend_ma?: { ok: boolean; ma_short?: number; ma_long?: number; direction?: string; series?: SeriesPoint[]; reason?: string };
  yoy_compare?: { ok: boolean; yoy_pct?: number; last_year_mean?: number; series_this_year?: SeriesPoint[]; series_last_year?: SeriesPoint[]; reason?: string };
  weather_effect?: { ok: boolean; cold?: { events: number; enough: boolean; change_pct: number | null }; rain?: { events: number; enough: boolean; change_pct: number | null }; after_days?: number; reason?: string };
  market_compare?: { ok: boolean; markets?: { market: string; price_kg: number; volume_ton: number; vs_overall_pct: number | null }[]; best?: { market: string }; jeju?: { market: string; price_kg: number } | null; reason?: string };
  my_volume?: { ok: boolean; boxes?: number; unit_label?: string; total_kg?: number; revenue?: Record<string, number>; unit_price?: Record<string, number>; low?: number; high?: number; note?: string; reason?: string };
}

export interface DataState {
  ok: boolean;
  last_trading_day: string | null;
  days_since_last: number | null;
  trading_days_30: number;
  trading_days_total: number;
  first_date: string | null;
  confidence: string;
  warnings: string[];
}

export interface AgentResponse {
  ok: boolean;
  mode: string;
  item: string | null;
  item_name: string | null;
  cultivar: string | null;
  asof: string;
  signal: Signal | null;
  headline: string | null;
  bullets: string[];
  extra_sentences: string[];
  llm_explanation: string | null;
  tools: Tools;
  data_state: DataState | null;
  footnotes: string[];
  clarify: { item: string; label: string }[];
  trace: string[];
}

export interface Item {
  key: string;
  name: string;
  cultivars: string[];
  default_cultivar: string;
  unit: { label: string; kg: number; verify?: boolean };
  jeju_share: "high" | "mid" | "low";
  region: string;
  has_data: boolean;
}

export type IntentKey = "overview" | "price_now" | "trend" | "yoy" | "weather" | "market" | "volume";
