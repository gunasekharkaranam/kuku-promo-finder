"""LLM promo finder: the model proposes promos per episode, code checks and fixes them."""
import json, re
from .parser import fmt
from . import candidates as C
from .llm import parse_json, LLMError

SYSTEM = """You are a senior promo editor for vertical microdrama apps like ReelShort and DramaBox.
You cut 20-60 second promos from the show's own footage for TikTok, Instagram Reels and YouTube Shorts.
The viewer is a stranger scrolling fast in the US who has never seen this show.

A great promo:
1. HOOK: something in the FIRST 3 SECONDS that stops the scroll (a slap, a shove, a reveal, a shocking or cruel line, a public humiliation). Never open on scenery, a quiet setup, or the middle of a sentence.
2. CLIFFHANGER: it cuts at an unresolved moment (a threat, a question, a door bursting open, a hand raised, right before the answer or the reveal). Never end on a resolved, calm or happy beat.
3. STANDS ALONE: a stranger understands who is wronged, by whom, and what is at stake, without knowing earlier episodes.
Usually one continuous stretch. You may join up to 3 moments in order (for example: open on the shocking moment, then show the build-up and cut right before it lands).
Use ONLY timestamps that appear in the transcript. Start a segment at the start of a beat and end it at the end of a beat; never cut someone mid-line.
Be strict. Return fewer promos rather than weak ones. Reply with JSON only."""

PROMPT = """SHOW PREMISE (from episode 1): {premise}
STORY SO FAR (recent episode summaries): {recap}

{prev_block}EPISODE {num} SUMMARY: {logline}
EPISODE {num} TRANSCRIPT (timestamps are MM:SS.ss from the start of this episode):
{transcript}

Find up to {k} of the best promos in episode {num}. Segments may use episode {num}{prev_note}.
Total length of all segments must be 20-60 seconds (aim for 25-45).
Return JSON:
{{"promos": [{{
  "title": "3-6 word working title",
  "segments": [{{"episode": {num}, "start": "MM:SS.ss", "end": "MM:SS.ss"}}],
  "hook": "what happens in the first 3 seconds",
  "cliffhanger": "the unresolved moment it cuts on",
  "why": "one line on why it works for a cold viewer",
  "context_gap": "what a new viewer might not understand, or empty",
  "hook_score": 1-10, "cliff_score": 1-10, "standalone_score": 1-10
}}]}}"""


def transcript(ep, a=0.0, b=None):
    out = []
    for e in ep.events:
        if e.end <= a or (b is not None and e.start >= b):
            continue
        t = f"[{fmt(e.start)}-{fmt(e.end)}]"
        if e.kind == "dialogue":
            tone = f" ({e.tone})" if e.tone else ""
            out.append(f'{t} {e.speaker}{tone}: "{e.text}"')
        elif e.kind == "camera":
            txt = e.text if len(e.text) <= 110 else e.text[:107] + "..."
            out.append(f"{t} CAMERA: {txt}")
        else:
            out.append(f"{t} {e.kind.upper()}: {e.text}")
    return "\n".join(out)


def build_prompt(episodes, i, k=3, prev_tail=40.0):
    ep = episodes[i]
    premise = episodes[0].logline
    recap = " | ".join(f"Ep{e.number}: {e.logline}" for e in episodes[max(0, i - 3):i]) or "(this is the first episode)"
    prev_block, prev_note = "", ""
    if i > 0:
        p = episodes[i - 1]
        a = max(0.0, C.content_end(p) - prev_tail)
        prev_block = (f"END OF PREVIOUS EPISODE {p.number} (last {int(prev_tail)}s, only usable as an opening moment):\n"
                      f"{transcript(p, a)}\n\n")
        prev_note = f" and the end of episode {p.number}"
    return PROMPT.format(premise=premise, recap=recap, prev_block=prev_block, num=ep.number,
                         logline=ep.logline, transcript=transcript(ep), k=k, prev_note=prev_note)


def to_sec(x):
    if isinstance(x, (int, float)):
        return float(x)
    m = re.match(r"\s*(\d+):(\d+(?:\.\d+)?)\s*$", str(x))
    if not m:
        raise ValueError(f"bad timestamp {x!r}")
    return int(m.group(1)) * 60 + float(m.group(2))


def _snap(t, points, before=1.5, after=1.5):
    near = [p for p in points if t - before <= p <= t + after]
    return min(near, key=lambda p: abs(p - t)) if near else None


def validate(raw, ep_map, allowed_eps):
    """Turn one model promo into a checked promo, or return (None, reason)."""
    flags = []
    segs = []
    for s in raw.get("segments") or []:
        try:
            n = int(s["episode"]); a = to_sec(s["start"]); b = to_sec(s["end"])
        except (KeyError, ValueError, TypeError) as e:
            return None, f"bad segment {s}: {e}"
        if n not in allowed_eps or n not in ep_map:
            return None, f"episode {n} not allowed"
        ep = ep_map[n]
        if not (0 <= a < b <= ep.duration + 0.5):
            return None, f"timestamps outside episode {n}: {s}"
        starts, ends = C.cut_points(ep)
        a2 = _snap(a, starts); b2 = _snap(b, ends, before=2.0, after=2.0)
        if a2 is None or b2 is None or b2 <= a2:
            return None, f"cannot snap segment to clean cut points: {s}"
        if abs(a2 - a) > 0.6 or abs(b2 - b) > 0.6:
            flags.append("timestamps snapped to clean cuts")
        segs.append(C.seg(n, a2, b2))
    if not segs:
        return None, "no segments"
    if len(segs) > 3:
        return None, "more than 3 segments"
    d = C.duration(segs)
    if d < C.MIN_D:  # extend the last segment to the next clean cut points
        last = segs[-1]; ep = ep_map[last["episode"]]
        _, ends = C.cut_points(ep)
        later = [t for t in ends if t > last["end"] and d + (t - last["end"]) >= C.MIN_D]
        if not later or d + (later[0] - last["end"]) > C.MAX_D:
            return None, f"too short ({d}s) and cannot extend"
        segs[-1] = C.seg(last["episode"], last["start"], later[0]); flags.append(f"extended from {d}s")
    elif d > C.MAX_D:
        last = segs[-1]; ep = ep_map[last["episode"]]
        _, ends = C.cut_points(ep)
        earlier = [t for t in ends if last["start"] + 3 < t < last["end"] and C.duration(segs) - (last["end"] - t) <= C.MAX_D]
        if not earlier:
            return None, f"too long ({d}s) and cannot trim"
        segs[-1] = C.seg(last["episode"], last["start"], earlier[-1]); flags.append(f"trimmed from {d}s")
    p = {"segments": segs, "duration": C.duration(segs)}
    if any(C.overlap({"segments": [x], "duration": x["end"] - x["start"]},
                     {"segments": [y], "duration": y["end"] - y["start"]}) > 0.2
           for i, x in enumerate(segs) for y in segs[i + 1:]):
        return None, "segments overlap each other"
    return p, flags


def llm_scores(raw):
    def g(k):
        try: return max(1.0, min(10.0, float(raw.get(k, 5))))
        except (TypeError, ValueError): return 5.0
    return {"hook": g("hook_score"), "cliff": g("cliff_score"), "standalone": g("standalone_score")}


def final_score(llm, rule, flags):
    l = 0.40 * llm["hook"] + 0.35 * llm["cliff"] + 0.25 * llm["standalone"]
    r = 0.35 * rule["hook"] + 0.30 * rule["cliff"] + 0.20 * rule["standalone"] + 0.15 * rule["intensity"]
    penalty = 0.4 * sum(1 for f in flags if f.startswith(("WEAK", "SOFT", "CONTEXT", "extended", "trimmed")))
    return round(0.6 * l + 0.4 * r - penalty, 2)


def quality_flags(rule):
    f = []
    if rule["hook"] < 4: f.append("WEAK HOOK: rules see little in the first 3s")
    if rule["cliff"] < 4: f.append("SOFT END: rules think the ending may be resolved")
    if rule["standalone"] < 5: f.append("CONTEXT: may need earlier episodes")
    return f


def find_llm_promos(episodes, client, per_episode=3, log=print, raw_dir=None):
    ep_map = {e.number: e for e in episodes}
    found, rejected = [], []
    for i, ep in enumerate(episodes):
        prompt = build_prompt(episodes, i, per_episode)
        try:
            text = client.complete(SYSTEM, prompt)
        except LLMError as e:
            if re.match(r"(400|401|403|404)", str(e)):
                raise SystemExit(f"Model error (check the API key and model name): {str(e)[:500]}")
            log(f"  ep {ep.number}: model error {e}"); rejected.append({"episode": ep.number, "reason": str(e)}); continue
        if raw_dir:
            (raw_dir / f"episode_{ep.number:03d}.txt").write_text(text, encoding="utf-8")
        try:
            data = parse_json(text)
        except Exception as e:
            log(f"  ep {ep.number}: unparseable reply"); rejected.append({"episode": ep.number, "reason": f"bad JSON: {e}"}); continue
        allowed = {ep.number} | ({episodes[i - 1].number} if i > 0 else set())
        n_ok = 0
        for raw in (data.get("promos") or [])[:per_episode]:
            p, flags = validate(raw, ep_map, allowed)
            if p is None:
                rejected.append({"episode": ep.number, "reason": flags, "raw": raw}); continue
            rule = C.rescore(p, ep_map)
            flags = flags + quality_flags(rule)
            llm = llm_scores(raw)
            if any(C.overlap(p, q) > 0.5 for q in found):
                rejected.append({"episode": ep.number, "reason": "duplicate of an earlier promo", "raw": raw}); continue
            p.update(source="llm", title=raw.get("title", ""), hook=raw.get("hook", ""),
                     cliffhanger=raw.get("cliffhanger", ""), why=raw.get("why", ""),
                     context_gap=raw.get("context_gap", ""), llm_scores=llm, parts=rule, flags=flags,
                     kind="multi-segment" if len(p["segments"]) > 1 else "continuous",
                     score=final_score(llm, rule, flags))
            found.append(p); n_ok += 1
        log(f"  ep {ep.number}: {n_ok} promos")
    return found, rejected


RANK_SYSTEM = """You are the head of growth for a microdrama app. You decide which promo clips to post first
on TikTok/Reels/Shorts for a new show, to win the most new viewers. Reply with JSON only."""

RANK_PROMPT = """Show premise: {premise}

Candidate promos (already checked to be 20-60s):
{items}

Pick the {n} promos to post first, in posting order. Think about: scroll-stopping hook, strength of
the cliffhanger, whether a stranger gets the premise, variety (do not post near-copies of the same
beat back to back), and spoilers (do not give away the biggest twists in the first posts).
Return JSON: {{"ranking": [{{"id": "P01", "reason": "one line: why post it at this position"}}]}}"""


def rank_with_llm(promos, episodes, client, n=10, pool=24):
    pool_ps = sorted(promos, key=lambda p: -p["score"])[:pool]
    items = []
    for j, p in enumerate(pool_ps):
        p["_pid"] = f"P{j + 1:02d}"
        segs = " + ".join(f"ep{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])
        items.append(f"{p['_pid']} [{segs}, {p['duration']}s] hook: {p['hook']} | ends: {p['cliffhanger']} | why: {p['why']}")
    text = client.complete(RANK_SYSTEM, RANK_PROMPT.format(premise=episodes[0].logline, items="\n".join(items), n=n))
    data = parse_json(text)
    by = {p["_pid"]: p for p in pool_ps}
    order = []
    for r in data.get("ranking", []):
        p = by.get(str(r.get("id", "")).strip())
        if p and p not in order:
            p["rank_reason"] = r.get("reason", ""); order.append(p)
    return order, text
