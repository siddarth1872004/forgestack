"""Vercel-compatible FastAPI entrypoint.

Vercel loads this root file as the module ``app``. Expose the sibling
``app/`` directory as its package search path before importing app.main,
so the entrypoint filename does not hide the actual application package.
"""
from pathlib import Path

# Vercel imports this file as module ``app``; make it package-like so
# ``app.main`` resolves to the sibling app/ directory rather than failing.
__path__ = [str(Path(__file__).resolve().parent / "app")]

from app.main import app  # noqa: E402

__all__ = ["app"]
