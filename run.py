"""Run the IGDesk Downloader backend locally.

Usage:
    python run.py            # serves on http://127.0.0.1:8000
"""
import os

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.app:app", host=host, port=port, reload=True, log_level="info")
