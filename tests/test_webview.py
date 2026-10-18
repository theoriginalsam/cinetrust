import json
from datetime import datetime, timezone

import pandas as pd

from cinetrust.webview import home_payload, polarity, reviews_payload

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def test_home_payload_shapes_both_lists():
    playing = pd.DataFrame([{
        "imdb_id": "tt1", "title": "A", "cinetrust_score": 80.0, "naive_review_average": float("nan"),
        "confidence": 0.9, "controversy": 3.0, "n_sources": 2, "n_reviews": 10,
        "n_suspicious_reviews": 1, "farming_alert": False, "genres": "Drama, Thriller",
        "breakdown": json.dumps({"imdb": {"score": 80, "share": 0.4}, "tmdb": {"score": 79, "share": 0.6}}),
    }])
    upcoming = pd.DataFrame([
        {"imdb_id": "tt2", "title": "Soon", "release_date": "2026-10-21", "hype_score": 70.0,
         "buzz_7d": 5.0, "n_comments": 50, "n_suspicious_reviews": 0, "farming_alert": False},
        {"imdb_id": "tt3", "title": "Big", "release_date": "2026-11-01", "hype_score": 60.0,
         "buzz_7d": 90.0, "n_comments": 300, "n_suspicious_reviews": 2, "farming_alert": False},
    ])
    doc = home_payload(playing, upcoming, generated_at=NOW)
    [m] = doc["now_playing"]
    assert m["naive_review_average"] is None            # NaN never reaches the JSON
    assert m["genres"] == ["Drama", "Thriller"]
    assert [b["source"] for b in m["breakdown"]] == ["tmdb", "imdb"]   # biggest weight first
    assert [u["title"] for u in doc["upcoming"]] == ["Big", "Soon"]    # most buzz first
    assert doc["upcoming"][1]["days_to_release"] == 4
    assert doc["stats"]["reviews_checked"] == 360
    json.dumps(doc)


def test_reviews_payload_labels_good_and_bad_by_rating_then_sentiment():
    reviews = pd.DataFrame([
        {"source": "tmdb", "rating": 9.0, "sentiment": 0.1, "text": "great", "trust": 1.0, "reasons": ""},
        {"source": "youtube", "rating": None, "sentiment": 0.2, "text": "boring", "trust": 0.2,
         "reasons": "near_duplicate_text,account_burst"},
        {"source": "youtube", "rating": None, "sentiment": None, "text": "🔥🔥", "trust": 1.0, "reasons": ""},
    ])
    doc = reviews_payload(reviews)
    assert [r["polarity"] for r in doc["reviews"]] == ["positive", "negative", None]
    assert doc["reviews"][1]["reasons"] == ["near_duplicate_text", "account_burst"]
    assert doc["sources"] == [{"source": "youtube", "count": 2}, {"source": "tmdb", "count": 1}]
    assert doc["polarity"] == {"positive": 1, "mixed": 0, "negative": 1}
    assert doc["down_weighted"] == 1
    json.dumps(doc)


def test_polarity_thresholds():
    assert polarity(65) == "positive" and polarity(50) == "mixed" and polarity(40) == "negative"


def test_write_static_mirrors_the_api(tmp_path):
    from cinetrust.webview import write_static

    playing = pd.DataFrame([{"imdb_id": "tt1", "title": "A", "cinetrust_score": 80.0,
                             "breakdown": "{}", "n_reviews": 1, "n_suspicious_reviews": 0}])
    upcoming = pd.DataFrame([{"imdb_id": "tt2", "title": "B", "release_date": "2026-12-01"}])
    reviews = pd.DataFrame([{"imdb_id": "tt1", "source": "tmdb", "rating": 8.0, "text": "good", "trust": 1.0}])
    (tmp_path / "movie").mkdir()
    (tmp_path / "movie" / "tt_old.json").write_text("{}")   # a movie that left theatres
    write_static(tmp_path, playing, upcoming, reviews)
    assert sorted(p.name for p in (tmp_path / "movie").iterdir()) == ["tt1.json", "tt2.json"]
    doc = json.loads((tmp_path / "movie" / "tt1.json").read_text())
    assert doc["movie"]["title"] == "A" and doc["reviews"][0]["polarity"] == "positive"
    assert json.loads((tmp_path / "movie" / "tt2.json").read_text())["reviews"] == []
