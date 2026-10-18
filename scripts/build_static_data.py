"""Write synthetic demo data for the static site (used when no Databricks token is configured).

  python scripts/build_static_data.py _site/data
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "app")]

from cinetrust.webview import write_static  # noqa: E402
from data import REVIEW_COLUMNS, Demo  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/data")
    demo = Demo()
    reviews = demo._reviews[["imdb_id", *REVIEW_COLUMNS]]
    home = write_static(out, demo.now_playing(), demo.upcoming(), reviews, demo=True)
    print(f"Wrote demo data to {out}: {len(home['now_playing'])} movies")
