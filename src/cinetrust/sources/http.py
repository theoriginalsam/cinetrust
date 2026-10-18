"""Small HTTP client shared by the API connectors: rate limiting + retry with backoff."""

from __future__ import annotations

import time
from typing import Any

import requests

USER_AGENT = "CineTrust/0.1 (portfolio project; https://github.com/)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        min_interval: float = 0.25,
        timeout: float = 20.0,
        max_retries: int = 4,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.params = params or {}
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.session.headers.update(headers or {})
        self._last_call = 0.0

    def get(self, path: str, **params: Any) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        query = {**self.params, **{k: v for k, v in params.items() if v is not None}}
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = self.session.get(url, params=query, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise ApiError(f"GET {url} failed: {exc}") from exc
                time.sleep(2**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
                continue
            if resp.status_code == 404:
                return None
            if not resp.ok:
                raise ApiError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise ApiError(f"GET {url} exhausted retries")
