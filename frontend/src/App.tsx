import { useCallback, useEffect, useRef, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { ask, fetchHealth, fetchItems } from "./api";
import { MarketPanel, VolumePanel, WeatherPanel } from "./components/Panels";
import { CropIcon } from "./components/CropIcon";
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
  const [connectionError, setConnectionError] = useState(false);
  const [requestFailed, setRequestFailed] = useState(false);
  const [big, setBig] = useState(() => safeGet("big") === "1");
  const [kiosk, setKiosk] = useState(() => safeGet("kiosk") === "1");
  const [listening, setListening] = useState(false);
  const idleTimer = useRef<number | null>(null);
  const stopListen = useRef<(() => void) | null>(null);
  const requestId = useRef(0);
  const lastRequest = useRef<Parameters<typeof ask>[0] | null>(null);
  const resultElement = useRef<HTMLElement | null>(null);
  const pickerHeading = useRef<HTMLHeadingElement | null>(null);
  const scrollToResult = useRef(false);

  useEffect(() => {
    if (!(requestFailed || (res && scrollToResult.current)) || !window.matchMedia("(max-width: 860px)").matches) return;
    scrollToResult.current = false;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultElement.current?.focus({ preventScroll: true });
    resultElement.current?.scrollIntoView({ behavior: reducedMotion ? "instant" : "smooth", block: "start" });
  }, [res, requestFailed]);

  const loadItems = useCallback(async () => {
    setConnectionError(false);
    try {
      const [health, list] = await Promise.all([fetchHealth(), fetchItems()]);
      setSynthetic(health.synthetic);
      setItems(list);
    } catch {
      setConnectionError(true);
    }
  }, []);

  useEffect(() => { void loadItems(); }, [loadItems]);

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
        setIntent("overview");
        setError(null);
        setRequestFailed(false);
        lastRequest.current = null;
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
    lastRequest.current = params;
    setLoading(true);
    setRes(null);
    setError(null);
    setRequestFailed(false);
    try {
      const r = await ask(params);
      if (id !== requestId.current) return;
      scrollToResult.current = !params.intents?.includes("volume") && !r.tools.my_volume;
      setRes(r);
      setSelected(r.item);
    } catch {
      if (id !== requestId.current) return;
      setRequestFailed(true);
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
    setIntent("overview");
    setSelected(null);
    void run({ question: t });
  };

  const clarifyItem = (key: string) => {
    const resolved = res?.intent;
    const intents = resolved?.intents.length ? resolved.intents : ["overview" as const];
    setSelected(key);
    setIntent(intents[0]);
    void run({ item: key, intents, boxes: resolved?.boxes ?? undefined });
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

  const returnToPicker = () => {
    pickerHeading.current?.focus({ preventScroll: true });
    pickerHeading.current?.scrollIntoView({ block: "start" });
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
  const sourceNotes = res && <ul className="foot">{res.footnotes.map((f, i) => <li key={i}>{f}</li>)}</ul>;

  return (
    <div className={`app${res?.ok ? " has-result" : ""}`}>
      <header className="top">
        <div className="top-inner">
          <div className="wordmark">
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
            <h1>출하 신호등</h1>
          </div>
          <button className="toggle font-toggle" aria-pressed={big} onClick={() => setBig((v) => !v)}>
            큰 글씨
          </button>
        </div>
      </header>

      <main className="main">
        <div className="workspace">
          <aside className="picker">
            <div className="intro">
              <p>제주 월동채소</p>
              <h2 ref={pickerHeading} tabIndex={-1}>어떤 채소의 시세가 궁금하세요?</h2>
            </div>

            {connectionError && (
              <div className="error" role="alert">
                <p>서버에 연결할 수 없어요. 실행 창을 확인해 주세요.</p>
                <button className="chip" onClick={() => void loadItems()}>연결 다시 시도</button>
              </div>
            )}
            {synthetic && <p className="notice" role="status">시연용 합성 자료예요. 실제 시세와 구분해 주세요.</p>}
            {!connectionError && items.length === 0 && <p role="status" className="notice">품목을 불러오는 중이에요.</p>}

            <nav className="items" aria-label="채소 고르기">
              {items.map((i) => (
                <button key={i.key} className="item-btn" aria-pressed={selected === i.key} disabled={!i.has_data} onClick={() => pickItem(i.key, "overview")}>
                  <CropIcon crop={i.key} />
                  <span className="item-copy">
                    <strong>{i.name}</strong>
                    {loading && selected === i.key ? (
                      <small>시세를 찾는 중</small>
                    ) : (!i.has_data || i.collection_incomplete) && (
                      <small>{i.has_data ? "수집 미완료" : "자료 준비 중"}</small>
                    )}
                  </span>
                  {i.has_data && <span className="row-arrow" aria-hidden="true" />}
                </button>
              ))}
            </nav>

            <details className="disclosure question-panel">
              <summary>질문하기</summary>
              <div className="disclosure-body">
                <form
                  className="ask"
                  onSubmit={(e) => {
                    e.preventDefault();
                    submitQuestion(question);
                  }}
                >
                  <label htmlFor="lookup-question">궁금한 내용을 적어 주세요</label>
                  <input id="lookup-question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="당근 작년보다 비싸요?" />
                  <div className="form-actions">
                    {sttAvailable() && (
                      <button type="button" className="toggle" aria-pressed={listening} onClick={toggleListen}>
                        {listening ? "듣는 중" : "말하기"}
                      </button>
                    )}
                    <button className="primary" type="submit" disabled={loading || connectionError || items.length === 0 || !question.trim()}>
                      묻기
                    </button>
                  </div>
                </form>
                {selected && (
                  <div className="chips" role="group" aria-label="선택한 채소에 대해 묻기">
                    {QUICK.map((q) => (
                      <button key={q.key} className="chip" aria-pressed={intent === q.key} onClick={() => pickItem(selected, q.key)}>
                        {q.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </details>

            <details className="display-settings">
              <summary>화면 설정</summary>
              <div className="chips">
                <button className="toggle" onClick={printResult} disabled={!res?.ok}>인쇄</button>
                <button className="toggle" aria-pressed={kiosk} onClick={() => setKiosk((v) => !v)}>키오스크</button>
              </div>
            </details>
          </aside>

          <section className="result" aria-label="시세 조회 결과" aria-busy={loading} ref={resultElement} tabIndex={-1}>
            {error && <div className="error" role="alert">{error}</div>}

            {requestFailed && (
              <div className="error" role="alert">
                <p>조회 응답을 받지 못했어요. 실행 창을 확인해 주세요.</p>
                <button className="chip" onClick={() => lastRequest.current && void run(lastRequest.current)}>조회 다시 시도</button>
              </div>
            )}
            {!res && !loading && !error && !connectionError && !requestFailed && (
              <div className="empty">채소를 고르면 여기에 시세가 나와요.</div>
            )}
            {loading && <div className="notice" role="status">{item ? `${item.name} 자료를 찾는 중…` : "살펴보는 중…"}</div>}

            {res && !res.ok && (
              <section className="panel">
                <h2>{res.headline}</h2>
                {res.bullets.map((b, i) => <p key={i}>{b}</p>)}
                {res.clarify.length > 0 ? (
                  <div className="chips">
                    {res.clarify.map((c) => <button key={c.item} className="chip" onClick={() => clarifyItem(c.item)}>{c.label}</button>)}
                  </div>
                ) : <button className="toggle" onClick={returnToPicker}>다른 채소 보기</button>}
              </section>
            )}

            {res?.ok && res.signal && item && (
              <>
                {synthetic && <p className="notice demo-note" role="status">시연용 합성 자료예요. 실제 시세가 아니에요.</p>}
                <SignalCard r={res} />
                <div className="result-actions">
                  <button className="toggle" onClick={returnToPicker}>다른 채소 보기</button>
                  <button className="primary" onClick={readAloud}>읽어주기</button>
                </div>

                <WhyThisColor r={res} />

                {res.bullets.length > 1 && (
                  <section className="panel comparison">
                    <h3>가격 비교</h3>
                    <ul>{res.bullets.slice(1).map((b, i) => <li key={i}>{b}</li>)}</ul>
                  </section>
                )}
                {res.llm_explanation && <p className="notice">{res.llm_explanation}</p>}

                {yoy?.ok && yoy.series_this_year && yoy.series_last_year && (
                  <details className="disclosure">
                    <summary>올해와 작년 시세 그래프</summary>
                    <div className="disclosure-body">
                      <PriceChart thisYear={yoy.series_this_year} lastYear={yoy.series_last_year} />
                    </div>
                  </details>
                )}

                {res.tools.weather_effect?.ok && <WeatherPanel w={res.tools.weather_effect} />}
                {res.intent?.intents.includes("weather") && res.tools.weather_effect && !res.tools.weather_effect.ok && (
                  <p className="notice">{res.tools.weather_effect.reason}</p>
                )}
                {res.tools.market_compare && <MarketPanel m={res.tools.market_compare} />}

                {!res.data_state?.collection_incomplete && (
                  <details className="disclosure" open={res.tools.my_volume?.ok || undefined}>
                    <summary>내 물량으로 계산</summary>
                    <div className="disclosure-body">
                      <VolumePanel item={item} result={res.tools.my_volume} onCalc={(boxes) => void run({ item: item.key, intents: ["volume"], boxes })} />
                    </div>
                  </details>
                )}

                <details className="disclosure source-disclosure">
                  <summary>자료 출처와 이용 안내</summary>
                  <div className="disclosure-body">{sourceNotes}</div>
                </details>
                <section className="print-source">
                  <h3>자료 출처와 이용 안내</h3>
                  {sourceNotes}
                </section>
                <details className="disclosure trace">
                  <summary>에이전트가 한 일</summary>
                  <div className="disclosure-body">
                    <ol>{res.trace.map((t, i) => <li key={i}>{t}</li>)}</ol>
                  </div>
                </details>
              </>
            )}
          </section>
        </div>
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
