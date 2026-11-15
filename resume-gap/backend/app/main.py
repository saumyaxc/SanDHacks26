"""FastAPI entry point. From backend/:  uvicorn app.main:app --reload

All routes live under /api so the Vite dev server can proxy them (no CORS needed).
"""

import logging

from fastapi import FastAPI

from app.api import analyze, health, history

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="resume-gap")
app.include_router(health.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
app.include_router(history.router, prefix="/api")
