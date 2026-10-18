"""Trakt: community comments/reviews with the commenter's own rating.

Docs: https://trakt.docs.apiary.io/ (free client id). Trakt accepts IMDb ids as movie ids.
"""

from __future__ import annotations

from .http import ApiClient


class Trakt:
    def __init__(self, client_id: str, *, client: ApiClient | None = None):
        self.client = client or ApiClient(
            "https://api.trakt.tv",
            headers={"trakt-api-version": "2", "trakt-api-key": client_id},
            min_interval=0.35,
        )

    def comments(self, imdb_id: str, max_pages: int = 3, limit: int = 100) -> list[dict]:
        out = []
        for page in range(1, max_pages + 1):
            data = self.client.get(
                f"movies/{imdb_id}/comments/newest", page=page, limit=limit, extended="full"
            )
            if not data:
                break
            out.extend(data)
            if len(data) < limit:
                break
        return out
