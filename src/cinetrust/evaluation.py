"""Red-team evaluation: inject synthetic review farms into real data and measure what they do.

No labelled farm data exists, so we attack ourselves: add templated and paraphrased bomb/boost
campaigns to the most-reviewed movies, then report
  * detection: ROC-AUC / average precision of the suspicion score, recall, organic false-positive rate
  * impact: how far each attack moves the score under (a) a naive review average,
    (b) CineTrust without trust weights, (c) full CineTrust.
Real-world farms already in the data are counted as "organic", so detection numbers are conservative.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .demo import farm_envelopes
from .features import build_features
from .local import silver_frames
from .rating import ConsensusConfig, compute_consensus
from .sentiment import SentimentFn, lexicon_sentiment

PredictFn = Callable[[pd.DataFrame], pd.DataFrame]
ATTACKS = [("bomb", "template"), ("boost", "paraphrase"), ("bomb", "paraphrase")]


def inject_farm(imdb_id: str, kind: str, style: str, *, n: int, start: pd.Timestamp,
                rng: np.random.Generator) -> pd.DataFrame:
    tmdb_id = int(rng.integers(10_000, 99_999))
    envs = farm_envelopes(imdb_id, tmdb_id, kind, style, n=n, start=start.floor("s").to_pydatetime(),
                          rng=rng, run_id="redteam", fetched_at="2100-01-01T00:00:00Z")
    _, farm, _ = silver_frames(envs)
    return farm.assign(is_farm=True)


def _scored(reviews: pd.DataFrame, scores: pd.DataFrame, predict_fn: PredictFn,
            sentiment: SentimentFn) -> pd.DataFrame:
    feats = build_features(reviews, scores, sentiment=sentiment)
    pred = predict_fn(feats).reset_index(drop=True)
    return pd.concat([feats.reset_index(drop=True), pred[["suspicion", "trust"]]], axis=1)


def evaluate(predict_fn: PredictFn, reviews: pd.DataFrame, scores: pd.DataFrame, *, seed: int = 7,
             n_targets: int = 3, sentiment: SentimentFn = lexicon_sentiment,
             cfg: ConsensusConfig | None = None) -> dict:
    rng = np.random.default_rng(seed)
    organic = reviews.copy()
    organic["is_farm"] = organic["is_farm"].astype(bool) if "is_farm" in organic else False
    organic["created_at"] = created = pd.to_datetime(organic["created_at"], utc=True)
    targets = organic["imdb_id"].value_counts().index[:n_targets]

    farms, attacks = [], []
    for i, imdb_id in enumerate(targets):
        kind, style = ATTACKS[i % len(ATTACKS)]
        n = max(10, int(0.6 * (organic["imdb_id"] == imdb_id).sum()))
        start = created.max() - pd.Timedelta(hours=float(rng.uniform(6, 72)))
        farms.append(inject_farm(imdb_id, kind, style, n=n, start=start, rng=rng))
        attacks.append({"imdb_id": imdb_id, "kind": kind, "style": style, "n": n})
    attacked = pd.concat([organic, *farms], ignore_index=True)

    clean = _scored(organic, scores, predict_fn, sentiment)
    hit = _scored(attacked, scores, predict_fn, sentiment)
    y, susp = hit["is_farm"].to_numpy(), hit["suspicion"].to_numpy()
    flagged = hit["trust"] < 0.5

    def consensus(df: pd.DataFrame, use_trust: bool) -> pd.DataFrame:
        df = df if use_trust else df.assign(trust=1.0)
        return compute_consensus(df, scores, cfg=cfg).set_index("imdb_id")

    before, after = consensus(clean, True), consensus(hit, True)
    before_nt, after_nt = consensus(clean, False), consensus(hit, False)
    for a in attacks:
        m = a["imdb_id"]
        a["naive_shift"] = round(abs(after.at[m, "naive_review_average"] - before.at[m, "naive_review_average"]), 2)
        a["untrusted_consensus_shift"] = round(abs(after_nt.at[m, "cinetrust_score"] - before_nt.at[m, "cinetrust_score"]), 2)
        a["cinetrust_shift"] = round(abs(after.at[m, "cinetrust_score"] - before.at[m, "cinetrust_score"]), 2)
        a["farm_recall"] = round(float(flagged[hit["imdb_id"].eq(m) & hit["is_farm"]].mean()), 3)

    # A movie with no rated reviews has no naive average before the attack, so compare naive vs
    # CineTrust only on attacks where both are defined.
    comparable = [a for a in attacks if pd.notna(a["naive_shift"])]
    naive = np.mean([a["naive_shift"] for a in comparable]) if comparable else np.nan
    ct_comparable = np.mean([a["cinetrust_shift"] for a in comparable]) if comparable else np.nan
    ct = np.mean([a["cinetrust_shift"] for a in attacks])
    metrics = {
        "roc_auc": round(float(roc_auc_score(y, susp)), 4),
        "average_precision": round(float(average_precision_score(y, susp)), 4),
        "farm_recall": round(float(flagged[y].mean()), 4),
        "organic_false_positive_rate": round(float(flagged[~y].mean()), 4),
        "mean_naive_shift": round(float(naive), 2),
        "mean_untrusted_consensus_shift": round(float(np.mean([a["untrusted_consensus_shift"] for a in attacks])), 2),
        "mean_cinetrust_shift": round(float(ct), 2),
        "shift_reduction_vs_naive": round(float(1 - ct_comparable / naive), 4) if naive else 0.0,
    }
    return {"metrics": metrics, "attacks": attacks, "n_organic": len(organic),
            "n_injected": int(y.sum())}
