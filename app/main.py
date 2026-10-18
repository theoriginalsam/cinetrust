"""CineTrust web app: FastAPI JSON API + static frontend, run as a Databricks App.

  GET /api/home                  movies in theatres + upcoming, for the home page
  GET /api/movie/{imdb_id}       one movie with every review (source, good/bad, trust, reasons)
  GET /                          the single-page frontend in app/static
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from cinetrust.webview import home_payload, reviews_payload  # noqa: E402
from data import DEMO, get_backend  # noqa: E402

CACHE_SECONDS = 300
app = FastAPI(title="CineTrust", docs_url=None, redoc_url=None)
_backend = None
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def backend():
    global _backend
    with _lock:
        if _backend is None:
            _backend = get_backend()
    return _backend


def cached(key: str, build):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = build()
    _cache[key] = (time.time(), value)
    return value


@app.get("/api/home")
def home():
    return cached("home", lambda: home_payload(backend().now_playing(), backend().upcoming(), demo=DEMO))


@app.get("/api/movie/{imdb_id}")
def movie(imdb_id: str):
    doc = home()
    found = next((m for m in doc["now_playing"] + doc["upcoming"] if m["imdb_id"] == imdb_id), None)
    if found is None:
        raise HTTPException(404, "Movie not found")
    reviews = cached(f"reviews:{imdb_id}", lambda: reviews_payload(backend().reviews(imdb_id)))
    return {"movie": found, **reviews}


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
