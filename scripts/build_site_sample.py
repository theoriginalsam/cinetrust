"""Write site/leaderboard.sample.json from the synthetic demo data, so the site works offline.

  python scripts/build_site_sample.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from cinetrust.demo import make_demo_envelopes
from cinetrust.features import build_features
from cinetrust.local import silver_frames
from cinetrust.rating import compute_consensus
from cinetrust.site_export import build_leaderboard
from cinetrust.trust import TrustModel


def main(out: Path = ROOT / "site" / "leaderboard.sample.json", seed: int = 7) -> dict:
    movies, reviews, scores = silver_frames(make_demo_envelopes(seed))
    feats = build_features(reviews, scores)
    scored = pd.concat([feats, TrustModel(random_state=seed).fit(feats).predict(feats)], axis=1)
    board = compute_consensus(scored, scores, movies)
    doc = build_leaderboard(board, movies, scored, demo=True,
                            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote {out.relative_to(ROOT)}: {len(doc['movies'])} movies")
    return doc


if __name__ == "__main__":
    main()
