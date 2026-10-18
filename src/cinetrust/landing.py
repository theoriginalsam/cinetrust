"""Landing zone writer: every API response becomes one JSON envelope line.

Layout: <root>/<source>/date=YYYY-MM-DD/<run_id>.jsonl
Files are written under a `_tmp_` name and renamed, so Auto Loader (which skips files starting
with `_` or `.`) never sees a half-written file.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_envelope(source: str, kind: str, imdb_id: str | None, payload: dict, *,
                  run_id: str, fetched_at: str | None = None) -> dict:
    return {
        "source": source,
        "kind": kind,
        "imdb_id": imdb_id,
        "fetched_at": fetched_at or utc_now_iso(),
        "run_id": run_id,
        "payload": payload,
    }


class LandingWriter:
    def __init__(self, root: str | os.PathLike, run_id: str | None = None):
        self.root = Path(root)
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self._buffers: dict[str, list[dict]] = defaultdict(list)

    def emit(self, source: str, kind: str, imdb_id: str | None, payload: dict) -> None:
        self._buffers[source].append(make_envelope(source, kind, imdb_id, payload, run_id=self.run_id))

    def flush(self) -> list[Path]:
        written = []
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for source, envelopes in self._buffers.items():
            if not envelopes:
                continue
            folder = self.root / source / f"date={day}"
            folder.mkdir(parents=True, exist_ok=True)
            final = folder / f"{self.run_id}.jsonl"
            tmp = folder / f"_tmp_{self.run_id}.jsonl"
            with tmp.open("w", encoding="utf-8") as fh:
                for env in envelopes:
                    fh.write(json.dumps(env, ensure_ascii=False) + "\n")
            os.replace(tmp, final)
            written.append(final)
        self._buffers.clear()
        return written


def read_landing(root: str | os.PathLike) -> list[dict]:
    """Load every envelope under a landing directory (local stand-in for Auto Loader)."""
    envelopes = []
    for path in sorted(Path(root).rglob("*.jsonl")):
        if path.name.startswith(("_", ".")):
            continue
        with path.open(encoding="utf-8") as fh:
            envelopes.extend(json.loads(line) for line in fh if line.strip())
    return envelopes


def upload_to_volume(paths: list[Path], local_root: str | os.PathLike, volume_root: str) -> None:
    """Copy locally written landing files into a Unity Catalog volume (when ingesting off-cluster)."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    local_root = Path(local_root)
    for path in paths:
        target = f"{volume_root.rstrip('/')}/{path.relative_to(local_root).as_posix()}"
        with path.open("rb") as fh:
            w.files.upload(target, fh, overwrite=True)
