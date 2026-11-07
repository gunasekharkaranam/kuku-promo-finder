@echo off
REM Full run on the input pack with Gemini (free key: https://aistudio.google.com/apikey)
REM Usage: run_gemini.bat YOUR_GEMINI_KEY
cd /d "%~dp0"
set GEMINI_API_KEY=%1
python -m pip install -q requests reportlab
python -m promofinder.run --input "..\I Married a Broken Soldier. He was a Duke" --provider gemini --model gemini-2.5-flash --out outputs\llm_gemini_full
python make_doc.py
echo.
echo Done. Outputs are in outputs\llm_gemini_full and the doc is Solution_Doc.pdf
pause
