"""Raw API envelopes -> unified silver rows (movies, reviews, source scores).

Stdlib-only on purpose: the DLT pipeline ships these functions to Spark workers by value, and
the local demo uses the exact same code, so there is one definition of "clean data".
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

MOVIE_SCHEMA = (
    "imdb_id STRING, tmdb_id BIGINT, title STRING, release_date STRING, region STRING, "
    "original_language STRING, popularity DOUBLE, poster_path STRING, fetched_at STRING, "
    "list_type STRING, backdrop_path STRING, overview STRING, genres STRING, runtime BIGINT, "
    "trailer_key STRING"
)
REVIEW_SCHEMA = (
    "review_id STRING, source STRING, imdb_id STRING, author_key STRING, author_name STRING, "
    "rating DOUBLE, text STRING, created_at STRING, url STRING, likes BIGINT, "
    "is_spoiler BOOLEAN, author_joined_at STRING, fetched_at STRING"
)
SCORE_SCHEMA = "imdb_id STRING, source STRING, score DOUBLE, votes BIGINT, fetched_at STRING"

OMDB_SOURCES = {
    "Internet Movie Database": "imdb",
    "Rotten Tomatoes": "rotten_tomatoes",
    "Metacritic": "metacritic",
}

_PERCENT = re.compile(r"^([\d.]+)\s*%$")
_FRACTION = re.compile(r"^([\d.]+)\s*/\s*([\d.]+)$")
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def columns(schema: str) -> list[str]:
    return [part.strip().split(" ")[0] for part in schema.split(",")]


def parse_score(value) -> float | None:
    """'7.8/10' -> 78.0, '87%' -> 87.0, '74/100' -> 74.0. Everything ends up on 0-100."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.upper() == "N/A":
        return None
    if m := _PERCENT.match(s):
        return float(m[1])
    if m := _FRACTION.match(s):
        den = float(m[2])
        return round(100 * float(m[1]) / den, 2) if den else None
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def iso_utc(value) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value) -> str:
    if not value:
        return ""
    return _SPACE.sub(" ", html.unescape(_TAGS.sub(" ", str(value)))).strip()


def _rating10(value) -> float | None:
    try:
        r = float(value)
    except (TypeError, ValueError):
        return None
    return min(r, 10.0) if r > 0 else None


def movie_rows(env: dict) -> list[dict]:
    if env.get("kind") != "movie":
        return []
    p = env["payload"]
    imdb_id = env.get("imdb_id") or p.get("imdb_id")
    if not imdb_id:
        return []
    popularity = p.get("popularity")
    return [{
        "imdb_id": imdb_id,
        "tmdb_id": p.get("id"),
        "title": p.get("title"),
        "release_date": p.get("release_date"),
        "region": p.get("region"),
        "original_language": p.get("original_language"),
        "popularity": float(popularity) if popularity is not None else None,
        "poster_path": p.get("poster_path"),
        "fetched_at": env["fetched_at"],
        "list_type": "upcoming" if p.get("upcoming") else "now_playing",
        "backdrop_path": p.get("backdrop_path"),
        "overview": p.get("overview"),
        "genres": ", ".join(g["name"] for g in p.get("genres") or [] if g.get("name")) or None,
        "runtime": p.get("runtime") or None,
        "trailer_key": p.get("trailer_key"),
    }]


def review_rows(env: dict) -> list[dict]:
    source, kind, p = env.get("source"), env.get("kind"), env["payload"]
    if source == "tmdb" and kind == "review":
        details = p.get("author_details") or {}
        author = details.get("username") or p.get("author")
        row = {
            "review_id": f"tmdb:{p['id']}",
            "author_key": f"tmdb:{author}",
            "author_name": p.get("author") or details.get("name"),
            "rating": _rating10(details.get("rating")),
            "text": clean_text(p.get("content")),
            "created_at": iso_utc(p.get("created_at")),
            "url": p.get("url"),
            "likes": None,
            "is_spoiler": None,
            "author_joined_at": None,
        }
    elif source == "trakt" and kind == "comment":
        user = p.get("user") or {}
        slug = (user.get("ids") or {}).get("slug") or user.get("username")
        row = {
            "review_id": f"trakt:{p['id']}",
            "author_key": f"trakt:{slug}",
            "author_name": user.get("username"),
            "rating": _rating10((p.get("user_stats") or {}).get("rating")),
            "text": clean_text(p.get("comment")),
            "created_at": iso_utc(p.get("created_at")),
            "url": None,
            "likes": parse_int(p.get("likes")),
            "is_spoiler": bool(p.get("spoiler")),
            "author_joined_at": iso_utc(user.get("joined_at")),
        }
    elif source == "youtube" and kind == "comment":
        top = (p.get("snippet") or {}).get("topLevelComment") or {}
        c = top.get("snippet") or {}
        channel = (c.get("authorChannelId") or {}).get("value") or c.get("authorDisplayName")
        row = {
            "review_id": f"youtube:{top.get('id') or p.get('id')}",
            "author_key": f"youtube:{channel}",
            "author_name": c.get("authorDisplayName"),
            "rating": None,  # trailer comments carry no stars; sentiment supplies an implied rating
            "text": clean_text(c.get("textOriginal") or c.get("textDisplay")),
            "created_at": iso_utc(c.get("publishedAt")),
            "url": f"https://www.youtube.com/watch?v={c.get('videoId')}&lc={top.get('id')}",
            "likes": parse_int(c.get("likeCount")),
            "is_spoiler": None,
            "author_joined_at": None,
        }
    else:
        return []
    row.update(source=source, imdb_id=env.get("imdb_id"), fetched_at=env["fetched_at"])
    return [row]


def score_rows(env: dict) -> list[dict]:
    source, kind, p = env.get("source"), env.get("kind"), env["payload"]
    imdb_id, fetched_at = env.get("imdb_id"), env["fetched_at"]
    if not imdb_id:
        return []
    if source == "tmdb" and kind == "movie":
        votes = parse_int(p.get("vote_count"))
        if not votes or p.get("vote_average") is None:
            return []
        return [{"imdb_id": imdb_id, "source": "tmdb", "score": round(float(p["vote_average"]) * 10, 2),
                 "votes": votes, "fetched_at": fetched_at}]
    if source == "omdb" and kind == "ratings":
        rows = {}
        for item in p.get("Ratings") or []:
            name = OMDB_SOURCES.get(item.get("Source"))
            score = parse_score(item.get("Value"))
            if name and score is not None:
                rows[name] = score
        if "imdb" not in rows and parse_score(p.get("imdbRating")) is not None:
            rows["imdb"] = parse_score(f"{p['imdbRating']}/10")
        if "metacritic" not in rows and parse_score(p.get("Metascore")) is not None:
            rows["metacritic"] = parse_score(p["Metascore"])
        imdb_votes = parse_int(p.get("imdbVotes"))
        return [{"imdb_id": imdb_id, "source": name, "score": score,
                 "votes": imdb_votes if name == "imdb" else None, "fetched_at": fetched_at}
                for name, score in rows.items()]
    return []


def envelope_from_row(row: dict) -> dict:
    """Bronze keeps the payload as a raw JSON string; decode it for the row functions."""
    env = dict(row)
    payload = env.get("payload")
    env["payload"] = json.loads(payload) if isinstance(payload, str) else (payload or {})
    return env
