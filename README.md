# CineTrust 🎬

**[Live demo →](https://theoriginalsam.github.io/cinetrust/)** · refreshed daily from the Databricks pipeline

![ci](https://github.com/theoriginalsam/cinetrust/actions/workflows/ci.yml/badge.svg) ![pages](https://github.com/theoriginalsam/cinetrust/actions/workflows/pages.yml/badge.svg)

**Farm-resistant movie ratings for films in theatres right now, built on Databricks.**

Single-platform ratings are easy to game: review bombs sink good films, paid campaigns inflate
weak ones, and whoever controls the platform controls the number. CineTrust pulls reviews and
scores from several independent sources, scores **every individual review for signs of farming**,
and combines everything into one rating that no single source or campaign can move much.

```
 TMDB now playing ─┐
 TMDB reviews ─────┤                    ┌──────────────── Databricks (serverless) ────────────────┐
 Trakt reviews ────┼─► landing volume ─►│ bronze ─► silver ─► gold ─► trust model ─► consensus    │
 OMDb (IMDb, RT,   │    (JSONL, UC)     │ Auto     expectations,      MLflow + UC    score +      │
  Metacritic) ─────┘                    │ Loader   SCD1 upserts       registry      farm alerts   │
                                        └──────────────────────────────────────────────────────────┘
```

## What makes it different

| Problem | CineTrust's answer |
|---|---|
| One platform dominates the score | **Diversity cap**: with 3+ sources, no source can exceed 35% of the final score |
| Copy-paste / templated farm reviews | **MinHash + LSH** near-duplicate detection on word shingles |
| Throwaway accounts mass-posting | Per-account 24h burst counts, account age, rating variance |
| Coordinated review bombing | Poisson burst z-score per movie, combined with rating extremity |
| "10/10" on text that reads like a pan | Rating vs. text-sentiment mismatch |
| 3 glowing reviews beating 3,000 mixed ones | **Bayesian shrinkage** toward the catalogue prior |
| Black-box moderation | Every down-weighted review carries reasons (`near_duplicate_text,coordinated_wave`) |

The trust model is unsupervised, because there are no labelled farm datasets. It combines an
**Isolation Forest** over 11 behavioural and text features with explainable rule signals (noisy-OR).
It's tracked in **MLflow**, registered in **Unity Catalog**, and promoted with a champion/challenger
alias only if it beats the current champion on the red-team eval.

## Results (red-team evaluation)

Since real farm labels don't exist, the evaluation attacks the system: it injects templated
*and* paraphrased bomb/boost campaigns into the most-reviewed movies, then measures detection
and how far each attack moves the score.

| Metric | Value |
|---|---|
| Detection ROC-AUC | **0.9999** |
| Farm recall (trust < 0.5) | **99.3%** |
| Organic false-positive rate | **0.5%** |
| Score shift from attack: naive review average | 19.1 pts |
| Score shift: multi-source consensus, no trust weights | 2.9 pts |
| Score shift: **full CineTrust** | **0.8 pts (96% less than naive)** |

> ⚠️ These numbers come from the synthetic demo dataset (`python scripts/local_demo.py`).
> Re-run `cinetrust-train` on real ingested data and report those numbers instead. On real data,
> any existing farms are counted as "organic", so detection numbers come out conservative.

In the demo, a review bomb drags *Glass Orchard*'s plain average down to **55**. CineTrust still
rates it **84**, close to its critics' consensus, and raises a `farming_alert`.

## Databricks features used

- **Unity Catalog**: schema, managed volume, tables, model registry with `@champion` alias
- **Auto Loader** (`cloudFiles`) incremental ingestion from a UC volume
- **Lakeflow Declarative Pipelines (DLT)**: medallion architecture, `@dlt.expect_or_drop`
  data-quality rules, `apply_changes` SCD type 1 upserts, materialized gold views
- **Serverless jobs and Workflows**: ingest → pipeline refresh → scoring DAG, weekly retrain
- **MLflow 3**: experiment tracking, pyfunc model with bundled code, signature, registry
- **Databricks Asset Bundles**: everything above is code (`databricks.yml`, `resources/`)
- **GitHub Actions**: lint + tests + local end-to-end demo on every PR; bundle deploy on `main`

## Repository layout

```
databricks.yml             bundle: variables + dev/prod targets
resources/                 schema + volume, DLT pipeline, jobs (daily scoring, weekly training)
pipelines/cinetrust_dlt.py bronze / silver / gold
jobs/                      ingest.py, train_trust.py, score.py (serverless Python tasks)
src/cinetrust/
  sources/                 TMDB, OMDb, Trakt clients (rate-limited, retrying)
  landing.py, ingest.py    API -> JSONL envelopes (atomic writes)
  normalize.py             raw -> unified silver schema (shared by DLT, demo and tests)
  dedup.py                 MinHash + LSH near-duplicate detection
  features.py              anti-farming features
  trust.py                 Isolation Forest + rule signals -> trust weight + reasons
  rating.py                trust-weighted, shrunk, diversity-capped consensus score
  evaluation.py            red-team farm injection + metrics
  demo.py                  synthetic, API-shaped demo data (fictional movies)
scripts/local_demo.py      the whole flow locally, no Databricks needed
app/                       Databricks App: FastAPI (main.py) + custom frontend (static/)
tests/                     33 unit tests
```

## Run it locally (2 minutes)

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run python scripts/local_demo.py
```

## Deploy to Databricks

1. **Get free API keys**: [TMDB](https://www.themoviedb.org/settings/api) (required),
   [OMDb](https://www.omdbapi.com/apikey.aspx) and [Trakt](https://trakt.tv/oauth/applications)
   (optional, but needed for multi-source scores).
2. **Workspace**: [Databricks Free Edition](https://www.databricks.com/learn/free-edition) works.
   Install the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html), then
   `databricks auth login`.
3. **Store keys as secrets**:
   ```bash
   databricks secrets create-scope cinetrust
   databricks secrets put-secret cinetrust tmdb_token
   databricks secrets put-secret cinetrust omdb_key
   databricks secrets put-secret cinetrust trakt_client_id
   ```
4. **Deploy and run**:
   ```bash
   databricks bundle deploy
   databricks bundle run cinetrust_daily     # ingest -> pipeline; the score task needs a model
   databricks bundle run cinetrust_train     # train + register champion
   databricks bundle run cinetrust_daily     # now scoring succeeds
   ```
   Unpause the schedules in the Jobs UI when you're happy with it.

**If serverless can't reach the APIs** (Free Edition restricts outbound internet), ingest from
your laptop and upload to the volume. The pipeline doesn't care where files come from:
```bash
TMDB_TOKEN=... OMDB_API_KEY=... TRAKT_CLIENT_ID=... \
  uv run python jobs/ingest.py --landing data/landing --upload-to /Volumes/workspace/cinetrust/landing
```

## The app

A **Databricks App** (`app.yaml`, `resources/app.yml`) serving a FastAPI JSON API and a custom
movie-site frontend, reading the gold tables through the SQL warehouse as its own service principal:

- **In theatres**: rotating backdrop hero, poster grid with CineTrust score rings, farm alerts
- **Coming soon**: upcoming releases ranked by *hype* (trust-weighted trailer reactions, paid hype filtered out)
- **Every movie page**: embedded trailer, how each source was weighted, the good/mixed/bad split,
  and every review, filterable by source and by good/bad/down-weighted and sortable
  (most positive, most negative, newest, most trusted, most liked)

```bash
databricks bundle deploy && databricks bundle run cinetrust_app
# one-time: let the app's service principal read the tables
#   GRANT USE CATALOG ON CATALOG workspace TO `<app-client-id>`;
#   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.cinetrust TO `<app-client-id>`;
CINETRUST_DEMO=1 python app/main.py          # local, synthetic data -> http://localhost:8000
python app/main.py                           # local, real data via your CLI login
```

## Gold tables

| Table | Contents |
|---|---|
| `gold_movie_scores` | Leaderboard: `cinetrust_score`, `confidence`, `controversy`, `farming_alert`, per-source `breakdown` |
| `gold_movie_scores_history` | Snapshot per run, for trend charts |
| `gold_review_trust` | Every review with `trust`, `suspicion`, `reasons` |
| `gold_review_activity` | Daily review volume per movie and source |
| `gold_now_playing` | Movies currently in theatres |
| `gold_upcoming` / `gold_upcoming_hype` | Upcoming releases and their pre-release hype |

## Limitations and next steps

- Lexicon sentiment by default; set `CINETRUST_SENTIMENT=hf` to use a DistilBERT classifier
  (add `transformers` and `torch` to the job environment).
- Rotten Tomatoes via OMDb is the Tomatometer (% positive critics), not an average rating.
- Next: a public read-only site for the leaderboard, an AI/BI dashboard on the gold tables, a Model Serving endpoint for real-time trust
  scoring, and more sources (YouTube trailer comments, Reddit discussion threads, subject to
  their API terms).

## Data and terms

Only official APIs are used; no sites are scraped. This product uses the TMDB API but is not
endorsed or certified by TMDB. Respect each provider's attribution and rate-limit terms.
