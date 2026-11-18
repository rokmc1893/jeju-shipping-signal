import type { AgentResponse } from "../types";

const won = (v?: number | null) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);

export function SignalCard({ r }: { r: AgentResponse }) {
  const s = r.signal!;
  const p = r.tools.price_now;
  return (
    <section className="signal" aria-live="polite">
      <div className={`lamp ${s.color}`} role="img" aria-label={`신호: ${s.label}`}>
        {s.label}
      </div>
      <div>
        <h2>{r.headline}</h2>
        <div className="price">
          {won(p?.price_kg)}
          <small>
            / kg
          </small>
        </div>
        <div className="meta">
          전국 도매가격
          {p?.dod_pct != null && ` · 전 거래일보다 ${p.dod_pct > 0 ? "+" : ""}${p.dod_pct}%`}
          {p?.date && ` · ${p.date} 거래 기준`}
        </div>
      </div>
    </section>
  );
}

export function WhyThisColor({ r }: { r: AgentResponse }) {
  const s = r.signal!;
  return (
    <details className="why">
      <summary>왜 이 색인가요? — 3가지 중 {s.score}가지 해당</summary>
      {s.conditions.map((c) => (
        <div className="cond" key={c.key}>
          <span className={`mark ${c.met === null ? "na" : c.met ? "ok" : "no"}`} aria-hidden="true">
            {c.met === null ? "?" : c.met ? "○" : "×"}
          </span>
          <div>
            <div>{c.label}</div>
            <div className="detail">{c.detail}</div>
          </div>
        </div>
      ))}
      {s.notes.length > 0 && (
        <ul className="notes">
          {s.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      <p className="detail" style={{ marginTop: "0.6rem" }}>
        초록 = 3가지 모두 해당 · 노랑 = 1~2가지 · 빨강 = 하나도 없음. 자료가 부족하면 노랑으로 표시해요.
      </p>
    </details>
  );
}
