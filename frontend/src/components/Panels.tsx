import { Fragment, useState } from "react";
import type { AgentResponse, Item } from "../types";

const won = (v?: number | null) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);

export function VolumePanel({ item, onCalc, result }: { item: Item; onCalc: (boxes: number) => void; result?: AgentResponse["tools"]["my_volume"] }) {
  const [boxes, setBoxes] = useState<string>("");
  const n = Number(boxes);
  return (
    <section className="panel">
      <h3>내 물량으로 계산</h3>
      <div className="volume">
        <input type="number" inputMode="numeric" min={1} placeholder="0" value={boxes} onChange={(e) => setBoxes(e.target.value)} aria-label={`${item.unit.label} 수`} />
        <span>
          {item.unit.label} (1{item.unit.label} = {item.unit.kg}kg)
        </span>
        <button onClick={() => n > 0 && onCalc(n)} disabled={!(n > 0)}>
          계산하기
        </button>
      </div>
      {result?.ok && result.revenue && (
        <div>
          <div className="range">
            약 {won(result.low)} ~ {won(result.high)}
          </div>
          <div className="scen">
            {Object.entries(result.revenue).map(([k, v]) => (
              <Fragment key={k}>
                <span>{k} 기준</span>
                <strong>{won(v)}</strong>
              </Fragment>
            ))}
          </div>
          <p style={{ color: "var(--ink-soft)", fontSize: "0.85rem" }}>{result.note}</p>
        </div>
      )}
    </section>
  );
}

export function MarketPanel({ m }: { m: NonNullable<AgentResponse["tools"]["market_compare"]> }) {
  if (!m.ok || !m.markets?.length) return null;
  const max = Math.max(...m.markets.map((x) => x.price_kg));
  return (
    <section className="panel">
      <h3>어느 시장이 더 쳐주나 (최근 거래일 기준)</h3>
      <div className="markets">
        {m.markets.map((x) => (
          <div className={`mrow ${x.market.includes("제주") ? "jeju" : ""}`} key={x.market}>
            <span>{x.market}</span>
            <div className="mbar" style={{ width: `${(x.price_kg / max) * 100}%` }} aria-hidden="true" />
            <strong>{won(x.price_kg)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export function WeatherPanel({ w, sentence }: { w: NonNullable<AgentResponse["tools"]["weather_effect"]>; sentence?: string }) {
  if (!w.ok) return <section className="panel"><h3>과거 날씨와 가격</h3><p>{w.reason ?? "기상 자료를 아직 준비하지 못했어요."}</p></section>;
  const row = (label: string, x?: { events: number; enough: boolean; change_pct: number | null }) =>
    x?.enough ? (
      <p>
        <strong>{label}</strong> 뒤 {w.after_days}거래일 가격: 평소보다 {x.change_pct! > 0 ? "+" : ""}
        {x.change_pct}% <span style={{ color: "var(--ink-soft)" }}>({x.events}회)</span>
      </p>
    ) : (
      <p>
        <strong>{label}</strong>: 사례가 아직 부족해요
      </p>
    );
  return (
    <section className="panel">
      <h3>날씨가 오면 값은 어땠나 (산지 관측소, 과거 2년)</h3>
      {row("한파(최저 0℃ 이하)", w.cold)}
      {row("비(10mm 이상)", w.rain)}
      {sentence && <p style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>{sentence}</p>}
    </section>
  );
}
