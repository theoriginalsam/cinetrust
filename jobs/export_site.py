"""Export the public leaderboard.json for the static CineTrust site (site/).

Reads gold_movie_scores (+ posters from gold_now_playing) and the down-weighted reviews from
gold_review_trust joined to silver_reviews, then writes one JSON file to a UC volume. No author
names are exported; review text is truncated.
"""

import argparse
import json
import sys
from pathlib import Path


def _default_src() -> str:
    try:
        return str(Path(__file__).resolve().parents[1] / "src")
    except NameError:
        return "src"


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default=_default_src())
    p.add_argument("--catalog", default="workspace")
    p.add_argument("--schema", default="cinetrust")
    p.add_argument("--out", help="Output file; default /Volumes/<catalog>/<schema>/site/leaderboard.json")
    args = p.parse_args(argv)
    sys.path.insert(0, args.src)

    from cinetrust.platform import fq, get_spark
    from cinetrust.site_export import SUSPICIOUS_TRUST, build_leaderboard

    spark = get_spark()
    def t(name):
        return fq(args.catalog, args.schema, name)
    scores = spark.table(t("gold_movie_scores")).toPandas()
    movies = spark.sql(f"SELECT imdb_id, poster_path, release_date FROM {t('gold_now_playing')}").toPandas()
    reviews = spark.sql(f"""
        SELECT t.imdb_id, t.source, t.rating, t.trust, t.reasons, r.created_at, r.text
        FROM {t('gold_review_trust')} t JOIN {t('silver_reviews')} r USING (review_id)
        WHERE t.trust < {SUSPICIOUS_TRUST}""").toPandas()

    doc = build_leaderboard(scores, movies, reviews)
    out = Path(args.out or f"/Volumes/{args.catalog}/{args.schema}/site/leaderboard.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    n_flagged = sum(len(m["flagged_reviews"]) for m in doc["movies"])
    print(f"Wrote {out}: {len(doc['movies'])} movies, {n_flagged} flagged reviews")


if __name__ == "__main__":
    main()
