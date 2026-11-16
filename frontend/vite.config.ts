import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const apiBaseUrl = (loadEnv(mode, process.cwd(), "VITE_").VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  if (apiBaseUrl) {
    const url = new URL(apiBaseUrl);
    if (url.username || url.password || url.search || url.hash) {
      throw new Error("공개 API 주소에 계정 정보·키·쿼리 문자열을 넣을 수 없습니다.");
    }
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
      throw new Error("API 서버는 HTTPS 또는 로컬 개발 주소를 사용해야 합니다.");
    }
  }
  return {
    plugins: [react(), {
      name: "mobile-build-metadata",
      generateBundle() {
        // 배포 검사에서 Gradle 환경뿐 아니라 실제 웹 빌드 설정을 확인한다.
        this.emitFile({ type: "asset", fileName: "mobile-build.json", source: JSON.stringify({ apiBaseUrl }) });
      },
    }],
    server: { proxy: { "/api": "http://127.0.0.1:8000" } },
    build: { outDir: "dist" },
  };
});
