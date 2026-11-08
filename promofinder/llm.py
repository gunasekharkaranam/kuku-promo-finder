"""One tiny interface over many model providers, so the model is easy to swap.

    client = make_client("gemini", "gemini-3.8-flash")
    text = client.complete(system, prompt)   # returns the model's raw text (JSON asked)

Providers: gemini | openai (any OpenAI-compatible API: OpenAI, Groq, OpenRouter,
Together, vLLM, Ollama, or an internal gateway via --base-url) | anthropic | mock.
Every call is cached on disk, so re-runs are free and outputs are reproducible.
"""
import hashlib, json, os, re, time
from pathlib import Path
import requests

DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "openai": "gpt-4o-mini",
                  "anthropic": "claude-haiku-5-5", "mock": "mock"}


class LLMError(RuntimeError):
    pass


def is_hard_stop(msg):
    """Errors that retrying will not fix: bad key/model, or the daily free quota is used up."""
    return bool(re.match(r"(400|401|403|404)", msg)) or (msg.startswith("429") and
            re.search(r"PerDay|per day|free_tier_requests|limit: \d+, mode", msg) is not None)


class BaseClient:
    provider = "base"

    def __init__(self, model, cache_dir=".cache", temperature=0.3, min_interval=0.0):
        self.model = model
        self.temperature = temperature
        self.cache = Path(cache_dir); self.cache.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last = 0.0
        self.calls = 0; self.cache_hits = 0; self.usage = {"in": 0, "out": 0}

    def _key(self, system, prompt):
        h = hashlib.sha256(f"{self.provider}|{self.model}|{self.temperature}|{system}|{prompt}".encode()).hexdigest()
        return self.cache / f"{h[:24]}.json"

    fallbacks = []   # other models to try when this one is unavailable, busy or out of quota

    def complete(self, system, prompt, retries=4, check=None):
        """Return the model's text. `check(text)` may raise to reject a broken reply (it is then retried).
        Transient errors are retried; if a model keeps failing or has no quota, the next model is tried."""
        if not hasattr(self, "tried"): self.tried = {self.model}
        while True:
            try:
                return self._complete_one(system, prompt, retries, check)
            except LLMError as e:
                nxt = next((m for m in self.fallbacks if m not in self.tried), None)
                if nxt is None:
                    raise
                why = "no quota / no access" if is_hard_stop(str(e)) else "keeps failing"
                print(f"  {self.model}: {why} -> switching to {nxt}")
                self.tried.add(nxt); self.model = nxt

    def _complete_one(self, system, prompt, retries, check):
        f = self._key(system, prompt)
        if f.exists():
            text = json.loads(f.read_text(encoding="utf-8"))["text"]
            try:
                if check: check(text)
                self.cache_hits += 1
                return text
            except Exception:
                pass  # cached reply is broken: ask again
        delay = 10.0
        for attempt in range(retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0: time.sleep(wait)
            self._last = time.time()
            try:
                text, usage = self._call(system, prompt)
                self.calls += 1
                self.usage["in"] += usage.get("in", 0); self.usage["out"] += usage.get("out", 0)
                if check:
                    try:
                        check(text)
                    except Exception as e:
                        raise LLMError(f"bad reply (not valid JSON): {e}")
                f.write_text(json.dumps({"provider": self.provider, "model": self.model, "text": text,
                                         "usage": usage}, ensure_ascii=False), encoding="utf-8")
                return text
            except LLMError as e:
                msg = str(e)
                if is_hard_stop(msg) or attempt == retries - 1:
                    raise
                print(f"    {self.model} busy or gave a bad reply, waiting {delay:.0f}s and trying again "
                      f"({attempt + 1}/{retries - 1})")
                time.sleep(delay); delay = min(delay * 2, 60)
        raise LLMError("unreachable")

    def _post(self, url, headers, body):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=600)
        except requests.RequestException as e:
            raise LLMError(f"timeout/network: {e}")
        if r.status_code != 200:
            raise LLMError(f"{r.status_code}: {r.text[:400]}")
        return r.json()


class GeminiClient(BaseClient):
    provider = "gemini"

    def __init__(self, model, api_key=None, **kw):
        super().__init__(model, **kw)
        self.key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.key: raise LLMError("Set GEMINI_API_KEY (free key: https://aistudio.google.com/apikey)")
        self.fallbacks = self.list_flash_models()

    def list_flash_models(self):
        """Ask Google which text 'flash' models this key can use (each model has its own free quota)."""
        try:
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             headers={"x-goog-api-key": self.key}, params={"pageSize": 200}, timeout=30)
            names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception:
            return []
        bad = ("image", "tts", "audio", "live", "omni", "embedding", "exp", "robotics", "computer", "native")
        flash = [n for n in names if "flash" in n and not any(b in n for b in bad) and n != self.model]
        # newest first, full flash before lite
        return sorted(flash, key=lambda n: ("lite" in n, [-int(x) for x in re.findall(r"\d+", n)[:2]]))

    def _call(self, system, prompt):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json",
                                     "maxOutputTokens": 32768}}
        j = self._post(url, {"x-goog-api-key": self.key, "Content-Type": "application/json"}, body)
        try:
            parts = j["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"bad response: {str(j)[:300]}")
        if not text.strip():
            raise LLMError(f"bad response: empty ({j.get('candidates', [{}])[0].get('finishReason', '?')})")
        u = j.get("usageMetadata", {})
        return text, {"in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}


class OpenAIClient(BaseClient):
    provider = "openai"

    def __init__(self, model, api_key=None, base_url=None, **kw):
        super().__init__(model, **kw)
        self.key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    def _call(self, system, prompt):
        body = {"model": self.model, "temperature": self.temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        j = self._post(f"{self.base}/chat/completions",
                       {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}, body)
        u = j.get("usage", {})
        return j["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}


class AnthropicClient(BaseClient):
    provider = "anthropic"

    def __init__(self, model, api_key=None, **kw):
        super().__init__(model, **kw)
        self.key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.key: raise LLMError("Set ANTHROPIC_API_KEY")

    def _call(self, system, prompt):
        body = {"model": self.model, "max_tokens": 16000, "temperature": self.temperature, "system": system,
                "messages": [{"role": "user", "content": prompt + "\n\nReply with JSON only."}]}
        j = self._post("https://api.anthropic.com/v1/messages",
                       {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
        u = j.get("usage", {})
        return "".join(b.get("text", "") for b in j["content"]), {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)}


class MockClient(BaseClient):
    """Offline stand-in used for tests: answers with the rule-based picks in the LLM's JSON format."""
    provider = "mock"

    def __init__(self, model="mock", responder=None, **kw):
        super().__init__(model, **kw)
        self.responder = responder

    def _call(self, system, prompt):
        return self.responder(prompt), {}


def make_client(provider, model=None, **kw):
    provider = provider.lower()
    model = model or DEFAULT_MODELS.get(provider)
    cls = {"gemini": GeminiClient, "openai": OpenAIClient, "anthropic": AnthropicClient, "mock": MockClient}.get(provider)
    if cls is None: raise LLMError(f"unknown provider {provider}")
    if provider != "openai": kw.pop("base_url", None)
    return cls(model, **kw)


def parse_json(text):
    """Pull the JSON object out of a model reply (handles ``` fences and chatter)."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise
