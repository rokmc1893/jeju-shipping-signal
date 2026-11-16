# 모바일 앱 작업 · 2026-11-16

- 사용자 요청: 갤럭시 크기의 실제 Android 에뮬레이터를 보면서 개발한다. iOS·Android UI를 공유하며 개인 Google·Chrome 계정 정보를 앱 사용자에게 노출하지 않는다.
- Capacitor 8.6.2 Android/iOS 프로젝트, 모바일 safe area·터치·큰 글씨·응답 순서 보호·음성 오류 처리를 추가했다. 앱에서는 음성 인식을 숨기고 인쇄 안내를 제공한다.
- 전용 AVD `Jeju_Galaxy_S24`, Android 16, 1080×2340·480dpi다. 앱 ID `io.github.rokmc1893.jejusignal`을 설치했다. 실제 삼성 OS는 아니다.
- `start_mobile.command`와 `scripts/mobile_dev.py`가 로컬 서버·에뮬레이터·빌드·설치를 연결한다. 백엔드 8000, Vite 5173, adb reverse를 사용한다. `.env`와 기본 실데이터 캐시는 변경하지 않는다.
- Android APK 빌드·설치·별도 앱 실행, iOS generic simulator 빌드, pytest37·웹 빌드·npm audit 0개를 확인했다. Chromium/WebKit 모바일 화면·입력·쿠키 제외도 검사했다.
- 기본 실데이터 수집·5품목 E2E, iOS 실행 런타임·앱 실행, 삼성 실기기·음성·배포 검증은 남았다. 개발 APK는 타인에게 배포하지 않는다.
- 코드 리뷰 서브에이전트가 native CORS·인쇄 no-op·release API 메타데이터 검증 문제를 지적했고 수정했다. 최종 재검토에서 새로 보고할 미해결 P0/P1/P2 결함은 없었다. 리뷰는 소스·diff를 읽는 방식이며 실제 빌드는 본 작업에서 별도로 확인했다.
- 개발 사진은 저장소에 올리지 않는다. 확인용 캡처·개발 로그·개인 서명 키·SDK 로컬 경로·native 빌드 결과는 git에서 제외한다.
- 상세 실행법과 현재 제한은 [docs/MOBILE.md](docs/MOBILE.md)에 있다.

---

# 저장소 재생성 · 2026-11-16

사용자 요청으로 기존 GitHub 저장소를 삭제하고 같은 이름으로 다시 생성한다. 이전 작성자·공동 작성자 이력을 게시하지 않고 유소민 계정의 새 커밋 하나로 시작한다. 이전 Git 이력과 저장소 설정·PR 정보는 로컬 `outputs/backups`에 보관하며 업로드하지 않는다.

개발 화면 캡처는 저장소와 README에서 제외한다. 아래 기록은 이전 점검 당시의 사실이며, 과거 커밋·PR·CI 식별자는 새 저장소에서 유효하지 않다. 실제 AI 도구 활용 내역은 README에 유지한다.

---

# 최신 인계 상태 · Codex 점검 (2026-11-15)

이 문서 아래 원본은 과거 담당자의 인계 기록이다. 현재 상태는 [제출 준비 점검](docs/READINESS.md)을 우선한다.

- GitHub 저장소: https://github.com/rokmc1893/jeju-shipping-signal 이다. 원격을 연결하고 기존 커밋을 업로드했다.
- 로컬 pytest 34개, 프론트 타입 검사·빌드, npm audit 취약점 0개를 확인했다. 합성 자료와 API 기반 검증이며 실데이터 재검증은 아니다.
- 기본 CSV 캐시는 점검 당시 비어 있었다. 시연용 합성 캐시는 `outputs/local-demo/cache`로 분리했다.
- 버튼 LLM 호출·환산 각주·기상 반복 중단·초기 프론트 빌드·API 입력·합성 자료 혼합·모바일 너비를 보완했다.
- `unit.verify`는 외부 규격 확인 완료 시 `true`다. 상자·망 무게는 확인 전이므로 `false`로 두며 환산 각주를 표시한다. 아래 원본의 반대 설명을 따르지 않는다.
- 원본의 ‘AI 환경에서 npm·pip·허브 접근이 모두 차단된다’는 설명은 이전 환경에 관한 기록이다. 이번 환경에서는 npm·pip·GitHub를 사용했다. 허브 API 재수집은 아직 하지 않았다.
- Claude에 전달할 요청은 [프롬프트 문서](docs/CLAUDE_REVIEW_PROMPT.md)에 있다. 원본 기획서 내보내기와 근거 검토가 우선이다.
- 다음 작업은 실데이터 적재·5품목 E2E, 공식 규칙과 이용조건·단위 확인, 제출 문서·ZIP 작성, 센터 PC 직접 검증이다.

---

# 인계 문서 — 「출하 신호등 — 제주 월동채소 편」

> 작성: 2026-11-15 20:00 KST (D-5). 이 문서 하나로 다음 담당(AI 에이전트 포함)이 작업을 그대로 이어갈 수 있도록 **대회 규칙·전략·결정 사유·실측 결과·코드 구조·현재 상태·남은 일·사람 수작업**을 전부 담았다.
> 참가자: **유소민 (개인 참가)**, GitHub `rokmc1893`, 개발 PC macOS(`~/Downloads/jeju-shipping-signal`), 센터 PC는 Windows.

---

## 0. 한 줄 요약

제주 농가 어르신이 **당근·무·양배추 버튼 하나** 누르면 오늘 도매 시세·작년 비교·날씨 영향을 종합해 **출하 참고 / 관망 / 주의**를 신호등 색과 쉬운 말로 알려주는 AI 에이전트. **백엔드·판단 엔진·React 프론트·수집기·기획서 초안이 완성**돼 있고, 지금은 **실데이터 적재 → 화면 확인 → 폴리시 → 제출** 단계다.

---

## 1. 대회 정보 (DAKER · 제주테크노파크)

| 항목 | 내용 |
|---|---|
| 대회명 | 제주 AI·빅데이터 활용 AI Agent 개발 챌린지 (https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge) |
| 주제 | 제주빅데이터센터 또는 제주데이터허브 데이터 **1종 이상** 활용, 데이터 탐색→분석 결과 제공까지 자동화하는 AI Agent. **IT 비전문가 도민이 센터에서 직접 실행·활용** 가능해야 함 |
| 센터 PC 사양 | Intel i7-8700 / GTX 1060 6GB / RAM 32GB |
| **제출 마감** | **2026-11-20(금) 10:00 KST** (이후 수정 불가, 사전 제출 권장) |
| 제출 방법 | DAKER [갤러리] → [기획서 및 최종 결과물 제출] |
| 제출물 ① | **AI Agent 기획서 15p 이내**: 구현목표 / 서비스 제안 / Agent 개발 구성(역할·Workflow·모델·Tool/API·자율 수행 범위) / 데이터 활용 계획(데이터명·출처·활용 항목·수집·전처리·이용조건) / 개발·탑재 계획(구현 범위·기술 환경·UI·센터 실행환경·외부 의존성) |
| 제출물 ② | **최종 결과물 zip**: 실행 소스(Agent 코드·프롬프트·Tool/API·데이터 처리·모델/라이브러리), 실행환경·매뉴얼(README·설치·의존성·환경변수 예시·사용자 매뉴얼·제약), 데이터 활용 명세(사용 데이터·출처·이용조건·전처리·외부 데이터/오픈소스), 결과 설명자료(문제 정의·Agent 구조·기능·실행 결과·검증·한계·센터 활용 방안) |
| 평가 | 전문가 70% (주제 타당성·창의성 15 / 데이터 활용 적절성 20 / **AI Agent 기술성·완성도 25** / **편의성·실용성 25** / 신뢰성·재현성 15) + **ELO 상호평가 30%** (11/23 12:00~11/27 10:00, **최소 투표 안 하면 내 점수 미반영 — 반드시 참여**) |
| 동점 처리 | 기술성·완성도 → 편의성·실용성 → 데이터 활용 순 |
| 수상 발표 | 11/30. 시상식 12/7(월) 제주테크노파크 **참석·발표 필수** |
| 규칙 | 생성형 AI 사용 가능하나 **사용 모델·AI 활용 범위·외부 API·외부 데이터·오픈소스 명시 필수**. API 키·개인정보 제출물 포함 금지. 타 공모전 수상작·공개 결과물 재제출 금지. 결과물 소유권 제주빅데이터센터 귀속, 수상작은 5년 비독점 라이선스. 허브에서 받은 데이터목록 xlsx 외부 배포 금지 |
| 상금 | 대상 300만(도지사상), 최우수 100만, 우수 50만×2. 전원 수료증 |

---

## 2. 전략 (왜 이렇게 만들었나)

1. **분석 대회가 아니라 제품 대회** — 기술성 25 + 편의성 25 + 재현성 15 = 65점이 "안 깨지는 서비스"에 걸려 있다. 5개 시나리오를 완벽하게 > 20개를 그럭저럭.
2. **Tool-first, LLM-last** — LLM은 ① 자유 질문 의도 추출(JSON) ② 숫자를 쉬운 말로 설명, 두 가지만. **숫자 계산·신호 색 판단은 전부 결정론 규칙**(pandas). 데모 중 환각·실패 위험 제거, GTX 1060 병목 회피.
3. **버튼 경로는 LLM 0회** — 품목 버튼 → 고정 Tool 플랜 → 규칙 판단 → 템플릿 문장. 인터넷·GPU·LLM 없이 완전 동작 → "콘센트 뽑기" 테스트 통과(재현성).
4. **로컬 캐시 우선** — 허브 API는 수집 시에만, 조회는 CSV 캐시만. 심사 당일 라이브 호출 의존 금지.
5. **한계를 숨기지 않고 각주로** — 산지 미구분·전국 기준·예측 아님을 모든 답에 자동 삽입(신뢰성).
6. **차별화** — 허브에 이미 '품종별 가격 전망'(예측) 응용서비스가 있음 → 우리는 **예측 금지, 의사결정 지원**(신호등·농가 단위 환산·날씨 교차·음성·인쇄)으로 간다.

### 자체 평가 체크리스트 (기획서 6절, 각 20점)
Q1 결정론 커버리지 / Q2 30초·무타이핑 / Q3 데이터 결정력·단위 일치 / Q4 콘센트 뽑기 / Q5 So-what·차별화 → 현재 자체 채점 96/100.

### 주제 피벗 기록
- 최초 후보 3개: 버스 돋보기(교통) / 동네 손님 지도(유동인구·카드) / **출하 신호등(농산물)** → 사용자 선택: 출하 신호등.
- 원래 **감귤**이었으나 허브 농산물 거래 API 품목이 **당근·마늘·무·양배추·양파 5종뿐** → **월동채소로 피벗**. 출하기(11~3월)가 심사 기간과 겹쳐 라이브 데모 가능, 과잉생산·산지폐기 문제가 더 절박 → 오히려 유리.

---

## 3. 데이터 — 실측 결과 (2026-11-15, 프로젝트 키로 직접 호출)

### 사용 데이터셋 (제주데이터허브 Open API, 모두 프로젝트에 '담기' 완료)
| ID | 이름 | dataKey | 용도 | 쿼터/일 |
|---|---|---|---|---|
| 1361 | 농산물 품종별 일일 거래 통계 | `13t6aat1at6166111Dtt1taa1ta1661t` | **핵심**: 일별 평균가·거래량·거래금액 | 3000 |
| 1362 | 농산물 품종별 일일 거래 정보 | `1tb1t233D16Da1b3333tttb266ba11D3` | 시장×법인별 — **표본 한계로 기본 비활성화** | 3000 |
| 579 | 일별 기상 정보 | `1aD5taat1attaa51Db1511b51ab9Da19` | 산지 관측소 한파·강수 → 과거 패턴 | 1000 |
| 578 | 기상관측소 정보 | `t1bab75a555a15715btaa7a5abaa1aab` | 관측소 목록 | 1000 |
| 1360 | 거래 이동평균 | — | **사용 안 함** (자체 계산) | — |

원천: aT 도매유통정보시스템(전국 공영도매시장, **산지 구분 없음**), 기상청.

### API 동작 특성 (코드에 전부 반영됨)
| 사실 | 대응 |
|---|---|
| URL `https://open.jejudatahub.net/api/proxy/{dataKey}/{projectKey}?param=…` | `.env JEJU_HUB_BASE_URL` 기본값 |
| 응답 `{totCnt, hasMore, data[]}`, **한 번에 최대 10행**, page/offset/limit 등 **페이징 파라미터 전부 무시** | `hub_client.fetch_range`: 10일 창 + hasMore 면 창을 반으로 쪼개 재호출 |
| 연속 호출 시 간헐 실패(`Failed to fetch`, ≈초당 1회 제한). 브라우저에서 성공:실패 ≈ 1:1 | 호출 간격 1.2s, 재시도 4회(1.5s×n 백오프), timeout 12s |
| **일요일·공휴일은 행 자체가 없음** (응용서비스 화면의 0.00 은 사이트가 채운 것) | 거래일 기준 계산. `data_store.apply_closed_day_rule`(0&0→NaN)은 방어용으로 유지 |
| 거래 통계: 당근(일반) **2016-01-04 ~ 2026-11-14** 수신 확인 (메타데이터의 2025-10-31 종료 표기와 달리 갱신 중) | — |
| 품종 문자열(필수 파라미터 `cultivar`) — 응용서비스 드롭다운+실호출로 확정 | 당근: `당근(일반)`* `흙당근` `세척당근` / 무: `월동무`* `세척무` / 양배추: `양배추(일반)`* `저장양배추` / 마늘: `깐마늘`* `마늘` `햇마늘 남도` `저장형 남도` `저장형 난지` / 양파: `조생양파`* `중만생양파` `만생양파` `저장양파` (*=기본). `무(일반)` `양파(일반)` `당근` `무` 는 **없음** |
| 거래 정보(1362): 하루 27행(시장×법인)인데 10행만 반환, 분할 불가 | `rules.market_compare_enabled: false`. 시장 비교 기능은 "선택(표본 한계)"로 기획서 표기 |
| 기상(579): `searchDate` 하루 1콜. 관측소 필터 없으면 **10곳만**(중문·산천단·대흘·추자도·우도·마라도·유수암·선흘·서광·어리목). `observatoryName` 지정 시 1곳/콜. **2025-03 자료 있음, 2025-10 이후 0건 → 갱신 지연** | 출하기 월(10~4월)만, 필요 관측소(구좌·성산·한림; 서광은 기본 10곳 포함)별 수집, 하루 예산 900콜, 여러 날 분할. 날씨는 **과거 패턴 분석용**으로만 |

### 실데이터 검증 결과 (당근(일반), 기준일 2026-11-15)
🟡 관망 — 오늘 1,781원/kg(1상자 20kg 35,620원) vs 30거래일 평균 2,005원(−11.2%), 7거래일 평균 하락(−8.3%), 작년 동기 894원 대비 **+99%** (2025-11 당근 폭락기 — 문제정의 근거로 활용 가능). 거래일 24/30, 신뢰도 high, 휴장일 자동 전환 동작.

### 프로젝트 키
- 제주데이터허브 마이페이지 → 프로젝트 관리 → "My Project"(id 4776) → 프로젝트키. **`.env` 에만 저장**(zip·채팅·문서·git 에 넣지 말 것. `.gitignore` 처리됨).
- 허브 계정은 유소민 본인. 로그인은 본인만.

---

## 4. 아키텍처

```
[React+TS (Vite, Recharts)]  ──HTTP──▶  [FastAPI app/main.py]
   품목 버튼 / 자유 질문 / 음성             │
                                          ▼
                                   [agent.py 오케스트레이션]
   버튼 경로: LLM 0회 ─────▶ 고정 Tool 플랜 ─┐
   자유질문 경로: intent.py (규칙 1차 + LLM JSON 보강) ─┘
                                          ▼
                 [tools.py 결정론 Tool 6종] ◀── [data_store.py CSV 캐시] ◀── [hub_client.py] ◀── 허브 API
                 price_now / trend_ma / yoy_compare / weather_effect / market_compare(off) / my_volume
                                          ▼
                 [judge.py 데이터 상태 점검 + 3조건 신호등 + 신뢰도] → [templates.py 쉬운 말] → (선택) [llm.py 설명 보강]
```

### 신호등 규칙 (`config/items.yaml rules`, 화면 '왜 이 색?'에 수치와 함께 노출)
- A 오늘가 > 최근 30거래일 평균 / B 7거래일 평균이 직전 7거래일 대비 +1% 초과 / C 작년 동기(±3일, 거래일만) 대비 ≥ 0%
- 3개 → 🟢 출하 참고 / 1~2개 → 🟡 관망 / 0개 → 🔴 주의
- 최근 30일 거래일 < 10 또는 판단불가 조건 ≥ 2 → 🟡 고정 + 사유 표시
- 보조 메모(색 불변): 거래량 평소 1.5배↑ 출하 집중 경고, 최근 7일 내 한파(최저 ≤0℃)·우천(≥10mm) 과거 패턴
- 하단 고정 문구: "과거 거래 자료 기준 참고 신호, 예측 아님, 출하 결정 책임은 농가"

### 에이전트 자율 판단 5가지 (trace 에 기록 → 화면 '에이전트가 한 일', 기획서 근거)
① 품목 못 찾으면 칩으로 되묻기 ② 기준일 휴장이면 직전 거래일로 전환 ③ 관측소 자료 없으면 fallback 관측소 ④ 자료 부족이면 관망으로 강등 ⑤ 의도별 Tool 선택(overview 면 전부)

### LLM (선택)
`.env LLM_PROVIDER = none | openai | ollama`. openai 호환(Upstage 등 `OPENAI_BASE_URL`) 기본 + Ollama `exaone3.5:7.8b`(Q4, 1060 6GB 적재) 폴백. none 이어도 모든 기능 동작. 설명 생성 프롬프트는 `templates.LLM_EXPLAIN_PROMPT` — 숫자 변경·예측·색 변경 금지.

---

## 5. 파일 구조 (repo: `~/Downloads/jeju-shipping-signal`, 첫 커밋 완료, 43 파일)

```
.env                 ← 프로젝트 키 (git 제외)      .env.example
.gitignore           (.env, data/, .venv, node_modules, dist, outputs)
README.md            설계 원칙·API 실측표·실행법·데이터/AI 명시
HANDOVER.md          이 문서
docs_install_manual.md  센터 직원용 설치·사용 매뉴얼 (Windows 기준)
start.bat / start.sh    원클릭 실행 (venv → .env 확인 → 데이터 없으면 collect → uvicorn + 브라우저)
requirements.txt     pandas numpy PyYAML fastapi uvicorn pydantic pytest
config/datasets.yaml 허브 API 레지스트리(dataKey·파라미터·응답 컬럼 매핑)
config/items.yaml    품목·품종(확정)·산지 관측소·단위 환산(kg, verify)·제주 점유 등급·판단 규칙·수집 설정
backend/app/
  config.py          .env + yaml 로더
  hub_client.py      urllib 기반 API 클라이언트: 10일 창·반분·재시도·키 마스킹·진행 점 출력
  data_store.py      normalize(원본→표준 컬럼) · 0&0→NaN · CSV upsert · 조회 헬퍼
  tools.py           Tool 6종 (@jsonsafe 로 numpy 타입 제거)
  judge.py           DataState / Condition / Signal / decide()
  intent.py          규칙 추출(품목·의도·상자수, '무' 오탐 방지) + LLM JSON 병합
  templates.py       headline/bullets/각주/LLM 프롬프트
  llm.py             none/openai/ollama 어댑터
  agent.py           AgentRequest/AgentResponse, run()
  main.py            FastAPI: GET /api/health, /api/items, /api/briefing · POST /api/ask · frontend/dist 정적 서빙
backend/tests/       synth.py(합성 데이터) conftest.py test_core.py — **23 테스트 통과**
scripts/check_api.py Go/No-Go 검증 (품종·최신일·시장·관측소) → outputs/checks/*.json
scripts/collect.py   초기 2년/증분 적재, 기상 예산·분할, 합성 캐시 마커 검사
scripts/demo_data.py 키 없이 합성 캐시 생성 (data/cache/SYNTHETIC 마커 생성 → 실데이터 전 삭제)
frontend/            Vite+React18+TS+Recharts 2.12. src/{App,api,types,speech,styles.css}, components/{SignalCard,PriceChart,Panels}
                     빌드 성공 확인(2026-11-15, `✓ built`). dist/ 생성됨
```

### API 응답 핵심 필드 (`POST /api/ask`)
`ok, mode(button|text), item, item_name, cultivar, asof, signal{color,label,score,conditions[{key,label,met,detail,value}],notes[],confidence}, headline, bullets[], extra_sentences[], llm_explanation, tools{price_now,trend_ma{series},yoy_compare{series_this_year,series_last_year},weather_effect,my_volume}, data_state, footnotes[], clarify[], trace[], intent`

### 프론트 UI
품목 타일(좌) → 신호등 램프 카드(색·한 줄 결론·1상자 가격) → 근거 3줄 → (LLM 설명) → "왜 이 색?" 펼침 → 올해 vs 작년 그래프 → 날씨 영향 패널 → 내 물량 계산 → 각주 → "에이전트가 한 일". 상단 토글: 큰 글씨(루트 25px) / 읽어주기(Web Speech TTS, 오프라인) / 인쇄(@media print) / 키오스크(60초 무입력 홈). 말하기(STT)는 Chrome+온라인일 때만 버튼 표시. 되묻기 칩. 디자인: 배경 #f3f6f0, 먹색 #1e2a1c, 신호 #2f8f4e/#e1a42b/#c9412f, 폰트 Pretendard(CDN).

---

## 6. 현재 상태 (2026-11-15 20:00)

| 항목 | 상태 |
|---|---|
| 백엔드·판단 엔진 | ✅ 완료, pytest 23/23, 실데이터(당근) 검증 완료 |
| React 프론트 | ✅ 소스 완료, 맥에서 빌드 성공. **실제 화면 육안 확인은 아직** |
| 허브 키·데이터 담기·API 검증 | ✅ 완료 |
| 데이터 적재 | 🔄 **미완**. 맥 `./start.sh` 가 첫 호출에서 Ctrl+C 로 중단됨(진행 표시 없어 멈춘 줄 오해 → 점 출력 추가함). 브라우저 백그라운드 수집은 당근(604행)·월동무(276행)만 완료 후 세션 종료 가능성 있음 → **맥에서 `./start.sh` 또는 `python3 scripts/collect.py` 재실행이 정답** (거래 ≈660콜 10~15분, 기상은 예산 900/일로 2회) |
| 기획서 | ✅ Claude Docs 초안 완료 https://claude.ai/artifact/T2FLyQnYQNRoCCA1sCEHA8 — 10섹션, 표 위주 약 10~12p. **남은 빈칸: 상자/망 kg 규격 1곳**. 팀 정보는 "개인 참가 — 유소민(기획·프론트·AI 백엔드 전담)"으로 채울 것 (아직 미기입) |
| git | ✅ 로컬 저장소 초기화·첫 커밋. **GitHub 원격 미연결** (레포 생성·push 는 본인 터미널에서) |
| 데모 영상·결과 설명자료·최종 zip | ❌ 미착수 |

---

## 7. 남은 일정 (제출 11/20 10:00)

| 날 | 할 일 | 누가 |
|---|---|---|
| 11/15 (오늘) | GitHub 레포 생성·push, `./start.sh` 로 데이터 적재·화면 확인·캡처 | 소민 |
| 11/16 | 실데이터로 5품목 E2E, UI 폴리시(캡처 기반), 기획서 빈칸·숫자 채우기, 기상 2차 수집 | AI |
| 11/17 | **비개발자 2~3명 사용자 테스트**("당근 지금 팔면 돼?"만 말하고 설명 없이) → 막힌 곳 메모 | 소민 |
| 11/17 | 테스트 피드백 반영, 데모 영상 대본, 결과 설명자료·데이터 활용 명세 작성 | AI |
| 11/18 | 데모 영상 2~3분 촬영(ELO 상호평가에서 결정적), 클린 환경 설치 테스트, **DAKER 1차 제출** | 소민 |
| 11/19 | 미세 수정, **최종 제출** (마감 당일 아침은 건드리지 않기) | 소민 |
| 11/23~27 | **ELO 투표 참여 필수** | 소민 |
| 12/7 | 제주테크노파크 시상식 참석 | 소민 |

### 제출 전 체크리스트
- [ ] 기획서 PDF 15p 이내, 필수 5섹션 포함, 빈칸 0
- [ ] zip: 소스·프롬프트(templates.py)·README·docs_install_manual.md·.env.example·데이터 활용 명세·결과 설명자료·(선택) 데모 영상 링크
- [ ] 사용 AI 모델·활용 범위·외부 API·오픈소스 명시 (README 하단 섹션 있음)
- [ ] **zip 안에 .env(키)·개인정보 없음** (`grep -r "b0j0" .` 로 확인), 허브 데이터목록 xlsx 미포함
- [ ] 새 PC에서 매뉴얼만 보고 설치·실행 재현
- [ ] DAKER 갤러리 제출 후 제출 상태 확인

---

## 8. 사람이 꼭 해야 하는 것 (AI 불가)

1. **GitHub**: 레포 `rokmc1893/jeju-shipping-signal` 생성(Public, README 없이) → `git remote add origin … && git branch -M main && git push -u origin main`
2. **데이터 적재**: `cd ~/Downloads/jeju-shipping-signal && ./start.sh` (AI 작업환경·컨테이너에선 허브·npm·pip 접근이 모두 차단됨)
3. **npm/pip 설치·vite build**: 맥 터미널에서만 가능
4. **허브 로그인·DAKER 참가신청·제출·ELO 투표·시상식 참석**
5. **사용자 테스트** 섭외·관찰
6. **데모 영상 촬영**(대본은 AI 작성)
7. **기획서 PDF 내보내기 후 페이지 수 확인**

---

## 9. 명령어 모음

```bash
# 백엔드 테스트
cd backend && python3 -m pytest -q
# 데이터 적재 (키는 .env)
./start.sh                     # 또는 python3 scripts/collect.py [--item carrot] [--weather-only] [--no-weather]
python3 scripts/check_api.py   # Go/No-Go 재검증
python3 scripts/demo_data.py   # 키 없이 합성 캐시 (실데이터 전 data/cache/SYNTHETIC 삭제)
# 프론트
cd frontend && npm install && npm run build   # dist/ 를 FastAPI 가 / 에서 서빙
cd backend && python3 -m uvicorn app.main:app --port 8000   # http://127.0.0.1:8000
# 개발 중 프론트 핫리로드
cd frontend && npm run dev   # vite proxy → 127.0.0.1:8000
```

---

## 10. 알려진 이슈·주의

- `collect.py` 거래 수집은 품종당 ≈73콜, 실패 재시도 포함 품종당 3~7분. 터미널에 `.`(성공)/`x`(재시도)가 찍힌다. **Ctrl+C 하지 말 것**.
- 기상 API 는 2025-10 이후 0건 → 최신 날씨 기반 메모는 당분간 안 뜸(정상). 기획서 한계에 명시됨.
- `tools.market_compare` 는 코드 유지, 기본 비활성. 켜려면 `rules.market_compare_enabled: true` (표본 한계 각주 필요).
- `items.yaml unit.kg` (당근 20kg 상자, 무 20kg, 양배추 8kg 망, 양파 15kg 망)은 **aT 거래 규격 미확인** → 확인 후 `verify: false` 로 바꾸면 각주의 "환산 기준" 문구가 사라짐.
- 프론트 `npm audit` 경고 2건·500kB 청크 경고는 무시 가능.
- 작년 대비 % 가 +99% 처럼 극단일 때(작년 폭락기) 설명 문구 보강 검토 (선택).
- 합성 데이터와 실데이터를 섞지 말 것 (`data/cache/SYNTHETIC` 마커 있으면 collect.py 가 거부).
- 메모리/프로젝트 문서(claude.ai Project "제주 AI·빅데이터 활용 AI Agent 개발 챌린지" → `claude/jeju-challenge-decisions.md`)에도 결정 요약이 있음.

---

## 11. 바로 다음 액션 (인계받는 쪽이 처음 할 일)

1. `git status` 확인 → GitHub push (사람)
2. `./start.sh` 완료 로그 받기 → `data/cache/daily_stats.csv` 에 5품목 존재·최신일 확인
3. 브라우저 `http://127.0.0.1:8000` 에서 당근·무·양배추 눌러 캡처 → UI 폴리시 목록 작성
4. 기획서 빈칸 2곳(팀 정보·kg 규격) 채우기, 실데이터 수치(당근 +99% YoY 등) 반영
5. 결과 설명자료·데이터 활용 명세 md 작성 → zip 패키징 스크립트
