"""
Tiered LLM routing:
  Tier 1 — Local Ollama (fast, private, free)
  Tier 2 — Claude API (complex reasoning)
  Tier 3 — OpenAI API (fallback)
"""
import httpx
from typing import Optional
from server.config import OLLAMA_BASE_URL, OLLAMA_MODEL, ANTHROPIC_API_KEY, OPENAI_API_KEY


_OLLAMA_CACHE_TTL = 30.0   # seconds between health checks

class LLMRouter:
    def __init__(self):
        self._ollama_ok: Optional[bool] = None
        self._ollama_checked_at: float = 0.0
        # Lazy singleton clients — created once, reused
        self._anthropic_client = None
        self._openai_client = None

    async def _check_ollama(self) -> bool:
        import time as _t
        now = _t.time()
        if self._ollama_ok is not None and (now - self._ollama_checked_at) < _OLLAMA_CACHE_TTL:
            return self._ollama_ok
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                self._ollama_ok = r.status_code == 200
        except Exception:
            self._ollama_ok = False
        self._ollama_checked_at = now
        return self._ollama_ok

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
        force_tier: Optional[int] = None,
    ) -> dict:
        tier = force_tier

        if tier is None:
            if await self._check_ollama():
                tier = 1
            elif ANTHROPIC_API_KEY:
                tier = 2
            elif OPENAI_API_KEY:
                tier = 3
            else:
                raise RuntimeError("No LLM available — install Ollama or set API keys in .env")

        if tier == 1:
            return await self._ollama(prompt, system, max_tokens)
        elif tier == 2:
            return await self._claude(prompt, system, max_tokens)
        else:
            return await self._openai(prompt, system, max_tokens)

    async def _ollama(self, prompt: str, system: str, max_tokens: int) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
                          "options": {"num_predict": max_tokens}},
                )
                r.raise_for_status()
                data = r.json()
                text = data.get("message", {}).get("content")
                if not text:
                    raise RuntimeError(f"Unexpected Ollama response shape: {str(data)[:200]}")
                return {"text": text, "tier": 1, "model": OLLAMA_MODEL}
        except Exception:
            self._ollama_ok = False   # invalidate cache so next request retries
            self._ollama_checked_at = 0.0
            raise

    async def _claude(self, prompt: str, system: str, max_tokens: int) -> dict:
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        kwargs = {"model": "claude-sonnet-4-6", "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = await self._anthropic_client.messages.create(**kwargs)
        return {"text": msg.content[0].text, "tier": 2, "model": "claude-sonnet-4-6"}

    async def _openai(self, prompt: str, system: str, max_tokens: int) -> dict:
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await self._openai_client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, max_tokens=max_tokens
        )
        return {"text": resp.choices[0].message.content, "tier": 3, "model": "gpt-4o-mini"}


llm = LLMRouter()
