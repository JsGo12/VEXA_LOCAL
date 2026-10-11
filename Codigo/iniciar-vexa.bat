@echo off
REM Inicia Vexa Local (Windows). Requiere Python 3.10+ y Ollama instalados.
cd /d "%~dp0"
if not exist venv (
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)
start "" /min ollama serve
python main.py
