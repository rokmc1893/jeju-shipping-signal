# Claude 작업 인계 · 2026-11-16

## 작업 위치와 현재 상태

- 실제 저장소: `/Users/somin/Downloads/jeju-shipping-signal`이다. 현재 Codex 채팅의 기본 폴더 `/Users/somin/Documents/ChatGPT/DAKER_제주`와 다르다.
- GitHub: https://github.com/rokmc1893/jeju-shipping-signal 이다. `main`의 모바일 기능 커밋은 `0868e6b`다.
- 기존 저장소를 삭제하고 소민님 단독 작성자 이력으로 다시 생성했다. 과거 인계 문서의 커밋·PR 링크는 일부 유효하지 않다.
- React·FastAPI·결정론 신호등에 Capacitor 8.6.2 Android/iOS 앱을 추가했다. 현재는 합성 자료 기반 MVP다.
- 기본 실데이터 `data/cache`에는 CSV가 없다. 인계 문서의 당근 실측 수치는 과거 담당자의 기록이며 이번 환경에서 재현한 결과가 아니다.

## 사용자 요구 · 반드시 유지

- 모든 설명·문서·커밋·PR·사용자 문자열은 한국어를 기본으로 한다.
- 실제 작업자는 유소민이며 GitHub 계정은 `rokmc1893`이다. 빌려 쓰는 Claude 계정 소유자 이동섭/Lee-D-S를 작성자·기여자·공동 작성자로 넣지 않는다. Git author/committer는 반드시 소민님 계정으로 연결한다.
- 현재 Git 비공개 이메일은 `202040831+rokmc1893@users.noreply.github.com`이다. 커밋 전에 로컬 설정과 GitHub 연결을 확인한다. 자동 공동 작성자 트레일러를 넣지 않는다. 실제 AI 도구 사용 내역은 README에 유지한다.
- 개발 사진·화면 캡처를 GitHub나 README에 넣지 않는다. 앱 기본 아이콘·스플래시는 빌드 리소스이며 개발 사진과 구분한다.
- `.env`·허브 키·LLM 키·개인 서명 키·Google 계정·브라우저 프로필·에뮬레이터 데이터는 저장소와 배포물에 넣지 않는다.
- 사용자는 갤럭시 크기 Android 에뮬레이터를 직접 보면서 개발하기를 원한다. 브라우저 탭이 아닌 설치형 앱으로 실행한다.
- 사용자 최신 AGENTS 규칙: 코드를 수정한 뒤에는 항상 `code-reviewer` 서브에이전트로 리뷰한다. 제공 환경에서 해당 기능이 없으면 가능 여부를 솔직히 알린다.

## 먼저 읽을 파일

1. `HANDOVER.md` 맨 위의 최신 모바일 작업 기록이다. 아래 원본은 과거 인계 기록이다.
2. `docs/MOBILE.md`는 현재 모바일 실행·개인정보 분리·검증·배포 제한이다.
3. `docs/READINESS.md`는 이전 제출 준비 점검이다. 테스트 34개 등 일부 수치는 과거 기록이며 최신 테스트는 37개다.
4. `docs/CLAUDE_REVIEW_PROMPT.md`는 기존 Claude 기획서·결정 기록을 내보내기 위한 요청이다.

## 실행 환경

- macOS ARM64다. Android SDK는 기본 Library 경로가 아니라 `/opt/homebrew/share/android-commandlinetools`에 있다.
- 전용 AVD는 `Jeju_Galaxy_S24`, Android 16 ARM64, 화면 1080×2340·480dpi다. 실제 삼성 One UI를 재현한 것은 아니다. 기존 `ulsainer-test` AVD는 다른 프로젝트 소유이므로 건드리지 않는다.
- 앱 ID: `io.github.rokmc1893.jejusignal`, 앱 이름: `출하 신호등`이다.
- 다시 실행: 프로젝트 루트에서 `./start_mobile.command`다. Python 가상환경과 npm 의존성은 설치돼 있다.
- `scripts/mobile_dev.py`가 서버 확인·합성 캐시 준비·AVD 부팅·웹 빌드·Capacitor sync·디버그 빌드·설치·앱 실행을 연결한다.
- 백엔드 `127.0.0.1:8000`, Vite `127.0.0.1:5173`을 사용하며 `adb reverse tcp:5173 tcp:5173`으로 앱과 연결한다. Vite HMR로 화면 수정이 자동 반영된다.
- 기존 개발 서버가 살아 있다면 먼저 프로세스와 health를 확인한다. 현재 실행은 `DATA_DIR=outputs/local-demo/cache`, `LLM_PROVIDER=none`인 합성 자료다. 새 실행기는 `outputs/mobile-dev/cache`를 준비한다.
- iOS Xcode 프로젝트는 생성했고 generic simulator 빌드에 성공했다. iOS 실행 런타임이 없어 iPhone 시뮬레이터 앱 실행은 아직 검증하지 않았다.

## 확인한 검증

- pytest 37개 통과, TypeScript 검사·Vite 빌드 성공, npm audit 취약점 0개다.
- 최종 main CI 6개가 통과했다. Windows/Linux Python 3.10/3.12, 웹 빌드·audit, Android 앱 빌드다.
- Android APK 빌드·에뮬레이터 설치·별도 앱 실행, 앱 안 당근 조회·물량 계산·인쇄 안내를 확인했다. 논리 폭 360px에서 가로 넘침이 없었다.
- Chromium/WebKit에서 8개 화면 크기의 큰 글씨·물량 계산·되묻기·가로 넘침·터치 높이를 검사했다. 이전 응답 무시·마이크 오류 안내·API 쿠키 제외도 확인했다.
- Android 앱은 외부 접근 권한으로 INTERNET만 선언한다. AndroidX의 앱 내부 서명 권한은 별도로 존재한다. 계정·연락처·사진·마이크 권한은 추가하지 않았고 자동 백업은 껐다.
- staged 소스와 디버그 APK에서 현재 .env의 비밀값, 쿠키 DB·계정 DB·개인 서명 키가 없는지 검사했다.
- code-reviewer가 지적한 native CORS, Android print no-op, release 설정 검사를 수정하고 재검토했다. 마지막 재검토에서 추가 P0/P1/P2 지적은 없었다.

## 모바일·보안 구현에서 보존할 점

- Google/Chrome 로그인은 서비스에 필요 없다. 사용자가 에뮬레이터 Chrome에 로그인했지만 그 계정·프로필을 앱으로 복사하지 않는다. 앱은 Chrome과 별도 저장 공간을 사용한다.
- `frontend/src/api.ts`는 모든 API fetch에 `credentials: omit`을 적용한다. 공개 API 주소는 `VITE_API_BASE_URL`이며 비밀키를 넣으면 안 된다.
- API URL은 HTTPS 또는 로컬 개발 HTTP만 허용한다. userinfo·query·fragment는 Vite 빌드와 런타임 양쪽에서 거부한다.
- Capacitor의 개발 URL은 `CAPACITOR_DEV_SERVER_URL=http://localhost:5173`로 제한한다. 기본 설정에는 server.url이 없다. 개발 HTTP 허용은 Android debug 설정의 localhost에만 적용한다.
- Android release 게이트는 개발 server.url이 남으면 막고, 실제 웹 번들의 mobile-build.json 안 HTTPS API 주소와 Gradle 환경값의 일치를 검사한다. iOS 자동 배포 게이트·서명은 아직 없다.
- backend CORS는 Vite origins 외에 `https://localhost`·`capacitor://localhost`를 명시 허용한다. wildcard·credentials 허용으로 바꾸지 않는다.
- 앱에서는 미구현 음성 인식을 숨긴다. 인쇄 버튼은 컴퓨터 인쇄 안내를 제공한다. 읽어주기의 네이티브 실기기 검증은 남아 있다.
- 버튼 경로 LLM 호출 0회, 가격·신호는 결정론 규칙, 허브 조회는 수집할 때만 수행하고 사용자 조회는 CSV 캐시를 사용한다.

## 바로 다음 작업 · 이 순서로 진행

1. 수집기 보완 후 5품목의 기본 품종부터 실데이터를 적재한다. 처음부터 모든 품종을 수집하지 않는다. 키는 `.env`를 코드에서 읽되 출력하지 않는다. 허브 네트워크 접근 가능 여부를 실제로 확인한다.
2. `scripts/collect.py`는 일부 HubError를 출력하고 정상 종료하며 품종 전체 수집 뒤에 저장한다. 실패 종료 코드·품목별 상태·중간 저장·재개·하루 누적 쿼터와 실패 재시도 집계를 보완한다. 현 기상 예산은 실행당 제한이다.
3. 스키마·최신일·결측·중복·단위·거래일·산지 범위를 검증하고 원천 응답 일부와 계산을 대조한다. 합성 캐시는 별도 폴더에 유지한다.
4. 당근 실데이터 E2E를 먼저 확인하고 기본 품종 나머지 4개로 확대한다. 초록·노랑·빨강·휴장일·자료 부족·전년 자료 없음·물량 환산을 확인한다.
5. `judge.py`는 마지막 자료가 7일 넘게 지나도 경고만 붙인다. 조건에 따라 초록이 나올 수 있으므로 신선도에 따른 판단 보류 규칙을 정하고 테스트한다. 현재 confidence는 주로 자료 개수이므로 예측 정확도로 설명하지 않는다.
6. 상자·망 무게는 외부 규격 확인 전이다. `unit.verify: false`와 환산 각주를 유지한다. 전국 도매가를 농가 수취가·수익으로 표현하지 않는다. 생산비·운송비·보관 가능 기간을 반영하지 않은 출하 권고 문구를 점검한다.
7. 날씨 비교는 계절성 등을 통제하지 않았고 인과·예측 근거가 아니다. 차트도 거래일 순서로 맞춰 날짜가 정확히 일치하지 않을 수 있으므로 보완한다. LLM 설명의 숫자·예측 표현 사후 검증도 남았다.
8. 원본 기획서·공식 대회 공고·데이터 이용조건을 확보하고 제출 문서를 작성한다. 기획서 원본은 기존 Claude 문서 `https://claude.ai/artifact/T2FLyQnYQNRoCCA1sCEHA8`이다. 이 링크는 실제 기존 자료의 접근 가능 여부를 확인하고 원본 HANDOVER의 링크와 대조한다.
9. iPhone/갤럭시 실기기·센터 Windows PC·오프라인 핵심 조회를 확인한다. 비개발자 사용성 테스트·데모·최종 ZIP을 준비한다.

## 제출과 배포를 구분

인계 문서 기준 대회 마감은 2026-11-20 10:00 KST이며 공식 공고와 다시 대조해야 한다. 대회용 로컬 실행과 앱 스토어 배포는 별도 작업이다. 현재 디버그 APK는 맥 서버에 의존하므로 다른 사용자에게 배포하지 않는다. 실제 앱 배포에는 공개 HTTPS 백엔드·운영 정책·실데이터 갱신·서명·실기기·스토어 검토가 필요하다.

## 명령어

```bash
cd /Users/somin/Downloads/jeju-shipping-signal
git status --short --branch
./start_mobile.command
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=moderate
.venv/bin/python scripts/collect.py --no-weather
```

실행하지 않은 검증을 완료로 쓰지 않는다. 코드 변경 뒤 code-reviewer 리뷰·필요 검증·한국어 커밋을 수행하고, push 시 Git author가 소민님인지 확인한다. 의사결정과 실행 결과는 HANDOVER.md 상단에 이어 기록한다.
