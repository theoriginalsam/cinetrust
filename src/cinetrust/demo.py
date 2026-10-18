"""Synthetic but API-shaped data: organic reviews plus review farms, for demos, tests and evals.

Titles and ids are fictional (tt90000xx) so demo output is never mistaken for real ratings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from .landing import make_envelope

# Organic reviews are generated from a slot grammar so no two read alike (like real reviews).
SUBJECTS = ["the lead", "the script", "the score", "the third act", "the villain", "the editing",
            "the dialogue", "the cinematography", "the cast", "the pacing", "the ending",
            "the soundtrack", "the action", "the humour", "the world-building", "the director"]
POS_ADJ = ["superb", "gorgeous", "gripping", "brilliant", "wonderful", "stunning", "clever",
           "memorable", "impressive", "touching", "excellent", "thrilling", "charming", "powerful"]
NEG_ADJ = ["dull", "messy", "predictable", "lazy", "tedious", "flat", "bland", "weak",
           "confusing", "forgettable", "painful", "bloated", "slow", "disappointing"]
OPENERS = ["Honestly,", "For me,", "Surprisingly,", "As a longtime fan,", "On a big screen,",
           "Compared to the trailer,", "Without spoilers,", "In my opinion,", "Overall,", "Weirdly,"]
TAILS = ["and I did not expect that", "which carried the whole film", "more than I expected",
         "especially in the second half", "even on a rewatch", "from the very first scene",
         "and my partner agreed", "for a {n}-minute runtime", "in a crowded {d} showing",
         "despite the hype", "compared to last year's films", "and it stuck with me"]
DAYS = ["Friday night", "Sunday matinee", "Tuesday", "late", "packed", "half-empty", "IMAX"]
POS_FRAMES = ["{o} {s} was {a} {t}.", "I loved {s}, {a} {t}.", "{s} felt {a} and {a2} {t}.",
              "Really {a} work on {s} {t}.", "{o} I would recommend it, {s} is {a}."]
NEG_FRAMES = ["{o} {s} was {a} {t}.", "I hated {s}, {a} {t}.", "{s} felt {a} and {a2} {t}.",
              "Really {a} work on {s} {t}.", "{o} not worth it, {s} is {a}."]
BOMB_TEMPLATE = (
    "Worst movie of the year and a total waste of money. The {a} was {b} and the plot made no "
    "sense at all. Everyone involved should be embarrassed. Save your money and do not watch "
    "this garbage in theatres, wait for it to hit streaming if you must."
)
BOMB_WORDS = ["terrible", "awful", "boring", "painful", "lazy", "pointless"]
BOOST_TEMPLATE = (
    "Absolute masterpiece, the best movie of the decade. The {a} was {b} and I was crying by the "
    "end. Everyone needs to see this in theatres right now, go buy your tickets today, you will "
    "not regret it, ten out of ten from me."
)
BOOST_WORDS = ["perfect", "amazing", "brilliant", "incredible", "stunning", "superb"]

DEMO_MOVIES = [
    ("tt9000001", 1001, "The Lantern Keeper", 82),
    ("tt9000002", 1002, "Orbit of Ashes", 64),
    ("tt9000003", 1003, "Paper Tigers", 46),
    ("tt9000004", 1004, "Midnight Ferry", 71),
    ("tt9000005", 1005, "Glass Orchard", 88),
]


def _sentence(positive: bool, rng: np.random.Generator) -> str:
    adj = POS_ADJ if positive else NEG_ADJ
    a, a2 = rng.choice(adj, size=2, replace=False)
    tail = str(rng.choice(TAILS)).format(n=int(rng.integers(95, 170)), d=rng.choice(DAYS))
    frame = str(rng.choice(POS_FRAMES if positive else NEG_FRAMES))
    text = frame.format(o=rng.choice(OPENERS), s=rng.choice(SUBJECTS), a=a, a2=a2, t=tail)
    return text[0].upper() + text[1:]


def organic_text(rating: float, rng: np.random.Generator) -> str:
    p_positive = float(np.clip((rating - 1) / 9, 0.05, 0.95))
    k = int(rng.integers(2, 5))
    return " ".join(_sentence(rng.random() < p_positive, rng) for _ in range(k))


def farm_text(kind: str, style: str, rng: np.random.Generator) -> str:
    if style == "template":
        template, words = (BOMB_TEMPLATE, BOMB_WORDS) if kind == "bomb" else (BOOST_TEMPLATE, BOOST_WORDS)
        return template.format(a=rng.choice(SUBJECTS)[4:], b=rng.choice(words))
    # "paraphrase": LLM-style varied text; dedup can't catch it, behaviour signals must.
    return organic_text(1.0 if kind == "bomb" else 10.0, rng)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def make_demo_envelopes(seed: int = 7, *, now: datetime | None = None, farms: bool = True) -> list[dict]:
    rng = np.random.default_rng(seed)
    now = now or datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    fetched = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = "demo"
    envs: list[dict] = []
    author_pool = [f"moviefan{i:03d}" for i in range(250)]

    def emit(source, kind, imdb_id, payload):
        envs.append(make_envelope(source, kind, imdb_id, payload, run_id=run_id, fetched_at=fetched))

    for imdb_id, tmdb_id, title, quality in DEMO_MOVIES:
        def noise(s=4.0):
            return float(rng.normal(0, s))
        emit("tmdb", "movie", imdb_id, {
            "id": tmdb_id, "imdb_id": imdb_id, "title": title, "release_date": "2026-10-03",
            "original_language": "en", "popularity": round(float(rng.uniform(40, 400)), 1),
            "vote_average": round(np.clip(quality + noise(), 0, 100) / 10, 1),
            "vote_count": int(rng.integers(300, 6000)), "poster_path": None, "region": "US",
            "now_playing": True,
        })
        emit("omdb", "ratings", imdb_id, {
            "Title": title, "imdbID": imdb_id, "Response": "True",
            "imdbRating": f"{np.clip(quality + noise(), 10, 99) / 10:.1f}",
            "imdbVotes": f"{int(rng.integers(2000, 90000)):,}",
            "Ratings": [
                {"Source": "Internet Movie Database", "Value": f"{np.clip(quality + noise(), 10, 99) / 10:.1f}/10"},
                {"Source": "Rotten Tomatoes", "Value": f"{int(np.clip(quality + noise(8), 0, 100))}%"},
                {"Source": "Metacritic", "Value": f"{int(np.clip(quality + noise(6), 0, 100))}/100"},
            ],
        })
        for source in ("tmdb", "trakt"):
            for i in range(int(rng.integers(14, 26))):
                rating = float(np.clip(round(rng.normal(quality / 10, 1.6)), 1, 10))
                created = now - timedelta(hours=float(rng.uniform(1, 13 * 24)))
                author = str(rng.choice(author_pool))
                text = organic_text(rating, rng)
                if source == "tmdb":
                    emit("tmdb", "review", imdb_id, {
                        "id": f"r{tmdb_id}{i:03d}", "author": author, "content": text,
                        "author_details": {"username": author, "rating": rating},
                        "created_at": _iso(created), "url": f"https://example.org/review/{tmdb_id}/{i}",
                    })
                else:
                    joined = created - timedelta(days=float(rng.uniform(60, 3000)))
                    emit("trakt", "comment", imdb_id, {
                        "id": int(tmdb_id * 1000 + i), "comment": text, "spoiler": False,
                        "review": len(text.split()) > 200, "likes": int(rng.poisson(3)),
                        "created_at": _iso(created),
                        "user_stats": {"rating": int(rating)},
                        "user": {"username": author, "ids": {"slug": author}, "joined_at": _iso(joined)},
                    })

    if farms:
        # Review bomb on the best film: templated 1/10s from throwaway Trakt accounts within 90 min.
        envs += farm_envelopes("tt9000005", 1005, "bomb", "template", n=28, start=now - timedelta(hours=30),
                               rng=rng, run_id=run_id, fetched_at=fetched)
        # Paid boost on the weakest film: varied 10/10 text, so only behaviour gives it away.
        envs += farm_envelopes("tt9000003", 1003, "boost", "paraphrase", n=18, start=now - timedelta(hours=50),
                               rng=rng, run_id=run_id, fetched_at=fetched)
    return envs


def farm_envelopes(imdb_id: str, tmdb_id: int, kind: str, style: str, *, n: int, start: datetime,
                   rng: np.random.Generator, run_id: str = "farm", fetched_at: str | None = None,
                   window_minutes: float = 90, accounts: int | None = None) -> list[dict]:
    rating = 1 if kind == "bomb" else 10
    accounts = accounts or max(3, n // 4)  # a few accounts posting several times each
    out = []
    for i in range(n):
        created = start + timedelta(minutes=float(rng.uniform(0, window_minutes)))
        user = f"{kind}bot{tmdb_id}_{i % accounts}"
        out.append(make_envelope("trakt", "comment", imdb_id, {
            "id": int(9_000_000 + tmdb_id * 100 + i), "comment": farm_text(kind, style, rng),
            "spoiler": False, "review": False, "likes": 0, "created_at": _iso(created),
            "user_stats": {"rating": rating},
            "user": {"username": user, "ids": {"slug": user},
                     "joined_at": _iso(created - timedelta(hours=float(rng.uniform(1, 48))))},
        }, run_id=run_id, fetched_at=fetched_at))
    return out
