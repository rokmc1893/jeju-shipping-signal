/** 읽어주기(TTS): 브라우저 내장 음성 — 오프라인 동작.  말로 묻기(STT): Chrome 전용, 인터넷 필요(선택 기능). */
import { Capacitor } from "@capacitor/core";

export function speak(text: string): boolean {
  if (!("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR";
  u.rate = 0.95;
  const ko = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith("ko"));
  if (ko) u.voice = ko;
  window.speechSynthesis.speak(u);
  return true;
}

export function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

type SR = { start: () => void; stop: () => void; lang: string; interimResults: boolean; maxAlternatives: number; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onerror: ((e: unknown) => void) | null; onend: (() => void) | null };

export function sttAvailable(): boolean {
  // 앱의 음성 인식은 별도 권한·네이티브 구현이 필요하므로 웹 브라우저에서만 제공한다.
  if (Capacitor.isNativePlatform()) return false;
  const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition) && navigator.onLine && window.isSecureContext;
}

export function listenOnce(onText: (t: string) => void, onEnd: () => void, onError: (message: string) => void): (() => void) | null {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = "ko-KR";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (e) => onText(e.results[0][0].transcript);
  rec.onerror = (event) => {
    const error = (event as { error?: string }).error;
    if (error !== "aborted" && error !== "no-speech") {
      onError(error === "not-allowed" ? "마이크 사용이 허용되지 않았어요. 작물 버튼이나 글로 물어봐 주세요." : "말하기를 시작하지 못했어요. 작물 버튼이나 글로 물어봐 주세요.");
    }
    onEnd();
  };
  rec.onend = () => onEnd();
  try {
    rec.start();
  } catch {
    onError("이 브라우저에서는 지금 말하기를 사용할 수 없어요. 글로 물어봐 주세요.");
    onEnd();
    return null;
  }
  return () => rec.stop();
}
