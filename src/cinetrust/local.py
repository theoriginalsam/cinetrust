"""Pandas stand-in for the DLT bronze->silver step, used by the local demo and tests."""

from __future__ import annotations

import pandas as pd

from . import normalize as N


def _latest(rows: list[dict], schema: str, keys: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=N.columns(schema))
    if df.empty:
        return df
    # Same semantics as apply_changes(stored_as_scd_type=1, sequence_by=fetched_at).
    return (df.sort_values("fetched_at").drop_duplicates(keys, keep="last")
              .reset_index(drop=True))


def silver_frames(envelopes: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    movies, reviews, scores = [], [], []
    for env in envelopes:
        env = N.envelope_from_row(env)
        movies.extend(N.movie_rows(env))
        reviews.extend(N.review_rows(env))
        scores.extend(N.score_rows(env))

    movies_df = _latest(movies, N.MOVIE_SCHEMA, ["imdb_id"])
    reviews_df = _latest(reviews, N.REVIEW_SCHEMA, ["review_id"])
    reviews_df = reviews_df[reviews_df["imdb_id"].notna() & (reviews_df["text"].str.len() > 0)]
    for col in ("created_at", "author_joined_at", "fetched_at"):
        reviews_df[col] = pd.to_datetime(reviews_df[col], utc=True, errors="coerce")
    scores_df = _latest(scores, N.SCORE_SCHEMA, ["imdb_id", "source"])
    return movies_df, reviews_df.reset_index(drop=True), scores_df
