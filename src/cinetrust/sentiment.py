"""Review-text sentiment in [0, 1] (1 = positive). Used to catch rating/text mismatch.

Default is a dependency-free lexicon scorer; set CINETRUST_SENTIMENT=hf to use a transformer.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

import numpy as np

POSITIVE = {
    "amazing", "awesome", "beautiful", "best", "brilliant", "captivating", "charming", "clever",
    "delight", "delightful", "enjoy", "enjoyed", "excellent", "fantastic", "fun", "funny", "gorgeous",
    "great", "gripping", "hilarious", "incredible", "love", "loved", "masterpiece", "moving",
    "perfect", "powerful", "recommend", "refreshing", "solid", "stunning", "superb", "thrilling",
    "touching", "wonderful", "worth", "good", "strong", "impressive", "memorable", "engaging",
}
NEGATIVE = {
    "awful", "bad", "bland", "bloated", "boring", "confusing", "disappointing", "disappointment",
    "dull", "forgettable", "garbage", "hate", "hated", "lazy", "mess", "mediocre", "messy",
    "painful", "pointless", "poor", "predictable", "ridiculous", "slow", "terrible", "tedious",
    "trash", "ugly", "waste", "weak", "worst", "worse", "cringe", "flat", "nonsense", "unwatchable",
}
NEGATORS = {"not", "no", "never", "isn't", "wasn't", "don't", "didn't", "hardly", "nothing"}
_TOKEN = re.compile(r"[a-z']+")

SentimentFn = Callable[[list[str]], np.ndarray]


def lexicon_sentiment(texts: list[str]) -> np.ndarray:
    out = np.full(len(texts), np.nan)
    for i, text in enumerate(texts):
        tokens = _TOKEN.findall((text or "").lower())
        pos = neg = 0
        for j, tok in enumerate(tokens):
            polarity = 1 if tok in POSITIVE else -1 if tok in NEGATIVE else 0
            if not polarity:
                continue
            if any(t in NEGATORS for t in tokens[max(0, j - 3):j]):
                polarity = -polarity
            pos += polarity > 0
            neg += polarity < 0
        if pos + neg:
            out[i] = (pos + 0.5) / (pos + neg + 1.0)  # smoothed share of positive hits
    return out


def hf_sentiment(model: str = "distilbert-base-uncased-finetuned-sst-2-english") -> SentimentFn:
    from transformers import pipeline

    clf = pipeline("sentiment-analysis", model=model, truncation=True)

    def score(texts: list[str]) -> np.ndarray:
        preds = clf([t or "" for t in texts], batch_size=32)
        return np.array([p["score"] if p["label"] == "POSITIVE" else 1 - p["score"] for p in preds])

    return score


def get_sentiment() -> SentimentFn:
    return hf_sentiment() if os.environ.get("CINETRUST_SENTIMENT") == "hf" else lexicon_sentiment
