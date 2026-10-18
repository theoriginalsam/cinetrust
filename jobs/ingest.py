"""Fetch now-playing movies and their reviews/scores from TMDB, OMDb and Trakt into the landing zone.

On Databricks:  --landing=/Volumes/<catalog>/<schema>/landing   (keys from the secret scope)
Locally:        --landing=data/landing [--upload-to=/Volumes/...] (keys from env vars:
                TMDB_TOKEN, OMDB_API_KEY, TRAKT_CLIENT_ID, YOUTUBE_API_KEY)
"""

import argparse
import logging
import sys
from pathlib import Path


def _default_src() -> str:
    try:
        return str(Path(__file__).resolve().parents[1] / "src")
    except NameError:  # some Databricks runners don't define __file__
        return "src"


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", default=_default_src())
    p.add_argument("--landing", required=True)
    p.add_argument("--upload-to", help="Also copy the written files into this /Volumes path")
    p.add_argument("--region", default="US")
    p.add_argument("--max-movies", type=int, default=25)
    p.add_argument("--max-upcoming", type=int, default=20)
    p.add_argument("--review-pages", type=int, default=3)
    p.add_argument("--secret-scope", default="cinetrust")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sys.path.insert(0, args.src)
    from cinetrust.ingest import run_ingest
    from cinetrust.landing import LandingWriter, upload_to_volume
    from cinetrust.platform import get_secret
    from cinetrust.sources import TMDB, OMDb, Trakt, YouTube

    tmdb_token = get_secret(args.secret_scope, "tmdb_token", "TMDB_TOKEN")
    if not tmdb_token:
        raise SystemExit("TMDB token missing: set TMDB_TOKEN or secret <scope>/tmdb_token")
    omdb_key = get_secret(args.secret_scope, "omdb_key", "OMDB_API_KEY")
    trakt_id = get_secret(args.secret_scope, "trakt_client_id", "TRAKT_CLIENT_ID")
    youtube_key = get_secret(args.secret_scope, "youtube_api_key", "YOUTUBE_API_KEY")
    if not omdb_key:
        logging.warning("No OMDb key: IMDb / Rotten Tomatoes / Metacritic scores will be skipped")
    if not trakt_id:
        logging.warning("No Trakt client id: Trakt community reviews will be skipped")
    if not youtube_key:
        logging.warning("No YouTube API key: trailer comments will be skipped")

    writer = LandingWriter(args.landing)
    stats = run_ingest(
        TMDB(tmdb_token), writer,
        omdb=OMDb(omdb_key) if omdb_key else None,
        trakt=Trakt(trakt_id) if trakt_id else None,
        youtube=YouTube(youtube_key) if youtube_key else None,
        region=args.region, max_movies=args.max_movies, max_upcoming=args.max_upcoming,
        review_pages=args.review_pages,
    )
    paths = writer.flush()
    if args.upload_to:
        upload_to_volume(paths, args.landing, args.upload_to)
    logging.info("run %s wrote %d files: %s", writer.run_id, len(paths), stats)
    return stats


if __name__ == "__main__":
    main()
