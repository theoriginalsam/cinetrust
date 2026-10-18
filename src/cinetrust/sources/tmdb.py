"""TMDB: which movies are in theatres right now, plus TMDB user reviews.

Docs: https://developer.themoviedb.org/reference (free API key; attribution required).
"""

from __future__ import annotations

from .http import ApiClient

VIDEO_LANGUAGES = "en,null,hi,ta,te,ml,kn,ko,ja,zh,es,fr,de,it,pt"


class TMDB:
    def __init__(self, token: str, *, client: ApiClient | None = None):
        # v4 "API Read Access Token" is a JWT (starts with eyJ); otherwise treat it as a v3 api_key.
        if token.startswith("eyJ"):
            kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
        else:
            kwargs = {"params": {"api_key": token}}
        self.client = client or ApiClient("https://api.themoviedb.org/3", **kwargs)

    def now_playing(self, region: str = "US", max_pages: int = 3) -> list[dict]:
        return self._movie_list("movie/now_playing", region, max_pages)

    def upcoming(self, region: str = "US", max_pages: int = 2) -> list[dict]:
        return self._movie_list("movie/upcoming", region, max_pages)

    def _movie_list(self, path: str, region: str, max_pages: int) -> list[dict]:
        movies, seen = [], set()
        for page in range(1, max_pages + 1):
            data = self.client.get(path, region=region, page=page, language="en-US")
            if not data:
                break
            for movie in data.get("results", []):
                if movie["id"] not in seen:
                    seen.add(movie["id"])
                    movies.append(movie)
            if page >= data.get("total_pages", 1):
                break
        return movies

    def movie_details(self, tmdb_id: int) -> dict | None:
        # Without include_video_language TMDB only returns English videos, so e.g. a Tamil
        # release's trailer is missing and its YouTube comments are never fetched.
        return self.client.get(f"movie/{tmdb_id}", append_to_response="external_ids,videos",
                               include_video_language=VIDEO_LANGUAGES)

    def reviews(self, tmdb_id: int, max_pages: int = 3) -> list[dict]:
        out = []
        for page in range(1, max_pages + 1):
            data = self.client.get(f"movie/{tmdb_id}/reviews", page=page)
            if not data:
                break
            out.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break
        return out
