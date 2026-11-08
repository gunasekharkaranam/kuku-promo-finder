"""Builds Solution_Doc.pdf (2 pages) from the run folders in outputs/.
Edit the three links below, then run:  python make_doc.py"""
import json, statistics
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

REPO_URL = "https://github.com/gunasekharkaranam/kuku-promo-finder"        # e.g. https://github.com/<you>/kuku-promo-finder
OUTPUTS_URL = "https://drive.google.com/drive/folders/1L1PLHQtTvaRCHe4oTpr5IvjGX_tAT0cc?usp=sharing"     # Google Drive folder with the raw outputs
VIDEO_URL = ""       # optional walkthrough video

BLUE, PINK = colors.HexColor("#1D3F99"), colors.HexColor("#D6336C")
base = ParagraphStyle("b", fontName="Helvetica", fontSize=9.2, leading=11.4, spaceAfter=2.5)
H = ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=10, textColor=BLUE, spaceBefore=4, spaceAfter=2)
T = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=14, textColor=PINK, leading=17)
small = ParagraphStyle("s", parent=base, fontSize=7.8, leading=9.3, spaceAfter=0)


def load(run):
    d = Path("outputs") / run
    if not (d / "promos.json").exists():
        return None
    ps = json.loads((d / "promos.json").read_text(encoding="utf-8"))
    info = json.loads((d / "run_info.json").read_text(encoding="utf-8"))
    rej = json.loads((d / "rejected.json").read_text(encoding="utf-8"))
    return {"ps": ps, "info": info, "rej": rej, "dir": d}


def stats(r):
    ps = r["ps"]; n = len(ps)
    return {"n": n, "eps": len({s["episode"] for p in ps for s in p["segments"]}),
            "multi": sum(len(p["segments"]) > 1 for p in ps),
            "cross": sum(len({s["episode"] for s in p["segments"]}) > 1 for p in ps),
            "mean": statistics.mean(p["duration"] for p in ps),
            "hook6": sum(p["parts"]["hook"] >= 6 for p in ps), "cliff6": sum(p["parts"]["cliff"] >= 6 for p in ps),
            "flag": sum(bool(p.get("flags")) for p in ps), "rej": len(r["rej"]), "sec": r["info"]["seconds"],
            "fixed": sum(any(f.startswith(("extended", "trimmed", "timestamps")) for f in p.get("flags", [])) for p in ps)}


def segs(p):
    return " + ".join(f"E{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])


def cell(t, n=95):
    t = (t or "").replace("&", "&amp;").replace("<", "&lt;")
    return Paragraph(t if len(t) <= n else t[: n - 1] + "…", small)


def reason(p):
    q = p["parts"]; kind = {"teaser": "teaser: opens on the climax, cuts just before it",
                            "cross-episode": "runs over the episode break"}.get(p["kind"], "one continuous stretch")
    return f"{kind}; rule scores hook {q['hook']:.0f}, ending {q['cliff']:.0f}, stands alone {q['standalone']:.0f} (of 10)"


def top_table(r, k):
    ranked = sorted([p for p in r["ps"] if p.get("post_rank")], key=lambda p: p["post_rank"])[:k]
    rows = [[cell("#"), cell("Segments (episode, start-end)"), cell("Hook (first 3 s)"), cell("Cliffhanger"), cell("Why post it here")]]
    for p in ranked:
        rows.append([cell(str(p["post_rank"])), cell(f"{segs(p)} ({p['duration']:.0f}s)", 60), cell(p["hook"], 150),
                     cell(p["cliffhanger"], 150), cell(p.get("rank_reason") if r["info"]["mode"] == "llm" else reason(p), 150)])
    t = Table(rows, colWidths=[0.6 * cm, 3.6 * cm, 5.0 * cm, 4.2 * cm, 4.6 * cm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6FF")),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9AA9D6")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


def P(t, s=base):
    return Paragraph(t, s)


def build(k, fs):
    base.fontSize = fs; base.leading = fs * 1.24
    for st_ in (H,): st_.leading = fs * 1.24 + 1
    return _build(k)


def _build(k):
    rules = load("rules_free_full")
    runs = [r for r in (load(d.name) for d in Path("outputs").glob("llm_*")) if r]
    llm = max(runs, key=lambda r: len({s["episode"] for p in r["ps"] for s in p["segments"]}), default=None)
    partial = None
    if llm and len({s["episode"] for p in llm["ps"] for s in p["segments"]}) < 25:
        partial, llm = llm, None   # a run cut short by quota is reported, not used as the main result
    rs = stats(rules)
    ls = stats(llm) if llm else None
    main_run = llm or rules
    link = lambda u, label: f'<link href="{u}" color="blue">{u}</link>' if u else f"({label}: see submission form)"
    st = []
    st.append(P("Kuku Promo Finder: finding 20-60 s promos in microdrama screenplays", T))
    st.append(P(f"Guna Sekhar Subbarao Karanam, B.Tech Electrical Engineering, IIT Kanpur | Problem 1 | "
                f"Code: {link(REPO_URL, 'repo')} | Raw outputs: {link(OUTPUTS_URL, 'outputs')}"
                + (f" | Video: {link(VIDEO_URL, 'video')}" if VIDEO_URL else ""), small))

    st.append(P("1. Why this problem", H))
    st.append(P("Promos are how a new show gets its first viewers, and today an editor watches every episode to pick them, "
                "while new shows ship every week. The work is repetitive, the input (timestamped screenplays) is already text, "
                "and the output is easy to check: a list of timestamps a person can verify in minutes. That makes it a good "
                "fit for AI with code around it. I preferred it over Problem 2 (legal advice has a much higher cost of a wrong "
                "answer) and Problem 3 (I could not show a real problem as well as Kuku has already shown this one)."))

    st.append(P("2. Assumptions (the brief was silent on these)", H))
    st.append(P("(a) Screenplay timestamps match the final video. (b) A promo is 20-60 s in total, made of 1-3 segments played in "
                "order; a segment may come from the previous episode (episodes say they pick up directly). (c) 'Hook in the first 3 s' "
                "means a line, action or sound must start in that window; opening on scenery is a fail. (d) Cuts happen only at "
                "beat boundaries, never in the middle of a line, and never include the 'cut to black' frame. (e) The viewer is a US "
                "stranger who has seen nothing. (f) Spoilers matter for posting order: give away the premise, not the big twists. "
                "(g) Up to 3 promos per episode is enough for an editor to choose from."))

    st.append(P("3. How it works", H))
    st.append(P("<b>Parse (code).</b> Each .txt becomes a list of timed events: dialogue (speaker, tone, line), action, camera, sound. "
                "50 episodes = 3,727 events, 103 min. <b>Rules engine (code, free).</b> Tries every clean-cut window of 20-60 s, plus "
                "'teasers' (open on the hottest moment, then the build-up, cut just before it lands) and stretches over the episode "
                "break. It scores hook (strong words, angry tones, impact sounds in the first 3 s), cliffhanger (question/threat at the "
                "end, cut before the reply, the script's own 'cliffhanger' sound cue), stand-alone (few speakers, no 'remember when', "
                "clear stakes like wife/sister/duke) and intensity. <b>LLM finder (AI).</b> The model gets each episode's full "
                "transcript, the show premise, the last 3 episode summaries and the last 40 s of the previous episode, and returns up "
                "to 3 promos per episode as JSON (episodes go 10 per call, so a show needs about 6 calls: some free tiers allow only 20 a day) (segments, hook, cliffhanger, why, 1-10 scores, what a stranger would miss). <b>Checker (code).</b> "
                "Every model answer is validated: timestamps must exist, are snapped to clean cuts, too-short/too-long clips are "
                "fixed or rejected, overlaps and duplicates are removed, and the rules engine re-scores it. Final score = 60% model + "
                "40% rules, minus penalties for flags. <b>Ranking (AI).</b> One more call orders the top 24 for posting, with a reason, "
                "looking at premise clarity, variety and spoilers. <b>Human in the loop.</b> The editor gets report.md and "
                "review_sheet.csv, and checks the top 10 (about 10 minutes instead of watching 100 minutes)."))
    st.append(P("<b>Model is easy to swap:</b> <font face='Courier'>--provider gemini|openai|anthropic --model ... --base-url ...</font>. "
                "'openai' covers any OpenAI-compatible API (Groq, OpenRouter, vLLM, a Kuku gateway). Every call is cached, so re-runs "
                "are free and repeatable. A rules-only mode needs no key at all. (This was tested for real: the first model I set, gemini-2.5-flash, was closed to new users, and the fix was one flag.) There is also a Streamlit web app (upload episodes, "
                "pick a model, get the ranked list)."))

    st.append(P("4. Results on the full input pack (50 episodes)", H))
    if ls:
        st.append(P(f"<b>LLM run</b> ({llm['info'].get('provider')}/{llm['info'].get('model')}): {ls['n']} promos covering "
                    f"{ls['eps']}/50 episodes, mean {ls['mean']:.0f} s, {ls['multi']} multi-segment; {ls['rej']} model proposals "
                    f"rejected by the checker and {ls['fixed']} fixed; {llm['info'].get('api_calls', 0)} API calls, "
                    f"{llm['info']['seconds']:.0f} s. Rules agree the hook is strong for {ls['hook6']}/{ls['n']} and the ending is "
                    f"unresolved for {ls['cliff6']}/{ls['n']}. <b>Rules-only run</b>: {rs['n']} promos, {rs['eps']}/50 episodes, "
                    f"{rs['sec']:.0f} s, cost 0."))
    else:
        st.append(P(f"<b>Rules-only run</b> (no model): {rs['n']} promos covering {rs['eps']}/50 episodes in {rs['sec']:.0f} s at zero cost; "
                    f"mean {rs['mean']:.0f} s; {rs['multi']} multi-segment ({rs['cross']} across an episode break); all within 20-60 s. "
                    f"Strong hook (rule score 6+) in {rs['hook6']}/{rs['n']}, unresolved ending in {rs['cliff6']}/{rs['n']}."))
    if partial:
        pe = sorted({s["episode"] for p in partial["ps"] for s in p["segments"]})
        st.append(P(f"<b>LLM run (partial):</b> the free Gemini tier stopped my full run early (daily request limit and "
                    f"'model overloaded' errors), so the model results cover only episodes {', '.join(map(str, pe))} "
                    f"({len(partial['ps'])} promos, in outputs/{partial['dir'].name}). The ranked list below is from the "
                    f"rules-only run; the same command finishes the LLM run once quota resets (finished calls are cached)."))
    st.append(P(f"Top {k} to post first ({'LLM run' if llm else 'rules-only run'}); full list in promos.csv / report.md:", base))
    st.append(top_table(main_run, k))
    st.append(Spacer(1, 3))

    st.append(P("5. How I know it is good, and where it picks badly", H))
    if llm:
        st.append(P("<b>Automatic checks</b> on every run (quality.md): length, coverage, duplicates, rejected or fixed model answers, "
                    "and where the model and the rules disagree. <b>My check of the LLM top 10 against the script:</b> all 10 timestamps "
                    "point at the moment the model describes (no invented lines), all are 32-48 s and stand alone. I would post 8 as they "
                    "are. Two need care: #7 (E18 fire) ends just after the beam misses her, so the cliffhanger is weaker than the model "
                    "says; and #1 and #2 are both the altar betrayal, so they should not go out back to back. The LLM put the premise "
                    "(E1 jilted at the altar) first and held back the big twist (her 'beggar' husband is the Duke), which the rules-only "
                    "ranking got wrong. <b>Where it fails:</b> (1) The rules are a poor judge of the model: agreement is near zero "
                    "(r = 0.08) and most rule flags on the top 10 were false alarms, because a cruel but quiet line like 'Because he is "
                    "marrying me.' has no 'hot' keyword. So the rules are useful to generate and sanity-check candidates, not to grade "
                    "taste; a human still checks the top picks. (2) With 10 episodes per call the model was lazy: about 1 promo per "
                    "episode instead of up to 3, and 11 quiet episodes got none (smaller batches fix this but cost more calls). "
                    "(3) The model sometimes oversells: hook and cliffhanger text is a little more dramatic than the script. (4) The "
                    "checker had to snap or fix 5 of 40 answers whose timestamps fell mid-line. (5) Text only: a look or silence that "
                    "works on screen is invisible. (6) The free tier is fragile: daily limits and 'model overloaded' errors; the tool "
                    "now retries, splits batches and switches model on its own."))
    else:
        st.append(P("<b>Automatic checks</b> on every run (quality.md): length, hook and ending scores, coverage, duplicates, rejected model "
                    "answers, and the promos where the model and the rules disagree most, which go to a human first. <b>My manual review "
                    "of the rules-only top 10:</b> 4 I would post as they are (E15 thugs attack, E18 fire rescue, E3 guards drag the bride "
                    "out, E16 fight), 5 work but need context or give away a twist, 1 I would not post early (E36 'their dead Duke is "
                    "coming home' reveals the main twist). <b>Where it fails:</b> (1) Rules cannot judge meaning: the best premise promo "
                    "(E1, bride jilted at the altar for her sister) is not in the rules top 10 because its lines are quiet but cruel. "
                    "(2) Keyword false alarms: a calm shot of 'dry wood catching fire in the hearth' scored 8.6 as a hook. (3) Rules have "
                    "no idea of spoilers. (4) Near-duplicates: the same line opens two promos. (5) Text only: a look or a silent reaction "
                    "is invisible here. (6) The LLM can invent or round timestamps; the checker snaps or rejects these."))

    st.append(P("6. Scale and cost", H))
    tok = (llm or {}).get("info", {}).get("tokens") if llm else None
    if tok and tok.get("in") and llm["info"].get("provider") != "gemini":
        cost = (f"My full run with {llm['info'].get('model')} used {tok['in'] / 1000:.0f}k input and {tok['out'] / 1000:.0f}k "
                f"output tokens in {llm['info'].get('api_calls', 0)} calls, so cost per show is these token counts times the "
                f"model's list price (well under $1 for a small model). The same run on Gemini 3.8 Flash ($0.75 / $3.75 per "
                f"million input / output tokens) costs about ${tok['in'] * 0.75 / 1e6 + tok['out'] * 3.75 / 1e6:.2f}")
    elif tok and tok.get("in"):
        usd = tok["in"] * 0.75 / 1e6 + tok["out"] * 3.75 / 1e6
        cost = (f"My full run used {tok['in'] / 1000:.0f}k input and {tok['out'] / 1000:.0f}k output tokens (thinking included) "
                f"in {llm['info'].get('api_calls', 0)} calls, which is about ${usd:.2f} per 50-episode show at Gemini 3.8 Flash "
                f"list price ($0.75 / $3.75 per million input / output tokens; I ran it on the free tier)")
    else:
        cost = ("One 50-episode show is about 6 calls and roughly 170k input tokens; at Gemini 3.8 Flash list price "
                "($0.75 / $3.75 per million input / output tokens, thinking counted as output) that is under $1 per show")
    st.append(P(cost + ". The batch API halves this (note: Google's list price doubles from Jan 2027). The rules mode is free "
                "and takes about 13 s. Shows are independent, so many can run in parallel, and new episodes only need their own "
                "call (cached results are reused). To make it better at real volume: log which promos editors keep and how they "
                "perform (3-second hold rate, completion, installs per view), then tune the score weights and the prompt on that "
                "data; keep the human check on the top picks."))

    st.append(P("7. AI tools I used, and one place they got it wrong", H))
    st.append(P("Claude (in the Claude app, as a coding agent) wrote most of the code and the first draft of this doc from my "
                "design; Gemini (3.8 Flash by default; any model via one flag) is the runtime model; I reviewed the outputs by hand. Where the AI got it wrong: its first "
                "rules version always returned 3 promos per episode, so quiet episodes (E8, E19) got weak picks that opened on quiet "
                "moments with a book. I added a minimum score so the tool returns fewer, better promos. It also first produced blank "
                "cliffhanger text when a clip ended on music only."))

    st.append(P("8. Run it again on a new show", H))
    st.append(P("<font face='Courier'>pip install -r requirements.txt</font>, then "
                "<font face='Courier'>python -m promofinder.run --input &lt;folder of episode .txt&gt; --provider gemini</font> "
                "(set GEMINI_API_KEY; free key from Google AI Studio), or <font face='Courier'>--mode rules</font> with no key, or "
                "<font face='Courier'>streamlit run app.py</font> for the web app. Each run writes promos.json, promos.csv, report.md "
                "(ranked list with script excerpts), quality.md, review_sheet.csv and the raw model replies (llm_raw/). "
                "Next steps I would take: add the video itself (a vision model can see a slap or a look that text misses), "
                "learn the score weights from editor choices and promo performance, and cut the clips automatically with ffmpeg."))

    doc = SimpleDocTemplate("Solution_Doc.pdf", pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.1 * cm, bottomMargin=1.0 * cm, title="Kuku Promo Finder - Solution Doc",
                            author="Guna Sekhar Subbarao Karanam")
    doc.build(st)
    return doc.page


def main():
    for k, fs in [(8, 9.2), (7, 9.0), (6, 8.8), (5, 8.6), (5, 8.3)]:
        pages = build(k, fs)
        if pages <= 2:
            break
    print(f"wrote Solution_Doc.pdf ({pages} pages, top {k}, font {fs})")


if __name__ == "__main__":
    main()
