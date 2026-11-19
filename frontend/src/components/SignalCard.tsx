import type { AgentResponse } from "../types";
import { CropIcon } from "./CropIcon";

const priceText = (value: number) => Math.round(value).toLocaleString("ko-KR");

export function SignalCard({ r }: { r: AgentResponse }) {
  const s = r.signal!;
  const p = r.tools.price_now;
  const change = p?.dod_pct;
  return (
    <section className="signal" aria-live="polite">
      <div className="signal-top">
        <CropIcon crop={r.item ?? ""} />
        <div>
          <h2>{r.item_name}</h2>
          {r.cultivar && <p className="cultivar">{r.cultivar}</p>}
        </div>
      </div>
      <p className="price-label">전국 도매가격</p>
      <p className="price">
        {p?.price_kg != null ? `${priceText(p.price_kg)}원` : "가격 없음"}
        {p?.price_kg != null && <small> / kg</small>}
      </p>
      <dl className="price-facts">
        {p?.date && (
          <div>
            <dt>마지막 거래</dt>
            <dd className="meta"><time dateTime={p.date}>{p.date}</time></dd>
          </div>
        )}
        {change != null && (
          <div>
            <dt>전 거래일보다</dt>
            <dd>{change === 0 ? "같아요" : `${Math.abs(change).toFixed(1)}% ${change > 0 ? "높아요" : "낮아요"}`}</dd>
          </div>
        )}
      </dl>
      <div className={`signal-status signal-status--${s.deferred ? "deferred" : s.color}`}>
        <strong>{s.label}</strong>
        <p>{r.headline}</p>
      </div>
    </section>
  );
}

export function WhyThisColor({ r }: { r: AgentResponse }) {
  const s = r.signal!;
  return (
    <details className="disclosure why">
      <summary>{s.deferred ? "보류한 이유 보기" : "판단 이유 보기"}</summary>
      <div className="disclosure-body">
        {!s.deferred && <p className="detail">세 가지 조건 중 {s.score}가지가 해당해요.</p>}
        <ul className="conditions">
          {s.conditions.map((c) => (
            <li className="cond" key={c.key}>
              <strong>{c.label}</strong>
              <span className={`condition-label ${c.met === null ? "na" : c.met ? "ok" : "no"}`}>
                {c.met === null ? "비교 불가" : c.met ? "해당" : "해당 없음"}
              </span>
              <p className="detail">{c.detail}</p>
            </li>
          ))}
        </ul>
        {s.notes.length > 0 && (
          <ul className="notes">
            {s.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}
      </div>
    </details>
  );
}
