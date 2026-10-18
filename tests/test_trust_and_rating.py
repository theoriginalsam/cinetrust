import json

import pandas as pd
import pytest

from cinetrust.demo import make_demo_envelopes
from cinetrust.evaluation import evaluate
from cinetrust.features import build_features
from cinetrust.local import silver_frames
from cinetrust.rating import ConsensusConfig, cap_shares, compute_consensus, compute_hype
from cinetrust.trust import TrustModel


@pytest.fixture(scope="module")
def demo():
    movies, reviews, scores = silver_frames(make_demo_envelopes(seed=3))
    reviews["is_farm"] = reviews["author_key"].str.contains("bot", regex=False)
    feats = build_features(reviews, scores)
    model = TrustModel(random_state=3).fit(feats)
    scored = pd.concat([feats, model.predict(feats)], axis=1)
    return movies, reviews, scores, model, scored


def test_cap_shares_limits_any_single_source():
    shares = cap_shares({"a": 10, "b": 1, "c": 1, "d": 1}, 0.35)
    assert sum(shares.values()) == pytest.approx(1)
    assert max(shares.values()) == pytest.approx(0.35)
    assert shares["b"] == pytest.approx(shares["c"])


def test_cap_shares_needs_three_sources_and_drops_zero_weights():
    assert cap_shares({"a": 3, "b": 1}, 0.35) == {"a": 0.75, "b": 0.25}
    assert cap_shares({"a": 0, "b": 0}, 0.35) == {}


def test_bayesian_shrinkage_keeps_few_reviews_from_topping_the_board():
    # Two perfect reviews vs 200 strong ones, in a catalogue whose typical movie scores ~5/10.
    n = {"few": 2, "many": 200, "typical": 300}
    reviews = pd.DataFrame({
        "imdb_id": [m for m, k in n.items() for _ in range(k)],
        "source": ["tmdb"] * sum(n.values()),
        "rating": [10.0] * 2 + [8.5] * 200 + [5.0] * 300,
        "sentiment": [None] * sum(n.values()),
        "trust": [1.0] * sum(n.values()),
    })
    board = compute_consensus(reviews, pd.DataFrame(columns=["imdb_id", "source", "score", "votes"]))
    assert board["imdb_id"].tolist()[:2] == ["many", "few"]


def test_farms_get_low_trust_and_organic_reviews_do_not(demo):
    *_, scored = demo
    farm, organic = scored[scored["is_farm"]], scored[~scored["is_farm"]]
    assert farm["trust"].mean() < 0.3
    assert organic["trust"].mean() > 0.9
    assert (farm["reasons"] != "").all()


def test_review_bomb_is_flagged_and_does_not_sink_the_best_movie(demo):
    movies, _, scores, _, scored = demo
    board = compute_consensus(scored, scores, movies).set_index("title")
    bombed = board.loc["Glass Orchard"]
    assert bombed["farming_alert"]
    assert bombed["naive_review_average"] < 65          # the farm wrecks a plain average...
    assert bombed["cinetrust_score"] > 80               # ...but not the CineTrust score
    assert set(json.loads(bombed["breakdown"])) >= {"imdb", "rotten_tomatoes", "metacritic"}


def test_redteam_eval_reports_detection_and_resistance(demo):
    _, reviews, scores, model, _ = demo
    m = evaluate(model.predict, reviews, scores, seed=11)["metrics"]
    assert m["roc_auc"] > 0.95
    assert m["organic_false_positive_rate"] < 0.05
    assert m["mean_cinetrust_shift"] < m["mean_untrusted_consensus_shift"] <= m["mean_naive_shift"]


def test_diversity_cap_bounds_damage_from_one_captured_source():
    reviews = pd.DataFrame({"imdb_id": ["m"] * 500, "source": ["trakt"] * 500, "rating": [1.0] * 500,
                            "sentiment": [None] * 500, "trust": [1.0] * 500})
    scores = pd.DataFrame({"imdb_id": ["m"] * 3, "source": ["imdb", "rotten_tomatoes", "metacritic"],
                           "score": [85.0, 90.0, 88.0], "votes": [50000, None, None]})
    row = compute_consensus(reviews, scores, cfg=ConsensusConfig(max_share=0.35)).iloc[0]
    assert json.loads(row["breakdown"])["trakt_reviews"]["share"] <= 0.35 + 1e-9
    assert row["cinetrust_score"] > 55


def test_hype_ranks_loved_trailers_and_ignores_farmed_hype():
    now = pd.Timestamp("2026-10-17", tz="UTC")
    def comments(imdb_id, n, sentiment, trust):
        return pd.DataFrame({"imdb_id": imdb_id, "rating": None, "sentiment": sentiment,
                             "trust": trust, "created_at": now - pd.Timedelta(days=1)}, index=range(n))
    reviews = pd.concat([comments("loved", 200, 0.9, 1.0), comments("meh", 200, 0.4, 1.0),
                         comments("farmed", 200, 1.0, 0.05), comments("farmed", 20, 0.4, 1.0)])
    hype = compute_hype(reviews, pd.DataFrame({"imdb_id": ["loved", "meh", "farmed"]}), now=now)
    by = hype.set_index("imdb_id")
    assert by.at["loved", "hype_score"] > by.at["meh", "hype_score"]
    assert by.at["farmed", "farming_alert"] and not by.at["loved", "farming_alert"]
    assert by.at["farmed", "hype_score"] < by.at["loved", "hype_score"]
    assert by.at["loved", "buzz_7d"] == 200
