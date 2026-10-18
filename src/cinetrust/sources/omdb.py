"""OMDb: IMDb rating + votes, Rotten Tomatoes Tomatometer and Metascore for one IMDb id.

Docs: https://www.omdbapi.com/ (free key, 1,000 requests/day).
"""

from __future__ import annotations

from .http import ApiClient


class OMDb:
    def __init__(self, api_key: str, *, client: ApiClient | None = None):
        self.client = client or ApiClient("https://www.omdbapi.com", params={"apikey": api_key})

    def by_imdb_id(self, imdb_id: str) -> dict | None:
        data = self.client.get("/", i=imdb_id, tomatoes="true")
        if not data or data.get("Response") == "False":
            return None
        return data
