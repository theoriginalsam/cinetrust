"""Build the public leaderboard.json that the static site (site/) renders.

Pure pandas so the Databricks job, the sample generator and the tests share one code path.
Only aggregate scores and down-weighted review snippets are published, never author names.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import pandas as pd

SUSPICIOUS_TRUST = 0.5
MAX_TEXT = 300
MAX_FLAGGED_PER_MOVIE = 25


def _clean(value):
    """JSON-safe scalar: NaN/NaT -> None, numpy -> python, timestamps -> ISO strings."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return None if pd.isna(value) else value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _truncate(text, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _breakdown(value) -> dict:
    data = json.loads(value) if isinstance(value, str) else (value or {})
    return {k: {"score": _clean(v["score"]), "share": _clean(v["share"])} for k, v in data.items()}


def flagged_reviews(reviews: pd.DataFrame, limit: int = MAX_FLAGGED_PER_MOVIE) -> dict[str, list]:
    """Down-weighted reviews per imdb_id, least trusted first.

    `reviews` needs imdb_id, source, rating, text, created_at, trust, reasons.
    """
    low = reviews[reviews["trust"] < SUSPICIOUS_TRUST]
    low = low.sort_values(["imdb_id", "trust", "created_at"], ascending=[True, True, False])
    out: dict[str, list] = {}
    for imdb_id, grp in low.groupby("imdb_id", sort=False):
        out[imdb_id] = [{
            "source": _clean(r.source),
            "rating": _clean(r.rating),
            "trust": round(float(r.trust), 3),
            "reasons": [x for x in str(r.reasons or "").split(",") if x],
            "created_at": _clean(r.created_at),
            "text": _truncate(r.text),
        } for r in grp.head(limit).itertuples()]
    return out


def build_leaderboard(scores: pd.DataFrame, movies: pd.DataFrame, reviews: pd.DataFrame,
                      generated_at: datetime | None = None, demo: bool = False) -> dict:
    """`scores` is gold_movie_scores, `movies` has imdb_id/poster_path/release_date."""
    meta = movies[["imdb_id", "poster_path", "release_date"]].drop_duplicates("imdb_id")
    board = scores.drop(columns=["poster_path", "release_date"], errors="ignore").merge(
        meta, on="imdb_id", how="left").sort_values("cinetrust_score", ascending=False)
    flagged = flagged_reviews(reviews)
    out = []
    for m in board.itertuples():
        out.append({
            "imdb_id": m.imdb_id,
            "title": _clean(m.title),
            "poster_path": _clean(m.poster_path),
            "release_date": _clean(m.release_date),
            "cinetrust_score": _clean(m.cinetrust_score),
            "naive_review_average": _clean(m.naive_review_average),
            "confidence": _clean(m.confidence),
            "controversy": _clean(m.controversy),
            "n_sources": _clean(m.n_sources),
            "n_reviews": _clean(m.n_reviews),
            "n_suspicious_reviews": _clean(m.n_suspicious_reviews),
            "farming_alert": bool(m.farming_alert),
            "breakdown": _breakdown(m.breakdown),
            "flagged_reviews": flagged.get(m.imdb_id, []),
        })
    return {
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "demo": demo,
        "movies": out,
    }
