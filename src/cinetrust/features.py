"""Per-review anti-farming features.

Each feature targets one farming tactic:
  dup_cluster_size      copy-paste / templated reviews
  author_burst_24h      one account mass-posting
  author_rating_std     accounts that only ever give 1s (or 10s)
  movie_burst_z         coordinated waves on one movie (review bombing)
  consensus_gap         rating far from what every other source says
  sentiment_gap         "10/10" attached to text that reads like a pan (or vice versa)
  account_age_days      throwaway accounts created right before posting
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dedup import near_duplicate_cluster_sizes
from .sentiment import SentimentFn, lexicon_sentiment

MODEL_FEATURES = [
    "dup_cluster_size_log",
    "author_reviews_log",
    "author_burst_24h",
    "author_rating_std",
    "rating_extremity",
    "consensus_gap",
    "movie_burst_z",
    "sentiment_gap",
    "text_len_log",
    "account_age_days_log",
    "likes_log",
]

_DAY_S = 24 * 3600.0
_HOUR_S = 3600.0
_EPOCH = pd.Timestamp(0, tz="UTC")


def _seconds(times: pd.Series) -> np.ndarray:
    return (times - _EPOCH).dt.total_seconds().to_numpy()


def _optional(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] if col in df.columns else pd.Series(np.nan, index=df.index)


def _window_counts(times: np.ndarray, half_window: float) -> np.ndarray:
    order = np.argsort(times)
    t = times[order]
    counts = np.searchsorted(t, t + half_window, "right") - np.searchsorted(t, t - half_window, "left")
    out = np.empty_like(counts)
    out[order] = counts
    return out


def _per_group_window_counts(df: pd.DataFrame, group: str, half_window: float) -> pd.Series:
    out = pd.Series(1, index=df.index, dtype=float)
    valid = df["created_at"].notna()
    for _, idx in df[valid].groupby(group).groups.items():
        out.loc[idx] = _window_counts(_seconds(df.loc[idx, "created_at"]), half_window)
    return out


def _movie_burst_z(df: pd.DataFrame) -> pd.Series:
    """Poisson z-score of *other* reviews in a +/-1h window vs the movie's average review rate.

    The variance is floored at 1 so sparse catalogues (an old film with 60 reviews over 7 years)
    can't turn a lone review into a 20-sigma "wave"; a wave needs several reviews together.
    """
    z = pd.Series(0.0, index=df.index)
    valid = df["created_at"].notna()
    for idx in df[valid].groupby("imdb_id").groups.values():
        times = _seconds(df.loc[idx, "created_at"])
        span_h = max((times.max() - times.min()) / _HOUR_S, 24.0)
        expected_others = (len(times) - 1) * 2.0 / span_h
        others = _window_counts(times, _HOUR_S) - 1
        z.loc[idx] = (others - expected_others) / np.sqrt(max(expected_others, 1.0))
    return z


def external_consensus(scores: pd.DataFrame | None) -> pd.Series:
    """Mean 0-100 score per movie across the aggregate sources (IMDb, RT, Metacritic, TMDB)."""
    if scores is None or scores.empty:
        return pd.Series(dtype=float)
    return scores.groupby("imdb_id")["score"].mean()


def build_features(reviews: pd.DataFrame, scores: pd.DataFrame | None = None, *,
                   sentiment: SentimentFn = lexicon_sentiment) -> pd.DataFrame:
    df = reviews.copy().reset_index(drop=True)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    text = df["text"].fillna("").astype(str)

    df["text_len_log"] = np.log1p(text.str.len())
    df["dup_cluster_size"] = near_duplicate_cluster_sizes(text.tolist())
    df["dup_cluster_size_log"] = np.log1p(df["dup_cluster_size"] - 1)

    by_author = df.groupby("author_key")
    df["author_reviews_log"] = np.log1p(by_author["review_id"].transform("count"))
    df["author_rating_std"] = by_author["rating"].transform("std")
    df["author_burst_24h"] = _per_group_window_counts(df, "author_key", _DAY_S)

    df["rating_extremity"] = (df["rating"] - 5.5).abs() / 4.5
    consensus = df["imdb_id"].map(external_consensus(scores))
    df["consensus_gap"] = (df["rating"] * 10 - consensus).abs() / 100
    df["movie_burst_z"] = _movie_burst_z(df)

    df["sentiment"] = sentiment(text.tolist())
    df["sentiment_gap"] = (df["rating"] / 10 - df["sentiment"]).abs()

    joined = pd.to_datetime(_optional(df, "author_joined_at"), utc=True, errors="coerce")
    age_days = (df["created_at"] - joined).dt.total_seconds() / 86400
    df["account_age_days_log"] = np.log1p(age_days.clip(lower=0))
    df["likes_log"] = np.log1p(pd.to_numeric(_optional(df, "likes"), errors="coerce"))
    return df
