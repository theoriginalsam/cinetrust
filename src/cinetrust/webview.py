"""JSON payloads for the CineTrust web UI (app/static), built from gold-table frames.

Pure pandas so the Databricks App, the demo backend and the tests share one code path.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import pandas as pd

POSITIVE_AT = 65.0   # implied 0-100 value at or above which a review counts as positive
NEGATIVE_AT = 40.0
SUSPICIOUS_TRUST = 0.5
MAX_TEXT = 2000


def clean(value):
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


def _genres(value) -> list[str]:
    return [g.strip() for g in str(value or "").split(",") if g.strip()]


def _breakdown(value) -> list[dict]:
    data = json.loads(value) if isinstance(value, str) else (value or {})
    rows = [{"source": k, "score": clean(v["score"]), "share": clean(v["share"])} for k, v in data.items()]
    return sorted(rows, key=lambda r: r["share"] or 0, reverse=True)


def _meta(m: dict) -> dict:
    return {
        "imdb_id": m["imdb_id"],
        "title": clean(m.get("title")),
        "release_date": clean(m.get("release_date")),
        "poster_path": clean(m.get("poster_path")),
        "backdrop_path": clean(m.get("backdrop_path")),
        "overview": clean(m.get("overview")),
        "genres": _genres(m.get("genres")),
        "runtime": clean(m.get("runtime")),
        "trailer_key": clean(m.get("trailer_key")),
    }


def days_until(release_date, today: date) -> int | None:
    try:
        return (date.fromisoformat(str(release_date)[:10]) - today).days
    except ValueError:
        return None


def home_payload(now_playing: pd.DataFrame, upcoming: pd.DataFrame, *,
                 generated_at: datetime | None = None, demo: bool = False) -> dict:
    """`now_playing`: gold_movie_scores joined to movie metadata; `upcoming`: gold_upcoming
    left-joined to gold_upcoming_hype."""
    generated_at = generated_at or datetime.now(timezone.utc)
    today = generated_at.date()

    playing = []
    for m in now_playing.sort_values("cinetrust_score", ascending=False).to_dict("records"):
        playing.append({**_meta(m),
            "kind": "now_playing",
            "cinetrust_score": clean(m.get("cinetrust_score")),
            "naive_review_average": clean(m.get("naive_review_average")),
            "confidence": clean(m.get("confidence")),
            "controversy": clean(m.get("controversy")),
            "n_sources": clean(m.get("n_sources")),
            "n_reviews": clean(m.get("n_reviews")) or 0,
            "n_suspicious_reviews": clean(m.get("n_suspicious_reviews")) or 0,
            "farming_alert": bool(m.get("farming_alert")),
            "breakdown": _breakdown(m.get("breakdown")),
        })

    soon = []
    for m in upcoming.to_dict("records"):
        soon.append({**_meta(m),
            "kind": "upcoming",
            "days_to_release": days_until(m.get("release_date"), today),
            "hype_score": clean(m.get("hype_score")),
            "hype_confidence": clean(m.get("hype_confidence")),
            "buzz_7d": clean(m.get("buzz_7d")) or 0,
            "n_reviews": clean(m.get("n_comments")) or 0,
            "n_suspicious_reviews": clean(m.get("n_suspicious_reviews")) or 0,
            "farming_alert": bool(m.get("farming_alert")) if clean(m.get("farming_alert")) is not None else False,
        })
    soon.sort(key=lambda m: (-(m["buzz_7d"] or 0), m["days_to_release"] or 0))

    sources = {b["source"] for m in playing for b in m["breakdown"]}
    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "demo": demo,
        "stats": {
            "movies_in_theatres": len(playing),
            "upcoming": len(soon),
            "reviews_checked": int(sum(m["n_reviews"] for m in playing + soon)),
            "reviews_down_weighted": int(sum(m["n_suspicious_reviews"] for m in playing + soon)),
            "sources": len(sources),
        },
        "now_playing": playing,
        "upcoming": soon,
    }


def polarity(value) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return "positive" if value >= POSITIVE_AT else "negative" if value <= NEGATIVE_AT else "mixed"


def reviews_payload(reviews: pd.DataFrame) -> dict:
    """Every review for one movie, labelled for the UI's source tabs and good/bad sorting.

    `reviews` needs source, author_name, rating, sentiment, text, created_at, url, likes, trust,
    reasons. `value` is the review's 0-100 opinion: its star rating, else its text sentiment.
    """
    out = []
    for r in reviews.to_dict("records"):
        rating, sentiment = clean(r.get("rating")), clean(r.get("sentiment"))
        value = rating * 10 if rating is not None else (sentiment * 100 if sentiment is not None else None)
        text = " ".join(str(r.get("text") or "").split())
        out.append({
            "source": clean(r.get("source")),
            "author": clean(r.get("author_name")),
            "rating": rating,
            "value": None if value is None else round(value, 1),
            "polarity": polarity(value),
            "text": text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1].rstrip() + "…",
            "created_at": clean(r.get("created_at")),
            "url": clean(r.get("url")),
            "likes": clean(r.get("likes")),
            "trust": None if clean(r.get("trust")) is None else round(float(r["trust"]), 3),
            "reasons": [x for x in str(r.get("reasons") or "").split(",") if x],
        })
    counts: dict[str, int] = {}
    for r in out:
        counts[r["source"]] = counts.get(r["source"], 0) + 1
    return {
        "reviews": out,
        "sources": [{"source": s, "count": n} for s, n in sorted(counts.items(), key=lambda kv: -kv[1])],
        "polarity": {p: sum(r["polarity"] == p for r in out) for p in ("positive", "mixed", "negative")},
        "down_weighted": sum((r["trust"] or 1) < SUSPICIOUS_TRUST for r in out),
    }


def write_static(out_dir, now_playing: pd.DataFrame, upcoming: pd.DataFrame,
                 reviews: pd.DataFrame, *, demo: bool = False) -> dict:
    """Write the files the static site reads: home.json + movie/<imdb_id>.json.

    Mirrors the app's /api/home and /api/movie/{id} responses, so one frontend serves both.
    `reviews` holds every review (all movies) with an imdb_id column.
    """
    import shutil
    from pathlib import Path

    out = Path(out_dir)
    shutil.rmtree(out / "movie", ignore_errors=True)  # drop movies that left theatres
    (out / "movie").mkdir(parents=True, exist_ok=True)
    home = home_payload(now_playing, upcoming, demo=demo)
    (out / "home.json").write_text(json.dumps(home, ensure_ascii=False))
    by_movie = dict(tuple(reviews.groupby("imdb_id"))) if not reviews.empty else {}
    for m in home["now_playing"] + home["upcoming"]:
        doc = {"movie": m, **reviews_payload(by_movie.get(m["imdb_id"], reviews.iloc[0:0]))}
        (out / "movie" / f"{m['imdb_id']}.json").write_text(json.dumps(doc, ensure_ascii=False))
    return home
