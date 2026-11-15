import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SeriesPoint } from "../types";

/** 올해 vs 작년(같은 시기) 선 2개. x 축은 '시작일로부터 n번째 거래일' 로 맞춰 겹친다. */
export function PriceChart({ thisYear, lastYear }: { thisYear: SeriesPoint[]; lastYear: SeriesPoint[] }) {
  const n = Math.max(thisYear.length, lastYear.length);
  const data = Array.from({ length: n }, (_, i) => ({
    i,
    date: thisYear[i]?.date ?? "",
    올해: thisYear[i]?.price ?? null,
    작년: lastYear[i]?.price ?? null,
  }));
  const fmt = (v: number) => `${Math.round(v / 100) * 100 >= 1000 ? (v / 1000).toFixed(1) + "천" : Math.round(v)}`;
  return (
    <div>
      <div className="legend">
        <span>
          <i style={{ background: "#1e2a1c" }} />올해
        </span>
        <span>
          <i style={{ background: "#b8c2b0" }} />작년 같은 시기
        </span>
        <span>단위: 원/kg · 거래일만</span>
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#e6ebe1" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 12 }} tickFormatter={(d: string) => (d ? d.slice(5) : "")} minTickGap={28} />
            <YAxis tick={{ fontSize: 12 }} tickFormatter={fmt} width={44} domain={["auto", "auto"]} />
            <Tooltip
              formatter={(v, name) => [v == null || v === "" ? "-" : `${Math.round(Number(v)).toLocaleString("ko-KR")}원`, String(name)]}
              labelFormatter={(l) => String(l ?? "")}
            />
            <Line type="monotone" dataKey="작년" stroke="#b8c2b0" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="올해" stroke="#1e2a1c" strokeWidth={3} dot={false} connectNulls isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
