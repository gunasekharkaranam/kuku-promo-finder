"""Run: python -m pytest tests  (or: python tests/test_basic.py)"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promofinder.parser import parse_episode, load_show
from promofinder import llm_finder as L, candidates as C
from promofinder.llm import parse_json

SAMPLE = '''EPISODE NUMBER: Episode 1
EPISODE LOGLINE: A bride is left at the altar.
CONTINUITY NOTES: First episode.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. CHURCH - DAY
Scene start: 00:00.00
Scene end: 00:40.00

Actions and dialogue:

**ACTION:**
Start: (00:00.00) | End: (00:02.00)
She slaps him hard across the face.

**ANNA (Furious):**
Start: (00:01.00) | End: (00:04.00)
"You liar!"
''' + "".join(f'''
**BEN (Cold):**
Start: (00:{4+3*i:02d}.00) | End: (00:{6+3*i:02d}.50)
"Line number {i}?"
''' for i in range(11)) + '''
**SOUND FX:**
Start: (00:37.00) | End: (00:40.00)
Ominous swell to a cliffhanger peak.

--- SCRIPT END ---
'''


def _ep():
    d = Path(tempfile.mkdtemp()); f = d / "episode-001-x.txt"; f.write_text(SAMPLE, encoding="utf-8")
    return d, parse_episode(f)


def test_parse():
    _, ep = _ep()
    assert ep.number == 1 and ep.duration == 40.0
    assert ep.events[1].speaker == "ANNA" and ep.events[1].tone == "Furious" and ep.events[1].text == "You liar!"


def test_validate_snaps_and_rejects():
    _, ep = _ep(); m = {1: ep}
    p, flags = L.validate({"segments": [{"episode": 1, "start": "00:00.30", "end": "00:39.80"}]}, m, {1})
    assert p and p["segments"][0]["start"] == 0.0 and 20 <= p["duration"] <= 60
    assert L.validate({"segments": [{"episode": 1, "start": "00:00.00", "end": "02:00.00"}]}, m, {1})[0] is None
    assert L.validate({"segments": [{"episode": 2, "start": "00:00.00", "end": "00:30.00"}]}, m, {1})[0] is None
    p, flags = L.validate({"segments": [{"episode": 1, "start": "00:00.00", "end": "00:09.50"}]}, m, {1})
    assert p and p["duration"] >= 20 and any("extended" in f for f in flags)


def test_rules_find_hook():
    d, ep = _ep()
    ps = C.find_rule_promos([ep], 2, min_score=0)
    assert ps and ps[0]["segments"][0]["start"] == 0.0 and ps[0]["parts"]["hook"] >= 6


def test_json_parse():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": [1,2]} hope that helps') == {"a": [1, 2]}


def test_mock_end_to_end():
    from promofinder.run import main
    d, _ = _ep(); out = Path(tempfile.mkdtemp())
    main(["--input", str(d), "--provider", "mock", "--out", str(out), "--cache", str(out / "c")])
    data = json.loads((out / "promos.json").read_text(encoding="utf-8"))
    assert data and (out / "report.md").exists() and (out / "quality.md").exists()


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
