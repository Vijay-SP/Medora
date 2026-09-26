"""Medpark Meeting Intelligence System - Shared Speech Server Runner.

Starts the whisper.cpp Metal-accelerated queued ASR service on port 8001.
Teammate backends connect to this service using ASR_PROVIDER=remote and REMOTE_ASR_BASE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import uvicorn

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    host = os.environ.get("SPEECH_HOST", "0.0.0.0")
    port = int(os.environ.get("SPEECH_PORT", 8001))
    reload = os.environ.get("RELOAD", "false").lower() in ("true", "1")

    uvicorn.run("app.speech_server:app", host=host, port=port, reload=reload)
