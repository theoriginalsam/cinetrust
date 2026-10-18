import json

import pandas as pd
import pytest

from cinetrust.demo import make_demo_envelopes
from cinetrust.features import build_features
from cinetrust.local import silver_frames
from cinetrust.rating import compute_consensus
from cinetrust.site_export import MAX_TEXT, build_leaderboard
from cinetrust.trust import TrustModel


def test_leaderboard_json_is_public_safe():
    movies, reviews, scores = silver_frames(make_demo_envelopes(seed=3))
    feats = build_features(reviews, scores)
    scored = pd.concat([feats, TrustModel(random_state=3).fit(feats).predict(feats)], axis=1)
    board = compute_consensus(scored, scores, movies)
    scored.loc[scored.index[0], "text"] = "x " * 400  # force truncation
    scored.loc[scored.index[0], "trust"] = 0.01

    doc = json.loads(json.dumps(build_leaderboard(board, movies, scored), allow_nan=False))

    assert len(doc["movies"]) == len(board)
    scores_out = [m["cinetrust_score"] for m in doc["movies"]]
    assert scores_out == sorted(scores_out, reverse=True)
    flagged = [r for m in doc["movies"] for r in m["flagged_reviews"]]
    assert flagged and all(r["trust"] < 0.5 for r in flagged)
    assert all(len(r["text"]) <= MAX_TEXT for r in flagged)
    assert "author" not in json.dumps(doc)
    alert = next(m for m in doc["movies"] if m["farming_alert"])
    assert sum(v["share"] for v in alert["breakdown"].values()) == pytest.approx(1, abs=0.01)
