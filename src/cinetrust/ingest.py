"""Orchestrates one ingestion run across all sources, keyed by IMDb id."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from .landing import LandingWriter
from .sources.http import ApiError
from .sources.youtube import pick_trailer

log = logging.getLogger(__name__)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def run_ingest(tmdb, writer: LandingWriter, *, omdb=None, trakt=None, youtube=None, region: str = "US",
               max_movies: int = 25, max_upcoming: int = 20, review_pages: int = 3) -> dict:
    stats: Counter = Counter()
    playing = tmdb.now_playing(region=region)[:max_movies]
    playing_ids = {m["id"] for m in playing}
    # Upcoming = not yet released and not already in the now-playing list.
    upcoming = [m for m in (tmdb.upcoming(region=region) if max_upcoming else [])
                if m["id"] not in playing_ids and (m.get("release_date") or "") > _today()][:max_upcoming]
    for movie, is_upcoming in [*((m, False) for m in playing), *((m, True) for m in upcoming)]:
        details = tmdb.movie_details(movie["id"])
        if not details:
            continue
        imdb_id = details.get("imdb_id") or (details.get("external_ids") or {}).get("imdb_id")
        if not imdb_id:
            stats["skipped_no_imdb_id"] += 1
            continue

        trailer = pick_trailer(details)
        details = {k: v for k, v in details.items() if k != "videos"}
        writer.emit("tmdb", "movie", imdb_id, {**details, "region": region, "now_playing": not is_upcoming,
                                                "upcoming": is_upcoming, "trailer_key": trailer})
        stats["upcoming" if is_upcoming else "movies"] += 1

        for review in tmdb.reviews(movie["id"], max_pages=review_pages):
            writer.emit("tmdb", "review", imdb_id, review)
            stats["tmdb_reviews"] += 1

        # Secondary sources are best-effort: one failing API must not sink the run.
        if omdb is not None and not is_upcoming:  # no critic/IMDb scores before release
            try:
                ratings = omdb.by_imdb_id(imdb_id)
                if ratings:
                    writer.emit("omdb", "ratings", imdb_id, ratings)
                    stats["omdb_ratings"] += 1
            except ApiError as exc:
                log.warning("omdb failed for %s: %s", imdb_id, exc)
                stats["omdb_errors"] += 1

        if trakt is not None:
            try:
                for comment in trakt.comments(imdb_id, max_pages=review_pages):
                    writer.emit("trakt", "comment", imdb_id, comment)
                    stats["trakt_comments"] += 1
            except ApiError as exc:
                log.warning("trakt failed for %s: %s", imdb_id, exc)
                stats["trakt_errors"] += 1

        if youtube is not None and trailer:
            try:
                for thread in youtube.comment_threads(trailer, max_pages=review_pages):
                    writer.emit("youtube", "comment", imdb_id, thread)
                    stats["youtube_comments"] += 1
            except ApiError as exc:  # e.g. comments disabled on the trailer
                log.warning("youtube failed for %s (%s): %s", imdb_id, trailer, exc)
                stats["youtube_errors"] += 1
    return dict(stats)
