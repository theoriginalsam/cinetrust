# CineTrust medallion pipeline (Lakeflow Declarative Pipelines / DLT, serverless).
#
#   landing volume (JSONL envelopes)
#     -> bronze_envelopes          raw, append-only, exactly what each API returned
#     -> silver_movies / silver_reviews / silver_source_scores
#                                  unified schema, data-quality expectations, SCD1 upserts
#     -> gold_now_playing / gold_review_activity
#                                  what the scoring job and dashboard read
#
# Normalisation logic lives in src/cinetrust/normalize.py so the local demo, unit tests and
# this pipeline share one definition.

import sys

import dlt
import pandas as pd
from pyspark.sql import functions as F

sys.path.insert(0, spark.conf.get("cinetrust.src_path"))  # noqa: F821 (spark is injected)
from cinetrust import normalize as N

try:  # Ship normalize's functions to workers by value, so workers don't need the source path.
    from pyspark import cloudpickle

    cloudpickle.register_pickle_by_value(N)
except Exception:
    pass

LANDING = spark.conf.get("cinetrust.landing_path")  # noqa: F821
ENVELOPE_SCHEMA = "source STRING, kind STRING, imdb_id STRING, fetched_at STRING, run_id STRING"


# ---------- bronze ----------

@dlt.table(
    name="bronze_envelopes",
    comment="Raw API envelopes from the landing volume, one row per fetched object.",
    table_properties={"quality": "bronze"},
)
def bronze_envelopes():
    raw = (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "text")
        .option("pathGlobFilter", "*.jsonl")
        .load(LANDING)
    )
    return raw.select(
        F.from_json("value", ENVELOPE_SCHEMA).alias("e"),
        F.get_json_object("value", "$.payload").alias("payload"),
        F.col("_metadata.file_path").alias("source_file"),
        F.current_timestamp().alias("ingested_at"),
    ).select("e.*", "payload", "source_file", "ingested_at")


# ---------- silver ----------

def _normalized(kinds: list[str], row_fn, schema: str):
    cols, decode = N.columns(schema), N.envelope_from_row

    def mapper(batches):
        for pdf in batches:
            rows = []
            for rec in pdf.to_dict("records"):
                rows.extend(row_fn(decode(rec)))
            yield pd.DataFrame(rows, columns=cols)

    return (
        dlt.read_stream("bronze_envelopes")
        .where(F.col("kind").isin(kinds))
        .select("source", "kind", "imdb_id", "fetched_at", "run_id", "payload")
        .mapInPandas(mapper, schema)
        .withColumn("fetched_at", F.to_timestamp("fetched_at"))
    )


@dlt.view(name="movies_normalized")
@dlt.expect_or_drop("has_imdb_id", "imdb_id IS NOT NULL")
@dlt.expect("has_title", "title IS NOT NULL")
def movies_normalized():
    return _normalized(["movie"], N.movie_rows, N.MOVIE_SCHEMA)


@dlt.view(name="reviews_normalized")
@dlt.expect_or_drop("has_imdb_id", "imdb_id IS NOT NULL")
@dlt.expect_or_drop("has_text", "length(text) > 0")
@dlt.expect_or_drop("has_created_at", "created_at IS NOT NULL")
@dlt.expect("rating_in_range", "rating IS NULL OR rating BETWEEN 0 AND 10")
def reviews_normalized():
    return (
        _normalized(["review", "comment"], N.review_rows, N.REVIEW_SCHEMA)
        .withColumn("created_at", F.to_timestamp("created_at"))
        .withColumn("author_joined_at", F.to_timestamp("author_joined_at"))
    )


@dlt.view(name="scores_normalized")
@dlt.expect_or_drop("score_in_range", "score BETWEEN 0 AND 100")
def scores_normalized():
    return _normalized(["movie", "ratings"], N.score_rows, N.SCORE_SCHEMA)


# Every ingest re-fetches all reviews, so silver is an upsert (SCD type 1) on the natural key.
for target, source, keys, comment in [
    ("silver_movies", "movies_normalized", ["imdb_id"], "Latest metadata per movie."),
    ("silver_reviews", "reviews_normalized", ["review_id"], "One row per review across all sources."),
    ("silver_source_scores", "scores_normalized", ["imdb_id", "source"],
     "Latest 0-100 score per movie per aggregate source."),
]:
    dlt.create_streaming_table(target, comment=comment, table_properties={"quality": "silver"})
    dlt.apply_changes(target=target, source=source, keys=keys,
                      sequence_by=F.col("fetched_at"), stored_as_scd_type=1)


# ---------- gold ----------

@dlt.table(name="gold_now_playing", comment="Movies seen in TMDB now-playing in the last 3 days.",
           table_properties={"quality": "gold"})
def gold_now_playing():
    return _recent_movies().where(F.coalesce("list_type", F.lit("now_playing")) == "now_playing")


@dlt.table(name="gold_upcoming", comment="Movies in TMDB upcoming that haven't been released yet.",
           table_properties={"quality": "gold"})
def gold_upcoming():
    return (_recent_movies()
            .where((F.col("list_type") == "upcoming") & (F.to_date("release_date") > F.current_date())))


MOVIE_COLUMNS = ["imdb_id", "tmdb_id", "title", "release_date", "region", "popularity", "poster_path",
                 "backdrop_path", "overview", "genres", "runtime", "trailer_key", "fetched_at"]


def _recent_movies():
    return (dlt.read("silver_movies")
            .where(F.col("fetched_at") >= F.current_timestamp() - F.expr("INTERVAL 3 DAYS"))
            .select(*MOVIE_COLUMNS, "list_type"))


@dlt.table(name="gold_review_activity",
           comment="Daily review volume and average rating per movie and source (dashboard).",
           table_properties={"quality": "gold"})
def gold_review_activity():
    return (
        dlt.read("silver_reviews")
        .groupBy("imdb_id", "source", F.to_date("created_at").alias("review_date"))
        .agg(
            F.count("*").alias("reviews"),
            F.round(F.avg("rating"), 2).alias("avg_rating"),
            F.countDistinct("author_key").alias("distinct_authors"),
        )
    )
