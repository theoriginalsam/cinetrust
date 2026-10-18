"""Score every review with the champion trust model, then publish CineTrust ratings.

Writes:
  gold_review_trust            per-review trust weight + human-readable reasons
  gold_movie_scores            current leaderboard for movies in theatres
  gold_movie_scores_history    append-only snapshots (score trends, monitoring)
  gold_upcoming_hype           pre-release hype for upcoming movies (trailer comments)
"""

import argparse
import sys
from datetime import datetime, timezone
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
    p.add_argument("--model-name", default="trust_model")
    args = p.parse_args(argv)
    sys.path.insert(0, args.src)

    import mlflow
    import pandas as pd

    from cinetrust.features import MODEL_FEATURES, build_features
    from cinetrust.platform import fq, get_spark, write_table
    from cinetrust.rating import compute_consensus, compute_hype

    spark = get_spark()
    def t(name):
        return fq(args.catalog, args.schema, name)
    reviews = spark.table(t("silver_reviews")).toPandas()
    scores = spark.table(t("silver_source_scores")).toPandas()
    movies = spark.table(t("gold_now_playing")).toPandas()
    upcoming = spark.table(t("gold_upcoming")).toPandas()

    mlflow.set_registry_uri("databricks-uc")
    model_uri = f"models:/{args.catalog}.{args.schema}.{args.model_name}@champion"
    try:
        model = mlflow.pyfunc.load_model(model_uri)
    except Exception as exc:
        raise SystemExit(f"No champion model at {model_uri}; run the cinetrust-train job first.") from exc

    feats = build_features(reviews, scores)
    pred = model.predict(feats[MODEL_FEATURES]).reset_index(drop=True)
    scored = pd.concat([feats.reset_index(drop=True), pred], axis=1)
    now = datetime.now(timezone.utc)

    review_cols = ["review_id", "source", "imdb_id", "author_key", "rating", "sentiment", "created_at",
                   "dup_cluster_size", "author_burst_24h", "movie_burst_z", "suspicion", "trust", "reasons"]
    write_table(spark, scored[review_cols].assign(scored_at=now), t("gold_review_trust"))

    board = compute_consensus(scored, scores, movies).assign(computed_at=now)
    write_table(spark, board, t("gold_movie_scores"))
    write_table(spark, board, t("gold_movie_scores_history"), mode="append")

    hype = compute_hype(scored, upcoming, now=pd.Timestamp(now))
    hype = upcoming[["imdb_id", "title", "release_date"]].merge(hype, on="imdb_id").assign(computed_at=now)
    if not hype.empty:  # an empty frame has no schema to create the table from
        write_table(spark, hype, t("gold_upcoming_hype"))
    print(board[["title", "cinetrust_score", "naive_review_average", "farming_alert"]].head(20).to_string())


if __name__ == "__main__":
    main()
