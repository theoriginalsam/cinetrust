"""YouTube Data API v3: viewer comments on a movie's official trailer.

Docs: https://developers.google.com/youtube/v3/docs/commentThreads/list (free API key,
10,000 quota units/day; each page of 100 comments costs 1 unit). The trailer's video id comes
from TMDB, so the expensive search endpoint (100 units) is never needed.
"""

from __future__ import annotations

from .http import ApiClient


class YouTube:
    def __init__(self, api_key: str, *, client: ApiClient | None = None):
        self.client = client or ApiClient("https://www.googleapis.com/youtube/v3",
                                          params={"key": api_key}, min_interval=0.1)

    def comment_threads(self, video_id: str, max_pages: int = 2) -> list[dict]:
        out, token = [], None
        for _ in range(max_pages):
            data = self.client.get("commentThreads", part="snippet", videoId=video_id,
                                   maxResults=100, order="time", textFormat="plainText",
                                   pageToken=token)
            if not data:
                break
            out.extend(data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return out


def pick_trailer(details: dict) -> str | None:
    """Best YouTube trailer from TMDB's `videos`: official first, then most recent."""
    videos = [v for v in (details.get("videos") or {}).get("results", [])
              if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("key")]
    if not videos:
        return None
    videos.sort(key=lambda v: (bool(v.get("official")), v.get("published_at") or ""), reverse=True)
    return videos[0]["key"]
