"""Run the whole CineTrust flow locally (no Databricks): landing -> silver -> trust -> scores.

  python scripts/local_demo.py                     # synthetic demo data with two review farms
  python scripts/local_demo.py --landing data/landing   # files written by jobs/ingest.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from cinetrust.demo import make_demo_envelopes
from cinetrust.evaluation import evaluate
from cinetrust.features import build_features
from cinetrust.landing import read_landing
from cinetrust.local import silver_frames
from cinetrust.rating import compute_consensus
from cinetrust.trust import TrustModel


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--landing", help="Landing directory; omit to use synthetic demo data")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    envelopes = read_landing(args.landing) if args.landing else make_demo_envelopes(args.seed)
    movies, reviews, scores = silver_frames(envelopes)
    if args.landing is None:  # demo farm accounts are known, so the eval can label them
        reviews["is_farm"] = reviews["author_key"].str.contains("bot", regex=False)

    feats = build_features(reviews, scores)
    model = TrustModel(random_state=args.seed).fit(feats)
    pred = model.predict(feats)
    scored = pd.concat([feats, pred], axis=1)
    board = compute_consensus(scored, scores, movies)
    report = evaluate(model.predict, reviews, scores, seed=args.seed)

    if not args.quiet:
        pd.set_option("display.width", 160)
        print(f"\n{len(movies)} movies, {len(reviews)} reviews, {len(scores)} source scores\n")
        print("CineTrust leaderboard")
        print(board[["title", "cinetrust_score", "naive_review_average", "confidence", "controversy",
                     "n_reviews", "n_suspicious_reviews", "farming_alert"]].to_string(index=False))
        if "is_farm" in reviews:
            y = scored["is_farm"]
            print(f"\nBuilt-in demo farms: mean trust {scored.loc[y, 'trust'].mean():.2f} "
                  f"vs organic {scored.loc[~y, 'trust'].mean():.2f}")
        top = scored.sort_values("suspicion", ascending=False).head(5)
        print("\nMost suspicious reviews")
        print(top[["source", "author_key", "rating", "suspicion", "reasons"]].to_string(index=False))
        print("\nRed-team evaluation (synthetic farms injected on top)")
        print(json.dumps(report["metrics"], indent=2))
    return {"board": board, "report": report}


if __name__ == "__main__":
    main()
