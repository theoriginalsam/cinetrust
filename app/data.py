"""Data access for the CineTrust web app.

Warehouse mode (default): reads the gold tables through a Databricks SQL warehouse. Inside a
Databricks App the credentials come from the app's service principal; locally they come from
your CLI profile (`databricks auth login`).

Demo mode (CINETRUST_DEMO=1): runs the local pipeline on synthetic data, no workspace needed.
"""

from __future__ import annotations

import os

import pandas as pd

CATALOG = os.environ.get("CINETRUST_CATALOG", "workspace")
SCHEMA = os.environ.get("CINETRUST_SCHEMA", "cinetrust")
DEMO = os.environ.get("CINETRUST_DEMO") == "1"

REVIEW_COLUMNS = ["source", "author_name", "rating", "sentiment", "text", "created_at", "url",
                  "likes", "trust", "reasons"]


def _t(name: str) -> str:
    return f"`{CATALOG}`.`{SCHEMA}`.`{name}`"


class Warehouse:
    def __init__(self):
        from databricks import sql
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config

        cfg = Config()
        warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
        if not warehouse_id:  # local runs: use the first warehouse you can see
            warehouse_id = next(iter(WorkspaceClient(config=cfg).warehouses.list())).id
        self._connect = lambda: sql.connect(
            server_hostname=cfg.host.removeprefix("https://"),
            http_path=f"/sql/1.0/warehouses/{warehouse_id}",
            credentials_provider=lambda: cfg.authenticate,
        )

    def query(self, statement: str, params: dict | None = None) -> pd.DataFrame:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(statement, params or {})
            return cur.fetchall_arrow().to_pandas()

    def now_playing(self) -> pd.DataFrame:
        return self.query(f"""
            SELECT s.*, m.release_date, m.poster_path, m.backdrop_path, m.overview, m.genres,
                   m.runtime, m.trailer_key
            FROM {_t('gold_movie_scores')} s JOIN {_t('gold_now_playing')} m USING (imdb_id)""")

    def upcoming(self) -> pd.DataFrame:
        try:
            return self.query(f"""
                SELECT u.*, h.hype_score, h.hype_confidence, h.buzz_7d, h.n_comments,
                       h.n_suspicious_reviews, h.farming_alert
                FROM {_t('gold_upcoming')} u LEFT JOIN {_t('gold_upcoming_hype')} h USING (imdb_id)""")
        except Exception:  # hype table appears after the first scoring run with upcoming movies
            return self.query(f"SELECT * FROM {_t('gold_upcoming')}")

    def reviews(self, imdb_id: str) -> pd.DataFrame:
        return self.query(f"""
            SELECT r.source, r.author_name, r.rating, t.sentiment, r.text, r.created_at, r.url,
                   r.likes, t.trust, t.reasons
            FROM {_t('gold_review_trust')} t JOIN {_t('silver_reviews')} r USING (review_id)
            WHERE t.imdb_id = :imdb_id""", {"imdb_id": imdb_id})


class Demo:
    """Same interface, computed in-process from the synthetic demo dataset."""

    def __init__(self):
        from cinetrust.demo import make_demo_envelopes
        from cinetrust.features import build_features
        from cinetrust.local import silver_frames
        from cinetrust.rating import compute_consensus
        from cinetrust.trust import TrustModel

        movies, reviews, scores = silver_frames(make_demo_envelopes())
        feats = build_features(reviews, scores)
        self._reviews = pd.concat([feats, TrustModel().fit(feats).predict(feats)], axis=1)
        board = compute_consensus(self._reviews, scores, movies)
        self._playing = board.merge(movies.drop(columns=["title"]), on="imdb_id")

    def now_playing(self) -> pd.DataFrame:
        return self._playing

    def upcoming(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["imdb_id", "title", "release_date"])

    def reviews(self, imdb_id: str) -> pd.DataFrame:
        return self._reviews.loc[self._reviews["imdb_id"] == imdb_id, REVIEW_COLUMNS]


def get_backend():
    return Demo() if DEMO else Warehouse()
