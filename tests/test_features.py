import numpy as np
import pandas as pd

from cinetrust.dedup import near_duplicate_cluster_sizes
from cinetrust.features import MODEL_FEATURES, build_features
from cinetrust.sentiment import lexicon_sentiment


def test_near_duplicates_cluster_but_distinct_texts_do_not():
    template = ("Worst movie of the year and a total waste of money. The {} was awful and the "
                "plot made no sense at all, do not watch this in theatres")
    texts = [template.format(w) for w in ("acting", "script", "ending", "acting")]
    texts += ["A gorgeous, gripping film with a superb lead performance.",
              "Slow and predictable, the third act drags badly.", ""]
    sizes = near_duplicate_cluster_sizes(texts)
    assert (sizes[:4] >= 3).all()
    assert (sizes[4:] == 1).all()


def test_lexicon_sentiment_direction_and_negation():
    pos, neg, negated, none = lexicon_sentiment(
        ["brilliant and wonderful", "boring, awful mess", "not good at all", "the cinema had seats"])
    assert pos > 0.7 and neg < 0.3 and negated < 0.5
    assert np.isnan(none)


def _reviews(n_bot=6):
    base = pd.Timestamp("2026-10-10", tz="UTC")
    rows = [{"review_id": f"o{i}", "source": "tmdb", "imdb_id": "tt1", "author_key": f"tmdb:u{i}",
             "rating": 7.0, "text": f"organic review number {i} with its own words {i * 7}",
             "created_at": base + pd.Timedelta(hours=10 * i)} for i in range(12)]
    rows += [{"review_id": f"b{i}", "source": "trakt", "imdb_id": "tt1", "author_key": "trakt:bot",
              "rating": 1.0, "text": "terrible waste do not watch this garbage film ever again please",
              "created_at": base + pd.Timedelta(days=3, minutes=5 * i)} for i in range(n_bot)]
    return pd.DataFrame(rows)


def test_behaviour_features():
    scores = pd.DataFrame({"imdb_id": ["tt1"], "source": ["imdb"], "score": [72.0], "votes": [1000]})
    f = build_features(_reviews(), scores)
    bots, organic = f["author_key"] == "trakt:bot", f["author_key"] != "trakt:bot"
    assert (f.loc[bots, "author_burst_24h"] == 6).all()
    assert (f.loc[organic, "author_burst_24h"] == 1).all()
    assert f.loc[bots, "movie_burst_z"].min() > f.loc[organic, "movie_burst_z"].max()
    assert f.loc[bots, "consensus_gap"].iloc[0] == (72 - 10) / 100
    assert (f.loc[bots, "dup_cluster_size"] == 6).all()
    assert set(MODEL_FEATURES) <= set(f.columns)


def test_sparse_old_movie_reviews_are_not_a_wave():
    # 60 reviews spread over 7 years (a re-release): no single review should look like a burst.
    base = pd.Timestamp("2019-04-26", tz="UTC")
    df = pd.DataFrame({
        "review_id": [f"r{i}" for i in range(60)], "source": "tmdb", "imdb_id": "tt_old",
        "author_key": [f"tmdb:u{i}" for i in range(60)], "rating": 10.0,
        "text": [f"distinct review {i} words {i * 13}" for i in range(60)],
        "created_at": [base + pd.Timedelta(days=42 * i) for i in range(60)],
    })
    assert build_features(df, None)["movie_burst_z"].max() < 1


def test_features_tolerate_missing_optional_columns_and_ratings():
    df = _reviews().drop(columns=[]).assign(rating=np.nan)
    f = build_features(df, None)
    assert f["consensus_gap"].isna().all()
    assert len(f) == len(df)
