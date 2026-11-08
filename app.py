"""Kuku Promo Finder - web app.   Run locally:  streamlit run app.py"""
import html, io, json, os, tempfile, zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
from promofinder.run import main as run_main
from promofinder.llm import DEFAULT_MODELS

REPO = "https://github.com/gunasekharkaranam/kuku-promo-finder"
st.set_page_config(page_title="Kuku Promo Finder", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# ---------- look and feel: olive, beige and brass (same as the PDF) ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Inter:wght@400;500;600&display=swap');
:root { --olive:#556B2F; --deep:#3B4A1F; --brass:#A88B3D; --beige:#F5EFDC; --sand:#F3EDDC; --paper:#FDFBF5; --ink:#3A3226; }
html, body, [class*="css"], .stMarkdown, p, li, label, .stTextInput, .stSelectbox { font-family:'Inter', sans-serif; color:var(--ink); }
#MainMenu, footer, header [data-testid="stToolbar"] { visibility:hidden; }
.block-container { padding-top:1.2rem; max-width:1180px; }
h1,h2,h3 { font-family:'Cormorant Garamond', serif !important; color:var(--deep) !important; letter-spacing:.2px; }

.hero { background:linear-gradient(135deg,#3B4A1F 0%,#556B2F 60%,#6B7F3A 100%); border-radius:18px; padding:38px 44px 30px;
        color:var(--beige); position:relative; overflow:hidden; box-shadow:0 10px 30px rgba(59,74,31,.25); }
.hero:after { content:""; position:absolute; inset:10px; border:1px solid rgba(232,215,160,.45); border-radius:12px; pointer-events:none; }
.hero h1 { font-family:'Cormorant Garamond', serif !important; color:#FBF6E6 !important; font-size:3rem; margin:0 0 6px; line-height:1.05; }
.hero p { color:#EDE4C6; font-size:1.08rem; margin:0 0 16px; max-width:760px; }
.pill { display:inline-block; background:rgba(251,246,230,.14); border:1px solid rgba(232,215,160,.55); color:#FBF6E6;
        padding:4px 12px; border-radius:999px; font-size:.82rem; margin:0 6px 6px 0; }
.ornament { text-align:center; color:var(--brass); letter-spacing:10px; margin:18px 0 6px; font-size:.9rem; }

.step { background:#FFFDF8; border:1px solid #E6DCBF; border-top:4px solid var(--olive); border-radius:14px; padding:18px 20px; height:100%; }
.step .n { display:inline-flex; width:30px; height:30px; border-radius:50%; background:var(--olive); color:#FBF6E6;
           align-items:center; justify-content:center; font-weight:600; margin-bottom:8px; }
.step b { font-family:'Cormorant Garamond', serif; font-size:1.25rem; color:var(--deep); display:block; }
.step span { font-size:.92rem; color:#5B5240; }

.panel { background:#FFFDF8; border:1px solid #E6DCBF; border-radius:16px; padding:6px 22px 18px; }
.stButton>button, .stDownloadButton>button { background:var(--olive); color:#FBF6E6; border:0; border-radius:10px;
        padding:.6rem 1.4rem; font-weight:600; }
.stButton>button:hover, .stDownloadButton>button:hover { background:var(--deep); color:#fff; }
[data-testid="stFileUploaderDropzone"] { background:#FBF7EA; border:1.5px dashed var(--brass); border-radius:12px; }

.metric { background:#FFFDF8; border:1px solid #E6DCBF; border-radius:14px; padding:14px 18px; text-align:center; }
.metric .v { font-family:'Cormorant Garamond', serif; font-size:2rem; color:var(--deep); font-weight:700; line-height:1.1; }
.metric .l { font-size:.82rem; color:#7A6E55; text-transform:uppercase; letter-spacing:.8px; }

.promo { background:#FFFDF8; border:1px solid #E6DCBF; border-left:6px solid var(--olive); border-radius:14px;
         padding:18px 22px; margin:14px 0; box-shadow:0 3px 12px rgba(59,74,31,.06); }
.promo .top { display:flex; align-items:center; gap:14px; margin-bottom:8px; }
.rank { flex:none; width:42px; height:42px; border-radius:50%; background:var(--olive); color:#FBF6E6; display:flex;
        align-items:center; justify-content:center; font-family:'Cormorant Garamond', serif; font-size:1.35rem; font-weight:700;
        box-shadow:0 0 0 3px #FFFDF8, 0 0 0 4px var(--brass); }
.promo .title { font-family:'Cormorant Garamond', serif; font-size:1.45rem; color:var(--deep); font-weight:700; }
.promo .meta { font-size:.85rem; color:#7A6E55; }
.chip { display:inline-block; background:#F3EDDC; border:1px solid var(--brass); color:var(--deep); border-radius:8px;
        padding:3px 10px; margin:4px 6px 4px 0; font-family:ui-monospace, Menlo, monospace; font-size:.85rem; }
.row { display:grid; grid-template-columns:130px 1fr; gap:4px 14px; margin-top:8px; font-size:.95rem; }
.row .k { color:var(--olive); font-weight:600; }
.note { margin-top:10px; background:#FBF3DD; border:1px solid #E2CC8F; color:#6B5520; border-radius:8px; padding:6px 10px; font-size:.85rem; }
.foot { text-align:center; color:#7A6E55; font-size:.85rem; margin:36px 0 10px; }
.foot a { color:var(--olive); }
.stTabs [data-baseweb="tab"] { font-weight:600; }
.stTabs [aria-selected="true"] { color:var(--olive) !important; }
</style>
""", unsafe_allow_html=True)

esc = lambda x: html.escape(str(x or ""))

# ---------- hero ----------
st.markdown("""
<div class="hero">
  <h1>Kuku Promo Finder</h1>
  <p>Upload the scripts of a short drama series. In a few minutes you get the best 20 to 60 second promo clips,
     with exact start and end times, ranked in the order you should post them.</p>
  <span class="pill">Hook in the first 3 seconds</span><span class="pill">Ends on a cliffhanger</span>
  <span class="pill">Makes sense to new viewers</span><span class="pill">Works with Gemini, Claude or OpenAI</span>
  <span class="pill">Free mode needs no key</span>
</div>
<div class="ornament">◆ ◆ ◆</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
for col, n, t, d in ((c1, 1, "Upload scripts", "Add the episode .txt files, or one .zip with all of them."),
                     (c2, 2, "Choose how to search", "Free rules engine, or an AI model if you have an API key."),
                     (c3, 3, "Get ranked promos", "See which clips to post first, why they work, and where to cut.")):
    col.markdown(f'<div class="step"><div class="n">{n}</div><b>{t}</b><span>{d}</span></div>', unsafe_allow_html=True)

st.write("")
left, right = st.columns([1.35, 1], gap="large")
with left:
    st.markdown("### Your episodes")
    files = st.file_uploader("Episode scripts (.txt files or one .zip)", type=["txt", "zip"], accept_multiple_files=True)
    st.caption("Your files are used only for this run and are not saved.")
with right:
    st.markdown("### Settings")
    choice = st.selectbox("How should it find promos?", ["Free: rules only (no key needed)", "Google Gemini (AI)",
                                                         "Anthropic Claude (AI)", "OpenAI or compatible (AI)"])
    provider = {"Free: rules only (no key needed)": None, "Google Gemini (AI)": "gemini",
                "Anthropic Claude (AI)": "anthropic", "OpenAI or compatible (AI)": "openai"}[choice]
    model = key = base = None
    if provider:
        key = st.text_input("API key", type="password", help="Used only for this run. It is never saved.")
        model = st.text_input("Model name", DEFAULT_MODELS[provider])
        if provider == "openai":
            base = st.text_input("API address (base URL)", "https://api.openai.com/v1")
    with st.expander("More options"):
        per_ep = st.slider("Most promos per episode", 1, 5, 3)
        top = st.slider("How many to rank for posting", 5, 20, 10)
        eps = st.text_input("Only these episodes (leave empty for all, e.g. 1-10)", "")

st.write("")
go = st.button("Find promos", type="primary", disabled=not files, use_container_width=True)
if not files:
    st.caption("Upload at least one script to start.")

if go:
    work = Path(tempfile.mkdtemp()); show = work / "show"; show.mkdir()
    for f in files:
        if f.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(f.read())) as z:
                for n in z.namelist():
                    if n.lower().endswith(".txt") and not n.startswith("__MACOSX"):
                        (show / Path(n).name).write_bytes(z.read(n))
        else:
            (show / f.name).write_bytes(f.read())
    if not any(show.glob("*.txt")):
        st.error("No .txt scripts found in what you uploaded."); st.stop()
    args = ["--input", str(show), "--out", str(work / "out"), "--per-episode", str(per_ep), "--top", str(top),
            "--cache", str(work / "cache")]
    if eps: args += ["--episodes", eps]
    env = None
    if provider:
        env = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]
        if not key:
            st.error("Please paste your API key, or choose the free rules option."); st.stop()
        args += ["--provider", provider, "--model", model] + (["--base-url", base] if base else [])
    else:
        args += ["--mode", "rules"]
    msg = "Reading the scripts and finding promos..." + (" AI runs can take a few minutes." if provider else "")
    with st.spinner(msg):
        try:
            if env: os.environ[env] = key          # only for this run...
            out = run_main(args)
            st.session_state["out"] = str(out)
        except SystemExit as e:
            st.error(f"The run stopped: {e}")
        except Exception as e:
            st.error(f"Something went wrong: {e}")
        finally:
            if env: os.environ.pop(env, None)      # ...then removed, so no other visitor can use it

# ---------- results ----------
if "out" in st.session_state:
    out = Path(st.session_state["out"])
    promos = json.loads((out / "promos.json").read_text(encoding="utf-8"))
    info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
    ranked = sorted([p for p in promos if p.get("post_rank")], key=lambda p: p["post_rank"])
    st.markdown('<div class="ornament">◆ ◆ ◆</div>', unsafe_allow_html=True)
    st.markdown("## Results")
    m = st.columns(4)
    engine = "Rules (free)" if info["mode"] == "rules" else info.get("model", "AI")
    for col, v, l in zip(m, [info["episodes"], len(promos), engine, f"{info['seconds']:.0f}s"],
                         ["Episodes read", "Promos found", "Engine", "Time taken"]):
        col.markdown(f'<div class="metric"><div class="v">{esc(v)}</div><div class="l">{l}</div></div>', unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["Post these first", "All promos", "Quality checks", "Download"])
    with t1:
        st.caption("Ranked in the order to post them. Times are minutes:seconds from the start of each episode.")
        for p in ranked:
            chips = "".join(f'<span class="chip">Episode {s["episode"]} · {s["start_ts"]} → {s["end_ts"]}</span>' for s in p["segments"])
            flags = "; ".join(p.get("flags", []))
            title = p.get("title") or f"Promo {p['id']}"
            st.markdown(f"""
<div class="promo">
  <div class="top"><div class="rank">{p['post_rank']}</div>
    <div><div class="title">{esc(title)}</div><div class="meta">{p['duration']:.0f} seconds · score {p['score']}</div></div></div>
  {chips}
  <div class="row"><div class="k">Opens with</div><div>{esc(p['hook'])}</div>
  <div class="k">Ends on</div><div>{esc(p['cliffhanger'])}</div>
  <div class="k">Why it works</div><div>{esc(p['why'])}</div>
  <div class="k">Why post it now</div><div>{esc(p.get('rank_reason', ''))}</div></div>
  {f'<div class="note">Check this: {esc(flags)}</div>' if flags else ''}
</div>""", unsafe_allow_html=True)
    with t2:
        rows = [{"Rank": p.get("post_rank"), "Score": p["score"], "Seconds": round(p["duration"]),
                 "Where (episode, start → end)": " + ".join(f"Ep {s['episode']} {s['start_ts']} → {s['end_ts']}" for s in p["segments"]),
                 "Opens with": p["hook"], "Ends on": p["cliffhanger"], "Check this": "; ".join(p.get("flags", []))} for p in promos]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with t3:
        st.markdown((out / "quality.md").read_text(encoding="utf-8"))
    with t4:
        st.write("Download the full results to share with your editor.")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Promos (CSV, for Excel)", (out / "promos.csv").read_bytes(), "promos.csv", use_container_width=True)
        d2.download_button("Promos (JSON)", (out / "promos.json").read_bytes(), "promos.json", use_container_width=True)
        d3.download_button("Full report", (out / "report.md").read_bytes(), "report.md", use_container_width=True)

st.markdown(f"""<div class="foot">◆ &nbsp; Built by <b>Guna Sekhar Subbarao Karanam</b>, IIT Kanpur, for the Kuku AI Generalist assignment
&nbsp;·&nbsp; <a href="{REPO}" target="_blank">Source code on GitHub</a> &nbsp; ◆</div>""", unsafe_allow_html=True)
