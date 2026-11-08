"""Streamlit UI:  streamlit run app.py"""
import io, json, os, tempfile, zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
from promofinder.run import main as run_main
from promofinder.llm import DEFAULT_MODELS

st.set_page_config(page_title="Kuku Promo Finder", page_icon="🎬", layout="wide")
st.markdown("""<style>
h1 {background: linear-gradient(90deg,#4F8BFF,#FF4F9A); -webkit-background-clip:text; color:transparent;}
.card {background:#1D2F66; border-left:6px solid #FF4F9A; border-radius:10px; padding:14px 18px; margin:10px 0;}
.seg {background:#4F8BFF33; border:1px solid #4F8BFF; border-radius:6px; padding:2px 8px; margin-right:6px; font-family:monospace;}
.flag {color:#FFB347;}
</style>""", unsafe_allow_html=True)
st.title("Kuku Promo Finder")
st.caption("Upload a show's episode screenplays (.txt files or one .zip). Get ranked 20-60s promos with exact timestamps.")

with st.sidebar:
    st.header("Model")
    choice = st.selectbox("Engine", ["rules (free, no key)", "gemini", "openai-compatible", "anthropic"])
    provider = {"rules (free, no key)": None, "gemini": "gemini", "openai-compatible": "openai", "anthropic": "anthropic"}[choice]
    model = key = base = None
    if provider:
        model = st.text_input("Model name", DEFAULT_MODELS[provider])
        key = st.text_input("API key", type="password", help="Used only for this run, never stored.")
        if provider == "openai":
            base = st.text_input("Base URL", "https://api.openai.com/v1")
    per_ep = st.slider("Max promos per episode", 1, 5, 3)
    top = st.slider("How many to rank for posting", 5, 20, 10)
    eps = st.text_input("Episodes (blank = all, e.g. 1-10)", "")

files = st.file_uploader("Screenplays", type=["txt", "zip"], accept_multiple_files=True)

if st.button("Find promos", type="primary", disabled=not files):
    work = Path(tempfile.mkdtemp()); show = work / "show"; show.mkdir()
    for f in files:
        if f.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(f.read())) as z:
                for n in z.namelist():
                    if n.lower().endswith(".txt") and not n.startswith("__MACOSX"):
                        (show / Path(n).name).write_bytes(z.read(n))
        else:
            (show / f.name).write_bytes(f.read())
    args = ["--input", str(show), "--out", str(work / "out"), "--per-episode", str(per_ep), "--top", str(top),
            "--cache", str(work / "cache")]
    if eps: args += ["--episodes", eps]
    if provider:
        env = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]
        args += ["--provider", provider, "--model", model] + (["--base-url", base] if base else [])
    else:
        env = None
        args += ["--mode", "rules"]
    if env and not key:
        st.error("Please paste your API key in the sidebar (or choose the free rules engine)."); st.stop()
    with st.spinner("Reading episodes and finding promos..."):
        try:
            if env: os.environ[env] = key          # only for this run...
            out = run_main(args)
            st.session_state["out"] = str(out)
        except SystemExit as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Run failed: {e}")
        finally:
            if env: os.environ.pop(env, None)      # ...then removed, so no other visitor can use it

if "out" in st.session_state:
    out = Path(st.session_state["out"])
    promos = json.loads((out / "promos.json").read_text(encoding="utf-8"))
    info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
    ranked = sorted([p for p in promos if p.get("post_rank")], key=lambda p: p["post_rank"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Episodes", info["episodes"]); c2.metric("Promos found", len(promos))
    c3.metric("Engine", info.get("model", "rules")); c4.metric("Run time", f"{info['seconds']}s")
    tab1, tab2, tab3 = st.tabs(["Post these first", "All promos", "Quality checks"])
    with tab1:
        for p in ranked:
            segs = "".join(f"<span class='seg'>Ep{s['episode']} {s['start_ts']} → {s['end_ts']}</span>" for s in p["segments"])
            flags = "; ".join(p.get("flags", []))
            st.markdown(f"<div class='card'><b>#{p['post_rank']} {p.get('title') or p['id']}</b> · {p['duration']}s · score {p['score']}<br>{segs}"
                        f"<br><b>Hook:</b> {p['hook']}<br><b>Cliffhanger:</b> {p['cliffhanger']}<br><b>Why:</b> {p['why']}"
                        f"<br><b>Why post now:</b> {p.get('rank_reason', '')}"
                        + (f"<br><span class='flag'>⚠ {flags}</span>" if flags else "") + "</div>", unsafe_allow_html=True)
    with tab2:
        rows = [{"id": p["id"], "rank": p.get("post_rank"), "score": p["score"], "sec": p["duration"],
                 "segments": " + ".join(f"Ep{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"]),
                 "hook": p["hook"], "cliffhanger": p["cliffhanger"], "flags": "; ".join(p.get("flags", []))} for p in promos]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with tab3:
        st.markdown((out / "quality.md").read_text(encoding="utf-8"))
    d1, d2, d3 = st.columns(3)
    d1.download_button("promos.json", (out / "promos.json").read_bytes(), "promos.json")
    d2.download_button("promos.csv", (out / "promos.csv").read_bytes(), "promos.csv")
    d3.download_button("report.md", (out / "report.md").read_bytes(), "report.md")
