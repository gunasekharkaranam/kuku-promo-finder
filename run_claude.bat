@echo off
REM Full run with Claude (needs an Anthropic API key with credit: https://console.anthropic.com)
REM Usage: run_claude.bat YOUR_ANTHROPIC_KEY
cd /d "%~dp0"
set ANTHROPIC_API_KEY=%1
python -m pip install --user -q requests reportlab
python -m promofinder.run --input "..\I Married a Broken Soldier. He was a Duke" --provider anthropic --model claude-haiku-5-5 --batch 10 --min-interval 1 --out outputs\llm_claude_full
if errorlevel 1 (echo. & echo RUN FAILED - send the error above to Claude & pause & exit /b 1)
python make_doc.py
echo.
echo Done. Outputs are in outputs\llm_claude_full and the doc is Solution_Doc.pdf
pause
