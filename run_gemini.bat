@echo off
REM Full run on the input pack with Gemini (free key: https://aistudio.google.com/apikey)
REM Usage: run_gemini.bat YOUR_GEMINI_KEY
cd /d "%~dp0"
set GEMINI_API_KEY=%1
python -m pip install --user -q requests reportlab
python -m promofinder.run --input "..\I Married a Broken Soldier. He was a Duke" --provider gemini --model gemini-3.8-flash --out outputs\llm_gemini_full
if errorlevel 1 (echo. & echo RUN FAILED - send the error above to Claude & pause & exit /b 1)
python make_doc.py
echo.
echo Done. Outputs are in outputs\llm_gemini_full and the doc is Solution_Doc.pdf
pause
