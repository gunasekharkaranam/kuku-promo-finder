import sys, json, os, time, tempfile, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import promofinder.llm as llm
from promofinder.run import main, mock_responder
from promofinder.parser import load_show

SHOW = os.path.join(os.path.dirname(__file__), "..", "..", "I Married a Broken Soldier. He was a Duke")
responder = mock_responder(load_show(SHOW))
time.sleep = lambda s: None          # no real waiting in the test
os.environ["GEMINI_API_KEY"] = "fake"
log = []
n = itertools.count()

class R:
    def __init__(self, code, body): self.status_code = code; self._b = body; self.text = json.dumps(body)
    def json(self): return self._b

def fake_get(url, **kw):
    names = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-omni-flash-preview", "gemini-3-flash-preview",
             "gemini-3.7-flash", "gemini-3.8-flash-image", "text-embedding-005"]
    return R(200, {"models": [{"name": "models/" + m, "supportedGenerationMethods": ["generateContent"]} for m in names]})

def ok(text):
    return R(200, {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": text}]},
                                   "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 300, "thoughtsTokenCount": 200}})

def fake_post(url, headers=None, json=None, timeout=None):
    model = url.split("/models/")[1].split(":")[0]
    i = next(n); log.append(model)
    if model in ("gemini-3.8-flash", "gemini-flash-latest"):
        return R(429, {"error": {"code": 429, "message": "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: x"}})
    prompt = json["contents"][0]["parts"][0]["text"]
    if i == 2: return R(503, {"error": {"code": 503, "message": "This model is currently experiencing high demand."}})
    if i == 3: raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=600)")
    if i == 4: return ok('{"promos": [{"episode": 1, "segm')            # cut-off JSON
    if i == 6: return R(200, {"candidates": [{"finishReason": "SAFETY"}]})  # empty / blocked reply
    return ok(responder(prompt))

requests.post = fake_post; requests.get = fake_get
llm.requests.post = fake_post; llm.requests.get = fake_get
out = tempfile.mkdtemp()
main(["--input", SHOW, "--provider", "gemini", "--model", "gemini-3.8-flash", "--batch", "10",
      "--out", out, "--cache", tempfile.mkdtemp(), "--min-interval", "0"])
print("calls per model:", {m: log.count(m) for m in dict.fromkeys(log)})
print(open(out + "/quality.md", encoding="utf-8").read()[:400])
print(sorted(os.listdir(out + "/llm_raw")))
