"""Near-duplicate review detection with MinHash + LSH banding (no Spark MLlib needed on serverless).

Review farms reuse templates with a few words swapped; exact-match dedup misses them,
word-shingle Jaccard similarity catches them.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

_TOKEN = re.compile(r"[a-z0-9']+")
_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)


def shingles(text: str, k: int = 3) -> set[str]:
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < k:
        return set()
    return {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


class MinHasher:
    def __init__(self, num_perm: int = 64, seed: int = 13):
        rng = np.random.default_rng(seed)
        self.a = rng.integers(1, 2**63, size=num_perm, dtype=np.uint64) | np.uint64(1)
        self.b = rng.integers(0, 2**63, size=num_perm, dtype=np.uint64)
        self.num_perm = num_perm

    def signature(self, shingle_set: set[str]) -> np.ndarray | None:
        if not shingle_set:
            return None
        x = np.fromiter((_hash64(s) for s in shingle_set), dtype=np.uint64)
        with np.errstate(over="ignore"):  # multiply-shift hashing wraps mod 2^64 by design
            hashed = (x[:, None] * self.a[None, :] + self.b[None, :]) & _MASK
        return hashed.min(axis=0)


def near_duplicate_cluster_sizes(texts: list[str], *, threshold: float = 0.5, bands: int = 16,
                                 k: int = 3, num_perm: int = 64) -> np.ndarray:
    """For each text: 1 + the number of other texts that are near-duplicates of it (1 = unique).

    Counts direct neighbours instead of connected components, so a chain of loosely similar
    organic reviews (A~B, B~C, ...) can't snowball into one giant "farm" cluster.
    """
    n = len(texts)
    rows = num_perm // bands
    hasher = MinHasher(num_perm)
    sigs = [hasher.signature(shingles(t or "", k)) for t in texts]
    sizes = np.ones(n, dtype=int)

    buckets: dict[tuple, list[int]] = {}
    for i, sig in enumerate(sigs):
        if sig is None:
            continue
        for band in range(bands):
            key = (band, sig[band * rows:(band + 1) * rows].tobytes())
            buckets.setdefault(key, []).append(i)

    checked = set()
    for members in buckets.values():
        for idx, i in enumerate(members):
            for j in members[idx + 1:]:
                if (i, j) in checked:
                    continue
                checked.add((i, j))
                if np.mean(sigs[i] == sigs[j]) >= threshold:
                    sizes[i] += 1
                    sizes[j] += 1
    return sizes
