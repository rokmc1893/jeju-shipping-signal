import { useCallback, useEffect, useRef, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { ask, fetchHealth, fetchItems } from "./api";
import { MarketPanel, VolumePanel, WeatherPanel } from "./components/Panels";
import { PriceChart } from "./components/PriceChart";
import { SignalCard, WhyThisColor } from "./components/SignalCard";
import { listenOnce, speak, sttAvailable, stopSpeaking } from "./speech";
import type { AgentResponse, IntentKey, Item } from "./types";

const QUICK: { key: IntentKey; label: string }[] = [
  { key: "overview", label: "한눈에 보기" },
  { key: "yoy", label: "작년보다 비싸요?" },
  { key: "trend", label: "오르는 중이에요?" },
  { key: "weather", label: "추우면 값 뛰나요?" },
];

const KIOSK_RESET_MS = 60_000;

export default function App() {
  const [synthetic, setSynthetic] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [intent, setIntent] = useState<IntentKey>("overview");
  const [question, setQuestion] = useState("");
  const [res, setRes] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [big, setBig] = useState(() => safeGet("big") === "1");
  const [kiosk, setKiosk] = useState(() => safeGet("kiosk") === "1");
  const [listening, setListening] = useState(false);
  const idleTimer = useRef<number | null>(null);
  const stopListen = useRef<(() => void) | null>(null);
  const requestId = useRef(0);
  const resultElement = useRef<HTMLElement | null>(null);
  const scrollToResult = useRef(false);

  useEffect(() => {
    if (!res || !scrollToResult.current || !window.matchMedia("(max-width: 860px)").matches) return;
    scrollToResult.current = false;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultElement.current?.scrollIntoView({ behavior: reducedMotion ? "instant" : "smooth", block: "start" });
  }, [res]);

  useEffect(() => {
    fetchHealth().then((health) => setSynthetic(health.synthetic)).catch(() => {});
    fetchItems().then(setItems).catch(() => setError("서버에 연결할 수 없어요. 실행 창이 열려 있는지 확인해 주세요."));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.big = big ? "1" : "0";
    safeSet("big", big ? "1" : "0");
  }, [big]);
  useEffect(() => {
    document.documentElement.dataset.kiosk = kiosk ? "1" : "0";
    safeSet("kiosk", kiosk ? "1" : "0");
  }, [kiosk]);

  // 키오스크: 60초 무입력 → 첫 화면
  useEffect(() => {
    if (!kiosk) return;
    const reset = () => {
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
      idleTimer.current = window.setTimeout(() => {
        requestId.current += 1;
        setLoading(false);
        setRes(null);
        setSelected(null);
        setQuestion("");
        stopSpeaking();
        stopListen.current?.();
        setListening(false);
      }, KIOSK_RESET_MS);
    };
    reset();
    const evs = ["click", "keydown", "touchstart", "mousemove"];
    evs.forEach((e) => window.addEventListener(e, reset));
    return () => {
      evs.forEach((e) => window.removeEventListener(e, reset));
      if (idleTimer.current) window.clearTimeout(idleTimer.current);
    };
  }, [kiosk]);

  const run = useCallback(async (params: Parameters<typeof ask>[0]) => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const r = await ask(params);
      if (id !== requestId.current) return;
      scrollToResult.current = !params.intents?.includes("volume") && !r.tools.my_volume;
      setRes(r);
      if (r.item) setSelected(r.item);
    } catch (e) {
      if (id !== requestId.current) return;
      setError(e instanceof Error ? e.message : "알 수 없는 오류가 났어요.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  const pickItem = (key: string, i: IntentKey = intent) => {
    setSelected(key);
    setIntent(i);
    void run({ item: key, intents: [i] });
  };

  const submitQuestion = (q: string) => {
    const t = q.trim();
    if (!t) return;
    setQuestion(t);
    void run({ question: t });
  };

  const toggleListen = () => {
    if (listening) {
      stopListen.current?.();
      setListening(false);
      return;
    }
    const stop = listenOnce(
      (t) => {
        setQuestion(t);
        submitQuestion(t);
      },
      () => setListening(false),
      setError,
    );
    if (stop) {
      stopListen.current = stop;
      setListening(true);
    }
  };

  const readAloud = () => {
    if (!res) return;
    const text = [res.headline, ...res.bullets, ...res.extra_sentences].filter(Boolean).join(" ");
    if (!speak(text)) setError("이 브라우저에서는 읽어주기를 지원하지 않아요.");
  };

  const printResult = () => {
    if (Capacitor.isNativePlatform()) {
      setError("앱에서는 바로 인쇄할 수 없어요. 컴퓨터에서 같은 자료를 열어 인쇄해 주세요.");
      return;
    }
    try {
      if (typeof window.print !== "function") throw new Error();
      window.print();
    } catch {
      setError("이 기기에서는 바로 인쇄할 수 없어요. 컴퓨터에서 같은 자료를 열어 인쇄해 주세요.");
    }
  };

  const item = items.find((i) => i.key === (res?.item ?? selected));
  const yoy = res?.tools.yoy_compare;

  return (
    <div className="app">
      <header className="top">
        <h1>출하 신호등</h1>
        <span className="date">제주 월동채소 · {res?.asof ?? new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" })}</span>
        <span className="spacer" />
        <button className="toggle" aria-pressed={big} onClick={() => setBig((v) => !v)}>
          큰 글씨
        </button>
        <button className="toggle" onClick={readAloud} disabled={!res?.ok}>
          읽어주기
        </button>
        <button className="toggle" onClick={printResult} disabled={!res?.ok}>
          인쇄
        </button>
        <button className="toggle" aria-pressed={kiosk} onClick={() => setKiosk((v) => !v)}>
          키오스크
        </button>
      </header>

      {synthetic && <div className="error" role="status">시연용 합성 자료입니다. 실제 시세가 아니며 출하 판단에 사용하면 안 됩니다.</div>}
      <main className="main">
        <aside>
          <nav className="items" aria-label="작물 고르기">
            {items.map((i) => (
              <button key={i.key} className="item-btn" aria-pressed={selected === i.key} disabled={!i.has_data} onClick={() => pickItem(i.key)}>
                {i.name}
                <small>{i.has_data ? `${i.region} · 원/kg` : "자료 준비 중"}</small>
              </button>
            ))}
          </nav>
          <form
            className="ask"
            onSubmit={(e) => {
              e.preventDefault();
              submitQuestion(question);
            }}
          >
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="말로 물어보기: 당근 작년보다 비싸요?" aria-label="질문" />
            {sttAvailable() && (
              <button type="button" className="mic" aria-pressed={listening} onClick={toggleListen} aria-label="마이크">
                {listening ? "듣는 중" : "말하기"}
              </button>
            )}
            <button type="submit" disabled={loading}>
              묻기
            </button>
          </form>
          <div className="chips" role="group" aria-label="자주 묻는 질문">
            {QUICK.map((q) => (
              <button key={q.key} className="chip" aria-pressed={intent === q.key} onClick={() => (selected ? pickItem(selected, q.key) : setIntent(q.key))}>
                {q.label}
              </button>
            ))}
          </div>
        </aside>

        <section className="result" aria-busy={loading} ref={resultElement}>
          {error && <div className="error" role="alert">{error}</div>}

          {!res && !loading && <div className="empty">작물을 고르면 최근 시세와 신호를 보여드려요.</div>}
          {loading && <div className="empty">살펴보는 중…</div>}

          {res && !res.ok && res.clarify.length > 0 && (
            <div className="panel">
              <h3>{res.headline}</h3>
              <div className="chips">
                {res.clarify.map((c) => (
                  <button key={c.item} className="chip" onClick={() => pickItem(c.item, "overview")}>
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {res && !res.ok && res.clarify.length === 0 && (
            <div className="panel">
              <h3>{res.headline}</h3>
              {res.bullets.map((b, i) => (
                <p key={i}>{b}</p>
              ))}
            </div>
          )}

          {res?.ok && res.signal && item && (
            <>
              <SignalCard r={res} />
              <ul className="bullets">
                {res.bullets.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
              {res.llm_explanation && <div className="explain">{res.llm_explanation}</div>}
              <WhyThisColor r={res} />

              {yoy?.ok && yoy.series_this_year && yoy.series_last_year && (
                <section className="panel">
                  <h3>올해와 작년, 같은 시기 가격</h3>
                  <PriceChart thisYear={yoy.series_this_year} lastYear={yoy.series_last_year} />
                </section>
              )}

              {res.tools.weather_effect && <WeatherPanel w={res.tools.weather_effect} />}
              {res.tools.market_compare && <MarketPanel m={res.tools.market_compare} />}

              <VolumePanel item={item} result={res.tools.my_volume} onCalc={(boxes) => void run({ item: item.key, intents: ["volume"], boxes })} />

              <ul className="foot">
                {res.footnotes.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
              <details className="trace">
                <summary>에이전트가 한 일</summary>
                <ol>
                  {res.trace.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ol>
              </details>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function safeGet(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function safeSet(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* 무시 */
  }
}
