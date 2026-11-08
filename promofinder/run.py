"""Command line entry point.

  python -m promofinder.run --input "path/to/show_folder" --provider gemini
  python -m promofinder.run --input ... --mode rules          # free, no API key
  python -m promofinder.run --input ... --provider openai --model gpt-4o-mini --base-url https://.../v1
"""
import argparse, csv, json, re, statistics, time
from datetime import datetime
from pathlib import Path

from .parser import load_show, fmt
from . import candidates as C
from . import llm_finder as L
from .llm import make_client, parse_json


def seg_str(p):
    return " + ".join(f"Ep{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])


def excerpt(p, ep_map):
    lines = []
    for s in p["segments"]:
        lines.append(f"  -- Ep{s['episode']} {s['start_ts']}-{s['end_ts']} --")
        for e in C.rules.events_in(ep_map[s["episode"]].events, s["start"], s["end"]):
            if e.kind == "dialogue":
                lines.append(f"  [{fmt(e.start)}] {e.speaker}: \"{e.text}\"")
            elif e.kind in ("action", "sfx"):
                lines.append(f"  [{fmt(e.start)}] ({e.kind}) {e.text}")
    return "\n".join(lines)


def rules_ranking(promos, n):
    """Score order, but never two in a row from the same episode, and spread over the show."""
    pool = sorted(promos, key=lambda p: -p["score"])
    order = []
    while pool and len(order) < n:
        last_eps = {s["episode"] for s in order[-1]["segments"]} if order else set()
        nxt = next((p for p in pool if not ({s["episode"] for s in p["segments"]} & last_eps)), pool[0])
        nxt["rank_reason"] = (f"highest remaining score ({nxt['score']}); hook {nxt['parts']['hook']}, "
                              f"cliff {nxt['parts']['cliff']}, standalone {nxt['parts']['standalone']}")
        order.append(nxt); pool.remove(nxt)
    return order


def mock_responder(episodes):
    """Offline test model: replies with rule picks in the LLM JSON format."""
    ep_map = {e.number: e for e in episodes}
    cache = {}

    def respond(prompt):
        if "Candidate promos" in prompt:
            ids = re.findall(r"^(P\d\d) ", prompt, re.M)
            return json.dumps({"ranking": [{"id": i, "reason": "mock ranking"} for i in ids[:10]]})
        nums = [int(x) for x in re.findall(r"===== EPISODE (\d+) =====", prompt)] or \
               [int(re.search(r"Find up to \d+ of the best promos in episode (\d+)", prompt).group(1))]
        if not cache:
            for p in C.find_rule_promos(episodes):
                cache.setdefault(p["segments"][0]["episode"], []).append(p)
        out = []
        for p in [p for n in nums for p in cache.get(n, [])]:
            out.append({"episode": p["segments"][0]["episode"], "title": "mock", "segments": [{"episode": s["episode"], "start": s["start_ts"], "end": s["end_ts"]}
                                                      for s in p["segments"]],
                        "hook": p["hook"], "cliffhanger": p["cliffhanger"], "why": "mock",
                        "hook_score": 7, "cliff_score": 7, "standalone_score": 6})
        return json.dumps({"promos": out})
    return respond


def write_outputs(out, promos, ranked, rejected, episodes, info):
    ep_map = {e.number: e for e in episodes}
    rank_of = {id(p): i + 1 for i, p in enumerate(ranked)}
    allp = sorted(promos, key=lambda p: (rank_of.get(id(p), 999), -p["score"]))
    for j, p in enumerate(allp):
        p["id"] = f"PR{j + 1:03d}"
        p["post_rank"] = rank_of.get(id(p))
        p.pop("_pid", None)
    (out / "promos.json").write_text(json.dumps(allp, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out / "promos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "post_rank", "score", "duration_s", "segments", "kind", "hook", "cliffhanger", "why",
                    "rule_hook", "rule_cliff", "rule_standalone", "llm_hook", "llm_cliff", "llm_standalone", "flags"])
        for p in allp:
            ls = p.get("llm_scores", {})
            w.writerow([p["id"], p["post_rank"] or "", p["score"], p["duration"], seg_str(p), p["kind"], p["hook"],
                        p["cliffhanger"], p["why"], p["parts"]["hook"], p["parts"]["cliff"], p["parts"]["standalone"],
                        ls.get("hook", ""), ls.get("cliff", ""), ls.get("standalone", ""),
                        "; ".join(p.get("flags", []) + p["parts"].get("notes", []))])
    with open(out / "review_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "post_rank", "segments", "hook_stops_scroll(y/n)", "ends_unresolved(y/n)",
                    "makes_sense_alone(y/n)", "would_post(1-5)", "notes"])
        for p in allp:
            w.writerow([p["id"], p["post_rank"] or "", seg_str(p), "", "", "", "", ""])

    md = [f"# Promo report: {info['show']}", "",
          f"Mode: **{info['mode']}** | model: `{info.get('provider', '-')}/{info.get('model', '-')}` | "
          f"episodes: {info['episodes']} | promos found: {len(promos)} | run: {info['started']}", "",
          "## Post these first", ""]
    for i, p in enumerate(ranked):
        md += [f"### {i + 1}. {p.get('title') or p['id']}  ({p['id']}, {p['duration']}s, score {p['score']})",
               f"- **Segments:** {seg_str(p)}", f"- **Hook:** {p['hook']}", f"- **Cliffhanger:** {p['cliffhanger']}",
               f"- **Why it works:** {p['why']}", f"- **Why post at #{i + 1}:** {p.get('rank_reason', '')}"]
        if p.get("context_gap"): md.append(f"- **Context gap:** {p['context_gap']}")
        fl = p.get("flags", []) + p["parts"].get("notes", [])
        if fl: md.append(f"- **Flags:** {'; '.join(fl)}")
        md += ["", "<details><summary>Script excerpt</summary>", "", "```", excerpt(p, ep_map), "```", "</details>", ""]
    md += ["## All promos by episode", "", "| id | rank | segments | sec | score | hook |", "|---|---|---|---|---|---|"]
    for p in sorted(allp, key=lambda p: (p["segments"][0]["episode"], p["segments"][0]["start"])):
        md.append(f"| {p['id']} | {p['post_rank'] or ''} | {seg_str(p)} | {p['duration']} | {p['score']} | "
                  f"{p['hook'][:90].replace('|', '/')} |")
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")

    # ---- automatic quality checks ----
    q = ["# Quality checks (automatic)", ""]
    n = len(promos)
    eps_cov = {s["episode"] for p in promos for s in p["segments"]}
    durs = [p["duration"] for p in promos]
    q += [f"- Promos: {n}; episodes covered: {len(eps_cov)}/{len(episodes)}; missing: "
          f"{sorted(set(e.number for e in episodes) - eps_cov) or 'none'}",
          f"- Duration: all within 20-60s: {all(20 <= d <= 60 for d in durs)}; mean {statistics.mean(durs):.1f}s; "
          f"min {min(durs)}s; max {max(durs)}s" if durs else "- no promos",
          f"- Multi-segment promos: {sum(len(p['segments']) > 1 for p in promos)}; cross-episode: "
          f"{sum(len({s['episode'] for s in p['segments']}) > 1 for p in promos)}",
          f"- Rule hook >= 6 (something strong in first 3s): {sum(p['parts']['hook'] >= 6 for p in promos)}/{n}",
          f"- Rule cliff >= 6 (unresolved ending): {sum(p['parts']['cliff'] >= 6 for p in promos)}/{n}",
          f"- Flagged by checks: {sum(bool(p.get('flags')) for p in promos)}/{n}",
          f"- Model proposals rejected or fixed by code: {len(rejected)} rejected; "
          f"{sum(any(f.startswith(('extended', 'trimmed', 'timestamps')) for f in p.get('flags', [])) for p in promos)} fixed"]
    if promos and promos[0].get("llm_scores"):
        a = [statistics.mean(p["llm_scores"].values()) for p in promos]
        b = [C.rules.combine(p["parts"], p["duration"]) for p in promos]
        try:
            q.append(f"- Agreement model vs rules (Pearson r): {statistics.correlation(a, b):.2f} "
                     "(low = the two judges disagree; look at those by hand)")
        except statistics.StatisticsError:
            pass
        dis = sorted(promos, key=lambda p: -abs(statistics.mean(p["llm_scores"].values()) -
                                                C.rules.combine(p["parts"], p["duration"])))[:8]
        q += ["", "## Biggest model-vs-rules disagreements (review these by hand)", ""]
        for p in dis:
            q.append(f"- {p['id']} {seg_str(p)}: model {statistics.mean(p['llm_scores'].values()):.1f} vs rules "
                     f"{C.rules.combine(p['parts'], p['duration']):.1f} | {p['hook'][:80]}")
    q += ["", "## Flagged promos", ""]
    for p in sorted(promos, key=lambda p: p["score"]):
        if p.get("flags"):
            q.append(f"- {p['id']} {seg_str(p)}: {'; '.join(p['flags'])}")
    q += ["", "## Lowest-scoring picks (likely bad)", ""]
    for p in sorted(promos, key=lambda p: p["score"])[:8]:
        q.append(f"- {p['id']} {seg_str(p)} score {p['score']}: {p['hook'][:80]} -> {p['cliffhanger'][:60]}")
    if rejected:
        q += ["", "## Rejected model proposals", ""]
        for r in rejected:
            q.append(f"- ep {r['episode']}: {r['reason']}")
    (out / "quality.md").write_text("\n".join(q), encoding="utf-8")
    (out / "rejected.json").write_text(json.dumps(rejected, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


def parse_range(s, nums):
    if not s: return nums
    keep = set()
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-"); keep |= set(range(int(a), int(b) + 1))
        else:
            keep.add(int(part))
    return [n for n in nums if n in keep]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find promo clips in microdrama screenplays")
    ap.add_argument("--input", required=True, help="folder with episode .txt screenplays")
    ap.add_argument("--out", default=None, help="output folder (default outputs/<mode>_<time>)")
    ap.add_argument("--mode", choices=["llm", "rules"], default="llm")
    ap.add_argument("--provider", default="gemini", help="gemini | openai | anthropic | mock")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None, help="for OpenAI-compatible APIs")
    ap.add_argument("--episodes", default=None, help="e.g. 1-10 or 1,5,9")
    ap.add_argument("--per-episode", type=int, default=3)
    ap.add_argument("--batch", type=int, default=10, help="episodes per model call (1 = one call per episode)")
    ap.add_argument("--top", type=int, default=10, help="how many to rank for posting")
    ap.add_argument("--min-interval", type=float, default=4.0, help="seconds between API calls (free-tier limits)")
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--min-score", type=float, default=5.5, help="rules mode: drop weaker promos")
    a = ap.parse_args(argv)

    t0 = time.time()
    episodes = load_show(a.input)
    keep = parse_range(a.episodes, [e.number for e in episodes])
    episodes = [e for e in episodes if e.number in keep]
    show = Path(a.input).resolve().name
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(a.out or f"outputs/{a.mode}_{a.provider if a.mode == 'llm' else 'free'}_{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    info = {"show": show, "mode": a.mode, "episodes": len(episodes), "started": stamp}
    print(f"Loaded {len(episodes)} episodes ({sum(e.duration for e in episodes) / 60:.1f} min) from {show}")

    rejected = []
    if a.mode == "rules":
        promos = C.find_rule_promos(episodes, a.per_episode, a.min_score)
        for p in promos: p["flags"] = L.quality_flags(p["parts"])
        ranked = rules_ranking(promos, a.top)
    else:
        kw = {"cache_dir": a.cache, "min_interval": 0 if a.provider == "mock" else a.min_interval}
        if a.provider == "mock": kw["responder"] = mock_responder(episodes)
        if a.base_url: kw["base_url"] = a.base_url
        client = make_client(a.provider, a.model, **kw)
        info.update(provider=client.provider, model=client.model)
        raw = out / "llm_raw"; raw.mkdir(exist_ok=True)
        print(f"Asking {client.provider}/{client.model} for up to {a.per_episode} promos per episode...")
        if getattr(client, "fallbacks", None):
            print(f"  (if {client.model} is out of quota, will try: {', '.join(client.fallbacks[:5])})")
        promos, rejected = L.find_llm_promos(episodes, client, a.per_episode, raw_dir=raw, batch=a.batch)
        if not promos:
            raise SystemExit("No promos found - see the errors above (quota / key / model).")
        try:
            ranked, text = L.rank_with_llm(promos, episodes, client, a.top)
            (raw / "ranking.txt").write_text(text, encoding="utf-8")
            if len(ranked) < min(a.top, len(promos)):
                extra = [p for p in rules_ranking([p for p in promos if p not in ranked], a.top) if p not in ranked]
                ranked += extra[: a.top - len(ranked)]
        except Exception as e:
            print(f"Ranking call failed ({e}); falling back to score order")
            ranked = rules_ranking(promos, a.top)
        info.update(model=client.model, api_calls=client.calls, cache_hits=client.cache_hits, tokens=client.usage,
                    batch=a.batch, episodes_covered=len({s["episode"] for p in promos for s in p["segments"]}))
    info["seconds"] = round(time.time() - t0, 1)
    write_outputs(out, promos, ranked, rejected, episodes, info)
    print(f"Done in {info['seconds']}s: {len(promos)} promos -> {out}")
    return out


if __name__ == "__main__":
    main()
