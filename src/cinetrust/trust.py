"""Trust model: unsupervised outlier detection + explainable rules -> per-review trust weight.

There are no ground-truth "farm" labels, so the model is an Isolation Forest over the
anti-farming features, combined (noisy-OR) with a few hand-written signals that make every
down-weighted review explainable ("near_duplicate_text", "account_burst", ...).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler

from .features import MODEL_FEATURES


def _col(feats: pd.DataFrame, name: str) -> np.ndarray:
    return pd.to_numeric(feats[name], errors="coerce").fillna(0).to_numpy(dtype=float)


def rule_signals(feats: pd.DataFrame) -> dict[str, np.ndarray]:
    dup = np.expm1(_col(feats, "dup_cluster_size_log")) + 1
    burst = _col(feats, "author_burst_24h")
    extremity = _col(feats, "rating_extremity")
    return {
        "near_duplicate_text": np.where(dup >= 3, np.minimum(0.95, 0.6 + 0.07 * (dup - 3)), 0.0),
        "account_burst": np.where(burst >= 5, np.minimum(0.9, 0.4 + 0.05 * (burst - 5)), 0.0),
        "coordinated_wave": np.where(
            (_col(feats, "movie_burst_z") >= 4) & (extremity >= 0.8), 0.5, 0.0),
        "rating_text_mismatch": np.where(_col(feats, "sentiment_gap") >= 0.7, 0.3, 0.0),
    }


@dataclass
class TrustModel:
    outlier_quantile: float = 0.90   # only the top 10% most anomalous reviews get an ML penalty
    outlier_weight: float = 0.8
    n_estimators: int = 300
    random_state: int = 7

    def fit(self, feats: pd.DataFrame) -> TrustModel:
        X = feats[MODEL_FEATURES].astype(float)
        self.pipeline_ = make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            RobustScaler(),
            IsolationForest(n_estimators=self.n_estimators, random_state=self.random_state),
        )
        self.pipeline_.fit(X)
        self.reference_ = np.sort(-self.pipeline_.score_samples(X))
        return self

    def params(self) -> dict:
        return {"outlier_quantile": self.outlier_quantile, "outlier_weight": self.outlier_weight,
                "n_estimators": self.n_estimators, "random_state": self.random_state}

    def outlier_suspicion(self, feats: pd.DataFrame) -> np.ndarray:
        raw = -self.pipeline_.score_samples(feats[MODEL_FEATURES].astype(float))
        pct = np.searchsorted(self.reference_, raw, "right") / len(self.reference_)
        q = self.outlier_quantile
        return np.clip((pct - q) / (1 - q), 0, 1) * self.outlier_weight

    def predict(self, feats: pd.DataFrame) -> pd.DataFrame:
        signals = rule_signals(feats)
        signals["statistical_outlier"] = self.outlier_suspicion(feats)
        stacked = np.vstack(list(signals.values()))
        suspicion = 1 - np.prod(1 - stacked, axis=0)
        names = np.array(list(signals))
        reasons = [",".join(names[col >= 0.3]) for col in stacked.T]
        return pd.DataFrame({
            "suspicion": suspicion.round(4),
            "trust": (1 - suspicion).round(4),
            "reasons": reasons,
        }, index=feats.index)
