# 모바일 앱 개발 환경

Android에서는 Capacitor 앱을 설치해 주소창 없이 실행한다. 화면은 기존 React 코드를 공유하며 Android WebView와 iOS WKWebView를 사용한다. 현재 사용자 배포용 완성본은 아니다.

## 지금 실행하는 환경

- 전용 AVD 이름은 `Jeju_Galaxy_S24`다. Android 16 ARM64 이미지를 사용한다.
- 화면은 1080×2340, 밀도 480dpi로 설정했다. 논리 화면 폭은 360px다.
- 갤럭시 S24와 비슷한 화면 크기이며 삼성 One UI나 Samsung Internet 자체를 재현한 환경은 아니다.
- 앱 ID는 `io.github.rokmc1893.jejusignal`, 표시 이름은 `출하 신호등`이다.
- 개발 화면은 Vite `127.0.0.1:5173`, 백엔드는 `127.0.0.1:8000`에서 실행한다.
- `adb reverse`로 앱의 `localhost:5173`을 맥의 Vite에 연결한다. 외부 네트워크에는 개발 서버를 공개하지 않는다.
- 시연 자료는 `outputs/` 아래 합성 캐시로 분리한다. 기본 실데이터 캐시는 아직 준비하지 않았다.

## 다시 실행

맥에서 프로젝트 루트의 `start_mobile.command`를 더블클릭하거나 아래 명령을 실행한다.

```bash
./start_mobile.command
```

실행기는 기존 개발 서버를 확인하고 필요한 서버를 시작한다. 전용 가상 기기를 부팅한 뒤 웹 빌드·Capacitor sync·Android 디버그 빌드·설치·앱 실행을 수행한다. 화면 소스 변경은 Vite가 자동 반영한다. 종료는 터미널에서 Ctrl+C다. 사용자가 보고 있는 에뮬레이터는 닫지 않는다.

먼저 Python 가상환경·`requirements.txt`, `frontend`의 `npm ci`, Java 21 이상, Android SDK 도구가 필요하다. `adb`, `emulator`가 PATH에 있어야 한다. 다른 맥에서는 Android SDK에 Android 36 Google APIs ARM64 이미지와 위 이름·화면 크기의 AVD를 만든다. SDK 라이선스는 설치자가 직접 확인한다.

Android SDK가 Homebrew 경로에 있는 현재 맥에서는 별도 Android Studio 설치 없이 빌드했다. 다른 프로젝트의 가상 기기는 수정하지 않았다.

## 계정과 개인정보

이 앱은 Google·Chrome 계정 로그인을 사용하지 않는다. 에뮬레이터의 Chrome에 로그인해도 앱을 위해 필요한 단계가 아니다. 앱 패키지에는 Chrome 프로필·쿠키·에뮬레이터 사용자 데이터·Google 계정 정보를 복사하지 않는다.

Android 앱은 Chrome과 별도 저장 공간을 사용한다. 현재 앱에 선언한 Android 접근 권한은 인터넷 연결뿐이다. 계정·연락처·사진·마이크 접근 권한을 추가하지 않았으며 Android 자동 백업은 비활성화했다. API 요청에는 `credentials: omit`을 적용한다.

프로젝트 키와 선택 LLM 키는 맥의 백엔드 `.env`에서만 읽는다. 프론트와 앱에 넣지 않는다. `VITE_` 환경변수는 공개 번들에 포함되므로 비밀키를 넣으면 안 된다. `VITE_API_BASE_URL`에는 공개 API 주소만 사용한다. 주소에 사용자명·비밀번호·쿼리·fragment가 있으면 빌드를 거부한다.

Git은 `.env`, 개인 서명 키, 계정 설정, `local.properties`, APK·빌드 결과·에뮬레이터 데이터를 제외한다. 개발 캡처도 `outputs/`에만 보관하고 저장소에 올리지 않는다. 기본 앱 아이콘 리소스는 앱 빌드에 필요한 파일이다.

## 최신 검증 · 2026-11-19

iPhone 17 시뮬레이터(iOS 27.2)에서 디버그 앱을 설치·실행하고 당근 가격·거래일·관망 표시까지 확인했다. 결과로 이동할 때 상단 상태바를 피해 스크롤하도록 고쳤고 갤럭시 크기 Android 에뮬레이터의 5품종 조회도 다시 확인했다. [실행 검증](INSTALLATION_TEST.md)

## 검증 결과 · 2026-11-16

| 범위 | 결과 |
| --- | --- |
| 백엔드 | pytest 37개가 통과했다. native CORS 허용과 외부 origin 거부를 포함한다. |
| 웹 | TypeScript 검사·프로덕션 빌드가 성공했고 npm audit 취약점은 0개다. |
| Chromium·WebKit | 320·360·375·393·412·768·1440px와 780×360 가로 화면에서 큰 글씨·가로 넘침·터치 높이·물량 계산·되묻기를 검사했다. |
| 예외 동작 | 두 엔진에서 늦은 이전 응답 무시와 마이크 시작 실패 안내를 확인했다. |
| 쿠키 | 테스트용 쿠키를 넣어도 API 요청에 Cookie 헤더가 전송되지 않는 것을 두 엔진에서 확인했다. |
| Android | 디버그 APK 빌드·실제 에뮬레이터 설치·별도 앱 실행이 성공했다. |
| iOS | Xcode에서 `generic/platform=iOS Simulator`, 서명 없이 빌드에 성공했다. iOS 실행 런타임이 없어 iPhone 시뮬레이터 앱 실행은 아직 확인하지 않았다. |

브라우저 크기 에뮬레이션은 실제 iPhone·갤럭시에서의 검증을 대신하지 않는다. 현재 공식 스토어 배포와 외부 사용자 테스트는 하지 않았다.

## 기능 차이

화면 조회·자유 질문·계산은 공통 UI를 사용한다. 음성 인식은 현재 웹 브라우저에서만 선택적으로 제공하며 앱에서는 버튼을 숨긴다. 네이티브 음성 인식은 권한과 별도 구현이 필요하다. 앱의 인쇄 버튼은 컴퓨터에서 인쇄하도록 안내한다. 읽어주기는 기기·WebView의 음성 지원에 따라 달라지며 네이티브 실기기 검증이 남아 있다.

## 실제 사용자에게 배포하기 전

디버그 APK는 맥의 개발 서버에 연결하므로 다른 사람에게 배포하지 않는다. 공개 HTTPS 백엔드, 데이터 갱신·이용조건 확인, 실제 폰 테스트, 배포 서명·스토어 검토가 필요하다. 현재 백엔드에는 사용자 계정·사용자별 저장 기능이 없다.

웹을 배포용 API 주소로 빌드하고 개발 URL 없이 sync해야 한다.

```bash
cd frontend
VITE_API_BASE_URL=https://실제-API-도메인 npm run build
npx cap sync android
npx cap sync ios
```

Android release 작업은 개발 서버 URL이 남아 있으면 중단한다. 웹 빌드의 `mobile-build.json`에 있는 HTTPS API 주소와 Gradle 프로세스의 `VITE_API_BASE_URL`이 일치하는지도 확인한다. 이 검사는 실제 서버의 동작·보안·데이터를 검증하는 배포 승인 절차가 아니다. iOS 배포용 서명과 자동 배포 검사는 아직 구성하지 않았다.

참고: [Capacitor Android](https://capacitorjs.com/docs/android), [개발용 Live Reload](https://capacitorjs.com/docs/guides/live-reload), [Playwright 기기 에뮬레이션](https://playwright.dev/docs/emulation).
