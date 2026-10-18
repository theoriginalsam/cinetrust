from cinetrust.ingest import run_ingest
from cinetrust.landing import LandingWriter, read_landing
from cinetrust.local import silver_frames
from cinetrust.sources.http import ApiError


class FakeTMDB:
    def now_playing(self, region):
        return [{"id": 1}, {"id": 2}]

    def upcoming(self, region):
        # id 1 is already playing; id 4 already released; id 3 is genuinely upcoming.
        return [{"id": 1, "release_date": "2999-01-01"}, {"id": 4, "release_date": "2000-01-01"},
                {"id": 3, "release_date": "2999-01-01"}]

    def movie_details(self, tmdb_id):
        if tmdb_id == 2:
            return {"id": 2, "title": "No IMDb id"}
        if tmdb_id == 3:
            return {"id": 3, "title": "Soon", "imdb_id": "tt0000003", "genres": [{"name": "Drama"}]}
        return {"id": 1, "title": "Film", "external_ids": {"imdb_id": "tt0000001"},
                "vote_average": 7.0, "vote_count": 100,
                "videos": {"results": [
                    {"site": "YouTube", "type": "Teaser", "key": "teaser1", "official": True},
                    {"site": "YouTube", "type": "Trailer", "key": "fanmade", "official": False},
                    {"site": "YouTube", "type": "Trailer", "key": "official1", "official": True},
                ]}}

    def reviews(self, tmdb_id, max_pages):
        return [{"id": "r1", "author": "a", "content": "Good film", "author_details": {"rating": 7},
                 "created_at": "2026-10-01T00:00:00Z"}]


class FakeOMDb:
    def by_imdb_id(self, imdb_id):
        return {"Ratings": [{"Source": "Rotten Tomatoes", "Value": "80%"}]}


class FakeYouTube:
    def __init__(self):
        self.videos = []

    def comment_threads(self, video_id, max_pages):
        self.videos.append(video_id)
        return [{"id": "t1", "snippet": {"topLevelComment": {"id": "c1", "snippet": {
            "videoId": video_id, "textOriginal": "Loved it", "publishedAt": "2026-10-02T00:00:00Z",
            "authorChannelId": {"value": "UC1"}}}}}]


class BrokenTrakt:
    def comments(self, imdb_id, max_pages):
        raise ApiError("trakt down")


def test_ingest_writes_landing_files_that_normalize(tmp_path):
    writer = LandingWriter(tmp_path, run_id="run1")
    youtube = FakeYouTube()
    stats = run_ingest(FakeTMDB(), writer, omdb=FakeOMDb(), trakt=BrokenTrakt(), youtube=youtube)
    paths = writer.flush()

    assert stats == {"movies": 1, "upcoming": 1, "tmdb_reviews": 2, "omdb_ratings": 1,
                     "trakt_errors": 2, "youtube_comments": 1, "skipped_no_imdb_id": 1}
    assert youtube.videos == ["official1"]  # official trailer beats teaser and fan uploads
    assert sorted(p.parent.parent.name for p in paths) == ["omdb", "tmdb", "youtube"]
    assert not list(tmp_path.rglob("_tmp_*"))

    movies, reviews, scores = silver_frames(read_landing(tmp_path))
    by_id = movies.set_index("imdb_id")
    assert by_id.loc["tt0000001", "list_type"] == "now_playing"
    assert by_id.loc["tt0000003", "list_type"] == "upcoming"  # and no OMDb call for it
    assert by_id.loc["tt0000003", "genres"] == "Drama"
    assert sorted(reviews["review_id"]) == ["tmdb:r1", "youtube:c1"]
    assert sorted(scores["source"]) == ["rotten_tomatoes", "tmdb"]
