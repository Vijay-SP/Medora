"""
Medpark Meeting Intelligence System - Local Server Runner
"""

import os
import sys
from pathlib import Path
import uvicorn

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("RELOAD", "true").lower() in ("true", "1")
    
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, reload_dirs=[str(backend_dir / "app")])
