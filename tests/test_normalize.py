import pytest

from cinetrust import normalize as N
from cinetrust.local import silver_frames


@pytest.mark.parametrize("raw,expected", [
    ("7.8/10", 78.0), ("87%", 87.0), ("74/100", 74.0), ("N/A", None), ("", None), (None, None), (61, 61.0),
])
def test_parse_score(raw, expected):
    assert N.parse_score(raw) == expected


def test_parse_int_handles_thousands():
    assert N.parse_int("123,456") == 123456
    assert N.parse_int("N/A") is None


def env(source, kind, payload, imdb="tt1", fetched="2026-10-16T00:00:00Z"):
    return {"source": source, "kind": kind, "imdb_id": imdb, "fetched_at": fetched, "run_id": "t",
            "payload": payload}


def test_tmdb_review_row():
    [row] = N.review_rows(env("tmdb", "review", {
        "id": "abc", "author": "Jo", "content": "<p>Great &amp; fun</p>",
        "author_details": {"username": "jo1", "rating": 8.0}, "created_at": "2026-10-10T08:00:00.000Z",
    }))
    assert row["review_id"] == "tmdb:abc"
    assert row["author_key"] == "tmdb:jo1"
    assert row["rating"] == 8.0
    assert row["text"] == "Great & fun"
    assert row["created_at"] == "2026-10-10T08:00:00Z"


def test_trakt_comment_row_and_missing_rating():
    [row] = N.review_rows(env("trakt", "comment", {
        "id": 5, "comment": "ok", "likes": 2, "spoiler": True, "created_at": "2026-10-10T08:00:00Z",
        "user_stats": {"rating": None}, "user": {"username": "Al", "ids": {"slug": "al"}},
    }))
    assert row["review_id"] == "trakt:5" and row["author_key"] == "trakt:al"
    assert row["rating"] is None and row["is_spoiler"] is True and row["likes"] == 2


def test_omdb_scores_are_on_0_100():
    rows = N.score_rows(env("omdb", "ratings", {
        "imdbVotes": "12,000",
        "Ratings": [
            {"Source": "Internet Movie Database", "Value": "7.5/10"},
            {"Source": "Rotten Tomatoes", "Value": "91%"},
            {"Source": "Metacritic", "Value": "70/100"},
        ],
    }))
    by = {r["source"]: r for r in rows}
    assert by["imdb"]["score"] == 75.0 and by["imdb"]["votes"] == 12000
    assert by["rotten_tomatoes"]["score"] == 91.0
    assert by["metacritic"]["score"] == 70.0 and by["metacritic"]["votes"] is None


def test_tmdb_movie_yields_movie_and_score():
    e = env("tmdb", "movie", {"id": 9, "title": "X", "vote_average": 6.4, "vote_count": 800})
    assert N.movie_rows(e)[0]["tmdb_id"] == 9
    assert N.score_rows(e) == [{"imdb_id": "tt1", "source": "tmdb", "score": 64.0, "votes": 800,
                                "fetched_at": "2026-10-16T00:00:00Z"}]


def test_envelope_from_row_decodes_payload_string():
    assert N.envelope_from_row({"payload": '{"a": 1}'})["payload"] == {"a": 1}


def test_silver_keeps_latest_version_of_each_review():
    payload = {"id": "r1", "author": "a", "author_details": {"rating": 4}, "created_at": "2026-10-01T00:00:00Z"}
    old = env("tmdb", "review", {**payload, "content": "old text"}, fetched="2026-10-01T00:00:00Z")
    new = env("tmdb", "review", {**payload, "content": "edited text"}, fetched="2026-10-02T00:00:00Z")
    _, reviews, _ = silver_frames([new, old])
    assert reviews["text"].tolist() == ["edited text"]


def test_youtube_comment_row_has_no_rating_and_links_to_comment():
    [row] = N.review_rows(env("youtube", "comment", {
        "id": "thr1",
        "snippet": {"videoId": "vid9", "topLevelComment": {"id": "c1", "snippet": {
            "videoId": "vid9", "textOriginal": "Saw it last night, loved it", "likeCount": 12,
            "authorDisplayName": "@fan", "authorChannelId": {"value": "UC123"},
            "publishedAt": "2026-10-12T20:00:00Z"}}},
    }))
    assert row["review_id"] == "youtube:c1" and row["author_key"] == "youtube:UC123"
    assert row["rating"] is None and row["likes"] == 12
    assert row["url"] == "https://www.youtube.com/watch?v=vid9&lc=c1"
