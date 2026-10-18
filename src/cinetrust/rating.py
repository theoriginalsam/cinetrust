"""CineTrust consensus score: trust-weighted, shrunk, and capped so no single source dominates.

1. Audience reviews (TMDB, Trakt): each review counts with its trust weight; per-source means are
   Bayesian-shrunk toward a global prior, so 3 glowing reviews can't beat 3,000 mixed ones.
2. Aggregate sources (IMDb, Rotten Tomatoes, Metacritic, TMDB votes) count by evidence strength.
3. Diversity cap: with 3+ sources, no source can exceed `max_share` of the final score - this is
   the "not centralized" part: capturing one platform can't move the number much.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ConsensusConfig:
    prior_strength: float = 5.0          # pseudo-reviews pulling a source toward the global prior
    max_share: float = 0.35
    suspicious_trust: float = 0.5
    implied_rating_weight: float = 0.5   # reviews without a star rating count half, via sentiment
    reliability: dict[str, float] = field(default_factory=lambda: {
        "rotten_tomatoes": 1.0, "metacritic": 1.0, "imdb": 1.0, "tmdb": 0.8,
        "tmdb_reviews": 0.7, "trakt_reviews": 0.7,
        "youtube_reviews": 0.4,  # trailer comments: high volume, mixes hype with reviews
    })


def cap_shares(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Normalise weights to shares, then water-fill so no share exceeds `cap` (needs 3+ sources)."""
    shares = {k: w for k, w in weights.items() if w > 0}
    total = sum(shares.values())
    if not total:
        return {}
    shares = {k: w / total for k, w in shares.items()}
    if len(shares) < 3 or cap * len(shares) < 1:
        return shares
    capped: set[str] = set()
    while True:
        over = [k for k, s in shares.items() if k not in capped and s > cap + 1e-12]
        if not over:
            return shares
        capped.update(over)
        free = 1 - cap * len(capped)
        rest_total = sum(s for k, s in shares.items() if k not in capped)
        shares = {k: cap if k in capped else free * s / rest_total for k, s in shares.items()}


def _audience_components(reviews: pd.DataFrame, cfg: ConsensusConfig) -> pd.DataFrame:
    df = reviews.copy()
    rating = pd.to_numeric(df["rating"], errors="coerce")
    sentiment = pd.to_numeric(df["sentiment"], errors="coerce") if "sentiment" in df else np.nan
    df["value"] = (rating * 10).fillna(sentiment * 100)
    df["w"] = df["trust"] * np.where(rating.notna(), 1.0, cfg.implied_rating_weight)
    df = df[df["value"].notna() & (df["w"] > 0)]
    if df.empty:
        return pd.DataFrame(columns=["imdb_id", "source", "score", "evidence"])
    prior = float(np.average(df["value"], weights=df["w"]))
    df["wv"] = df["w"] * df["value"]
    g = df.groupby(["imdb_id", "source"]).agg(sw=("w", "sum"), swv=("wv", "sum")).reset_index()
    c = cfg.prior_strength
    g["score"] = (g["swv"] + c * prior) / (g["sw"] + c)
    g["evidence"] = g["sw"] / (g["sw"] + c)
    g["source"] = g["source"] + "_reviews"
    return g[["imdb_id", "source", "score", "evidence"]]


def _aggregate_components(scores: pd.DataFrame) -> pd.DataFrame:
    if scores is None or scores.empty:
        return pd.DataFrame(columns=["imdb_id", "source", "score", "evidence"])
    df = scores[["imdb_id", "source", "score", "votes"]].copy()
    votes = pd.to_numeric(df["votes"], errors="coerce")
    # Vote-based sources reach full evidence at ~10k votes; critic aggregates count fully.
    df["evidence"] = np.where(votes.notna(), np.minimum(1.0, np.log10(1 + votes.fillna(0)) / 4), 1.0)
    return df[["imdb_id", "source", "score", "evidence"]]


def compute_consensus(reviews: pd.DataFrame, scores: pd.DataFrame,
                      movies: pd.DataFrame | None = None,
                      cfg: ConsensusConfig | None = None) -> pd.DataFrame:
    """`reviews` needs imdb_id, source, rating, sentiment, trust."""
    cfg = cfg or ConsensusConfig()
    components = pd.concat([_audience_components(reviews, cfg), _aggregate_components(scores)],
                           ignore_index=True)
    rating = pd.to_numeric(reviews["rating"], errors="coerce")
    suspicious = reviews["trust"] < cfg.suspicious_trust

    rows = []
    for imdb_id, comp in components.groupby("imdb_id"):
        raw = {r.source: cfg.reliability.get(r.source, 0.5) * r.evidence for r in comp.itertuples()}
        shares = cap_shares(raw, cfg.max_share)
        by_source = comp.set_index("source")["score"]
        score = sum(shares[s] * by_source[s] for s in shares)
        spread = np.sqrt(sum(shares[s] * (by_source[s] - score) ** 2 for s in shares))

        mine = reviews["imdb_id"] == imdb_id
        n_reviews, n_susp = int(mine.sum()), int((mine & suspicious).sum())
        naive = rating[mine].mean() * 10 if rating[mine].notna().any() else np.nan
        rows.append({
            "imdb_id": imdb_id,
            "cinetrust_score": round(score, 1),
            "confidence": round(1 - np.exp(-sum(raw.values())), 3),
            "controversy": round(spread, 1),
            "n_sources": len(shares),
            "n_reviews": n_reviews,
            "n_suspicious_reviews": n_susp,
            "farming_alert": bool(n_susp >= 3 and n_susp / max(n_reviews, 1) >= 0.2),
            "naive_review_average": round(naive, 1) if pd.notna(naive) else None,
            "breakdown": json.dumps({s: {"score": round(by_source[s], 1), "share": round(shares[s], 3)}
                                     for s in sorted(shares, key=shares.get, reverse=True)}),
        })
    out = pd.DataFrame(rows)
    if movies is not None and not movies.empty and not out.empty:
        out = movies[["imdb_id", "title"]].merge(out, on="imdb_id", how="inner")
    return out.sort_values("cinetrust_score", ascending=False).reset_index(drop=True)


def compute_hype(reviews: pd.DataFrame, movies: pd.DataFrame, *, now: pd.Timestamp | None = None,
                 prior_strength: float = 10.0, suspicious_trust: float = 0.5) -> pd.DataFrame:
    """Pre-release hype for upcoming movies, from trailer comments and early reviews.

    hype_score: trust-weighted positivity (0-100), shrunk toward the catalogue mean so a handful
    of comments can't top the chart. buzz_7d: trust-weighted comments in the last 7 days.
    Farmed hype (bot waves of "can't wait!!") is down-weighted exactly like review farms.
    `reviews` needs imdb_id, rating, sentiment, trust, created_at; `movies` needs imdb_id.
    """
    cols = ["imdb_id", "hype_score", "hype_confidence", "buzz_7d", "n_comments", "n_scored",
            "n_suspicious_reviews", "farming_alert"]
    if movies is None or movies.empty:
        return pd.DataFrame(columns=cols)
    now = now or pd.Timestamp.now(tz="UTC")
    df = reviews[reviews["imdb_id"].isin(movies["imdb_id"])].copy()
    rating = pd.to_numeric(df["rating"], errors="coerce")
    sentiment = pd.to_numeric(df["sentiment"], errors="coerce") if "sentiment" in df else np.nan
    df["value"] = (rating * 10).fillna(sentiment * 100)
    created = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df["recent"] = created >= now - pd.Timedelta(days=7)

    scored = df[df["value"].notna()]
    prior = float(np.average(scored["value"], weights=scored["trust"])) if scored["trust"].sum() else 60.0
    rows = []
    for imdb_id in movies["imdb_id"]:
        m, s = df[df["imdb_id"] == imdb_id], scored[scored["imdb_id"] == imdb_id]
        w = float(s["trust"].sum())
        n_susp = int((m["trust"] < suspicious_trust).sum())
        rows.append({
            "imdb_id": imdb_id,
            "hype_score": round((float((s["trust"] * s["value"]).sum()) + prior_strength * prior)
                                / (w + prior_strength), 1),
            "hype_confidence": round(w / (w + prior_strength), 3),
            "buzz_7d": round(float(m.loc[m["recent"], "trust"].sum()), 1),
            "n_comments": int(len(m)),
            "n_scored": int(len(s)),
            "n_suspicious_reviews": n_susp,
            "farming_alert": bool(n_susp >= 3 and n_susp / max(len(m), 1) >= 0.2),
        })
    return pd.DataFrame(rows, columns=cols)
