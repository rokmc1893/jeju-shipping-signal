/** 읽어주기(TTS): 브라우저 내장 음성 — 오프라인 동작.  말로 묻기(STT): Chrome 전용, 인터넷 필요(선택 기능). */

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
  const w = window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition) && navigator.onLine;
}

export function listenOnce(onText: (t: string) => void, onEnd: () => void): (() => void) | null {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = "ko-KR";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (e) => onText(e.results[0][0].transcript);
  rec.onerror = () => onEnd();
  rec.onend = () => onEnd();
  rec.start();
  return () => rec.stop();
}
