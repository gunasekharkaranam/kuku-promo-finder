# Kuku Promo Finder

**Live web app:** https://kukupromofinder.streamlit.app/  

Raw outputs from the full input pack (rules-only and Gemini runs): https://drive.google.com/drive/folders/1L1PLHQtTvaRCHe4oTpr5IvjGX_tAT0cc?usp=sharing

Reads a microdrama's episode screenplays and finds the best **20–60 second promos** (hook in the
first 3 seconds, cliffhanger at the end, makes sense to a stranger). For each promo it gives the
episode and start/end timestamps of every segment, the hook, the cliffhanger, one line on why it
works, and a ranked "post these first" list. Kuku AI Generalist assignment, Problem 1.

## Quick start

```bash
pip install -r requirements.txt

# 1) Free, no API key (rules only, ~13 s for 50 episodes)
python -m promofinder.run --input "path/to/show_folder" --mode rules

# 2) With an LLM (default: Gemini 3.8 Flash, free key at https://aistudio.google.com/apikey)
export GEMINI_API_KEY=...            # Windows: set GEMINI_API_KEY=...
python -m promofinder.run --input "path/to/show_folder" --provider gemini

# 3) Web app
streamlit run app.py
```

Windows one-click full run: `run_gemini.bat YOUR_GEMINI_KEY` (expects the show folder next to this repo).

### Swap the model
| Provider | Example |
|---|---|
| Gemini | `--provider gemini --model gemini-3.8-flash` (env `GEMINI_API_KEY`) |
| Any OpenAI-compatible API (OpenAI, Groq, OpenRouter, vLLM, Ollama, an internal gateway) | `--provider openai --model gpt-4o-mini --base-url https://.../v1` (env `OPENAI_API_KEY`) |
| Anthropic | `--provider anthropic --model claude-haiku-5-5` (env `ANTHROPIC_API_KEY`) |
| Offline test model | `--provider mock` |

Other options: `--episodes 1-10`, `--per-episode 3`, `--top 10`, `--min-interval 4` (seconds between
calls, for free-tier rate limits), `--out folder`. Model replies are cached in `.cache/`, so re-runs are free.

## Input format
A folder of `.txt` screenplays, one per episode, as in the Kuku input pack: `EPISODE NUMBER`,
`EPISODE LOGLINE`, `CONTINUITY NOTES`, scenes, and blocks like `**NAME (Tone):**` / `**ACTION:**` /
`**CAMERA:**` / `**SOUND FX:**`, each followed by `Start: (MM:SS.ss) | End: (MM:SS.ss)` and the text.

## Output (one folder per run)
| File | What |
|---|---|
| `promos.json` / `promos.csv` | every promo: segments, duration, hook, cliffhanger, why, model + rule scores, flags, post rank |
| `report.md` | ranked "post these first" list with script excerpts, then all promos by episode |
| `quality.md` | automatic checks, flagged picks, model-vs-rules disagreements, rejected model answers |
| `review_sheet.csv` | blank sheet for an editor to mark each promo (hook ok? ends unresolved? would post?) |
| `llm_raw/` | the model's unedited replies (one per episode + the ranking call) |
| `run_info.json` | model, calls, tokens, time |

## How it works
```
screenplays ─► parser ─► timed events ─┬─► rules engine: every clean-cut 20–60 s window, teasers,
                                       │   cross-episode stretches; scores hook / cliff / stand-alone
                                       └─► LLM: per episode, propose ≤3 promos as JSON
                                               │
                         checker (code): snap to clean cuts, fix/reject bad length or timestamps,
                         drop duplicates, re-score with rules, flag problems
                                               │
                         LLM ranking: posting order with reasons (premise, variety, spoilers)
                                               │
                         report.md · promos.csv · quality.md · review_sheet.csv  ─► editor checks top 10
```
Code layout: `promofinder/parser.py`, `rules.py`, `candidates.py` (rules finder), `llm.py` (providers),
`llm_finder.py` (prompts + checker + ranking), `run.py` (CLI + outputs). `make_doc.py` builds the 2-page doc.

## Tests
`python tests/test_basic.py` (or `pytest tests`). Uses a tiny synthetic screenplay and the offline mock model.

## Confidentiality
The Kuku input pack and run outputs (which quote it) are **not** in this repo (`.gitignore`).
