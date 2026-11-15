"""LLM 어댑터 — 선택 사항. 표준 라이브러리만 사용(urllib).

- provider=none : 어떤 호출도 하지 않음 (버튼 경로·템플릿 설명만으로 완전 동작)
- provider=openai: OpenAI 호환 Chat Completions (Upstage Solar 등 호환 엔드포인트도 OPENAI_BASE_URL 로 사용 가능)
- provider=ollama: 로컬 Ollama (EXAONE-3.5-7.8B / Qwen2.5-7B Q4 — GTX 1060 6GB 적재 가능)
- 클라우드 실패 시 Ollama 가 떠 있으면 자동 폴백. 둘 다 실패하면 None → 호출부는 템플릿으로 계속.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import config


class LLM:
    def __init__(self):
        self.provider = config.env("LLM_PROVIDER", "none").lower()
        self.openai_key = config.env("OPENAI_API_KEY")
        self.openai_base = config.env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_model = config.env("OPENAI_MODEL", "gpt-4o-mini")
        self.ollama_base = config.env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = config.env("OLLAMA_MODEL", "exaone3.5:7.8b")
        self.last_backend: str | None = None

    @property
    def enabled(self) -> bool:
        return self.provider in ("openai", "ollama")

    # ---- backends ----------------------------------------------------------
    def _post(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _openai(self, prompt: str, max_tokens: int, timeout: float) -> str:
        out = self._post(f"{self.openai_base}/chat/completions",
                         {"model": self.openai_model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": 0.2},
                         {"Authorization": f"Bearer {self.openai_key}"}, timeout)
        return out["choices"][0]["message"]["content"]

    def _ollama(self, prompt: str, max_tokens: int, timeout: float) -> str:
        out = self._post(f"{self.ollama_base}/api/generate",
                         {"model": self.ollama_model, "prompt": prompt, "stream": False, "keep_alive": "30m",
                          "options": {"num_predict": max_tokens, "temperature": 0.2}}, {}, timeout)
        return out.get("response", "")

    def complete(self, prompt: str, max_tokens: int = 300, timeout: float = 25.0) -> str | None:
        if not self.enabled:
            return None
        order = ["openai", "ollama"] if self.provider == "openai" else ["ollama"]
        for backend in order:
            try:
                if backend == "openai" and self.openai_key:
                    txt = self._openai(prompt, max_tokens, timeout)
                elif backend == "ollama":
                    txt = self._ollama(prompt, max_tokens, timeout)
                else:
                    continue
                self.last_backend = backend
                return txt.strip()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError, OSError):
                continue
        self.last_backend = None
        return None

    def complete_json(self, prompt: str) -> dict | None:
        txt = self.complete(prompt, max_tokens=150, timeout=15.0)
        if not txt:
            return None
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
