import type { CapacitorConfig } from '@capacitor/cli';

// 개발용 로컬 서버만 허용한다. 배포용 기본 설정에는 외부 URL을 넣지 않는다.
const devUrl = process.env.CAPACITOR_DEV_SERVER_URL;
if (devUrl && !['http://localhost:5173', 'http://127.0.0.1:5173'].includes(devUrl)) {
  throw new Error('모바일 개발 서버는 이 맥의 localhost:5173만 사용할 수 있습니다.');
}

const config: CapacitorConfig = {
  appId: 'io.github.rokmc1893.jejusignal',
  appName: '출하 신호등',
  webDir: 'dist',
  plugins: { SystemBars: { insetsHandling: 'native', initialViewportFitValueHint: 'cover' } },
  ...(devUrl ? { server: { url: devUrl, cleartext: true } } : {}),
};

export default config;
