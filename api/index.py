"""
Vercel Python entrypoint. Vercel's Python runtime looks for a module
under api/ that exports an ASGI/WSGI-compatible `app` and wraps it as a
serverless function -- this just re-exports the real app unchanged so
there's exactly one FastAPI app definition (backend/app/main.py), not a
copy that could drift from what runs locally under uvicorn.

vercel.json routes /api/* here.
"""
import sys
from pathlib import Path

# backend/ is a sibling of api/, not on sys.path by default in the
# function's execution environment -- add the repo root so `backend.app`
# imports the same way it does locally (pixi run uvicorn backend.app.main:app).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.main import app  # noqa: E402
