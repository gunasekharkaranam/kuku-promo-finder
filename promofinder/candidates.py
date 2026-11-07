"""Rule-based promo finder (no model needed) + shared helpers for promos."""
from .parser import fmt
from . import rules

MIN_D, MAX_D = 20.0, 60.0


def _speech_ranges(ep):
    return [(e.start, e.end) for e in ep.events if e.kind == "dialogue"]


def _clean_cut(t, speech):
    """True if no one is mid-line at time t."""
    return not any(s + 0.15 < t < e - 0.15 for s, e in speech)


def cut_points(ep):
    sp = _speech_ranges(ep)
    starts = sorted({e.start for e in ep.events if e.kind != "camera" or e.start == 0} )
    starts = [t for t in starts if _clean_cut(t, sp)]
    end_evs = [e for e in ep.events if not (e.kind == "camera" and "cut to black" in e.text.lower())]
    ends = sorted({e.end for e in end_evs})
    ends = [t for t in ends if _clean_cut(t, sp)]
    return starts, ends


def content_end(ep):
    """Episode end without the final 'Cut to black.'"""
    evs = [e for e in ep.events if not (e.kind == "camera" and "cut to black" in e.text.lower())]
    return max(e.end for e in evs) if evs else ep.duration


def describe(e):
    if e.kind == "dialogue":
        return f'{e.speaker.title()}: "{e.text}"'
    return e.text


def promo_text(ep_map, segments):
    """First real beat (hook) and last real beat (cliffhanger) of a promo."""
    first = segments[0]; last = segments[-1]
    ev1 = [e for e in rules.events_in(ep_map[first["episode"]].events, first["start"], first["start"] + 3.5)
           if e.kind != "camera"] or rules.events_in(ep_map[first["episode"]].events, first["start"], first["start"] + 3.5)
    tail = rules.events_in(ep_map[last["episode"]].events, last["end"] - 6, last["end"])
    ev2 = [e for e in tail if e.kind in ("dialogue", "action")] or [e for e in tail if e.kind != "camera"] or tail
    hook = describe(ev1[0]) if ev1 else ""
    cliff = describe(ev2[-1]) if ev2 else ""
    return hook, cliff


def seg(ep, a, b):
    return {"episode": ep, "start": round(a, 2), "end": round(b, 2), "start_ts": fmt(a), "end_ts": fmt(b)}


def duration(segments):
    return round(sum(s["end"] - s["start"] for s in segments), 2)


def overlap(p, q):
    o = 0.0
    for s in p["segments"]:
        for t in q["segments"]:
            if s["episode"] == t["episode"]:
                o += max(0.0, min(s["end"], t["end"]) - max(s["start"], t["start"]))
    return o / max(1e-6, min(p["duration"], q["duration"]))


def rescore(promo, ep_map):
    """Rule scores for any promo (single or multi segment)."""
    segs = promo["segments"]
    first, last = segs[0], segs[-1]
    e1, e2 = ep_map[first["episode"]], ep_map[last["episode"]]
    all_evs = []
    for s in segs:
        all_evs += rules.events_in(ep_map[s["episode"]].events, s["start"], s["end"])
    h, hn = rules.hook_score(rules.events_in(e1.events, first["start"], first["end"]), first["start"])
    nxt = [e for e in e2.events if e.start >= last["end"] - 0.05][:4]
    c, cn = rules.cliff_score(rules.events_in(e2.events, last["start"], last["end"]), last["end"], nxt, content_end(e2))
    st, sn = rules.standalone_score(all_evs, min(s["episode"] for s in segs))
    parts = {"hook": round(h, 1), "cliff": round(c, 1), "standalone": round(st, 1),
             "intensity": round(rules.intensity(all_evs), 1), "notes": [n for n in (hn, cn, sn) if n]}
    return parts


def _single_windows(ep):
    starts, ends = cut_points(ep)
    out = []
    for a in starts:
        for b in ends:
            d = b - a
            if d < MIN_D: continue
            if d > MAX_D: break
            parts = rules.score_window(ep, a, b)
            out.append((rules.combine(parts, d), [seg(ep.number, a, b)], parts, "continuous"))
    return out


def _teasers(ep, top_k=4):
    """Open on the hottest moment, then show the build-up and cut right before it happens."""
    hot = sorted((e for e in ep.events if e.kind in ("dialogue", "action", "sfx")),
                 key=lambda e: -rules._line_heat(e))[:top_k]
    starts, ends = cut_points(ep)
    out = []
    for h in hot:
        ha = h.start
        hb = min([t for t in ends if t >= h.end] or [h.end])
        if hb - ha > 7 or hb - ha < 2.0: continue
        for a in starts:
            for b in ends:
                body = b - a
                if b > ha + 0.05 or ha - b > 1.5: continue
                if body < 15 or body + (hb - ha) > MAX_D or body + (hb - ha) < MIN_D: continue
                segs = [seg(ep.number, ha, hb), seg(ep.number, a, b)]
                p = {"segments": segs, "duration": duration(segs)}
                parts = rescore(p, {ep.number: ep})
                parts["cliff"] = round(min(10, parts["cliff"] + 2.5), 1)  # cut just before a moment we already teased
                out.append((round(rules.combine(parts, p["duration"]) - 0.3, 2), segs, parts, "teaser"))
    return out


def _cross(ep, nxt):
    """Stretch that runs over the episode break (scripts say episodes pick up directly)."""
    if nxt is None or not any(k in nxt.continuity.lower() for k in ("directly", "immediately", "continu")):
        return []
    end_a = content_end(ep)
    starts, _ = cut_points(ep)
    _, ends_b = cut_points(nxt)
    out = []
    for a in [t for t in starts if end_a - 40 <= t <= end_a - 8]:
        for b in [t for t in ends_b if 8 <= t <= 45]:
            segs = [seg(ep.number, a, end_a), seg(nxt.number, 0.0, b)]
            d = duration(segs)
            if not (MIN_D <= d <= MAX_D): continue
            p = {"segments": segs, "duration": d}
            parts = rescore(p, {ep.number: ep, nxt.number: nxt})
            out.append((round(rules.combine(parts, d) - 0.2, 2), segs, parts, "cross-episode"))
    return out


def pick(cands, k, existing=()):
    chosen = list(existing)
    res = []
    for sc, segs, parts, kind in sorted(cands, key=lambda x: -x[0]):
        p = {"segments": segs, "duration": duration(segs)}
        if any(overlap(p, q) > 0.35 for q in chosen):
            continue
        p.update(score=sc, parts=parts, kind=kind)
        chosen.append(p); res.append(p)
        if len(res) >= k: break
    return res


def find_rule_promos(episodes, per_episode=3, min_score=5.5):
    ep_map = {e.number: e for e in episodes}
    found = []
    for i, ep in enumerate(episodes):
        nxt = episodes[i + 1] if i + 1 < len(episodes) else None
        cands = _single_windows(ep) + _teasers(ep) + _cross(ep, nxt)
        for p in pick([c for c in cands if c[0] >= min_score], per_episode, existing=found):
            hook, cliff = promo_text(ep_map, p["segments"])
            p.update(source="rules", hook=hook, cliffhanger=cliff,
                     why=f"{p['kind']} clip; rule scores hook {p['parts']['hook']}, cliff {p['parts']['cliff']}, "
                         f"standalone {p['parts']['standalone']}")
            found.append(p)
    return found
