@echo off
echo ==================================================================
echo   Starting Medpark Offline Meeting Intelligence System
echo   Mode: 100%% Offline (Air-Gapped)
echo   Local Web Interface: http://127.0.0.1:8000
echo   API Documentation:   http://127.0.0.1:8000/docs
echo ==================================================================

set PYTHONPATH=%~dp0backend
call "%~dp0.venv\Scripts\activate.bat"
python "%~dp0backend\run_server.py"
pause
