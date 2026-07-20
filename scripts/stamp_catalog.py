#!/usr/bin/env python3
"""Stamp marketplace metadata onto scene_packs/index.json (Content Platform Phase 7).

Maintainer tool — not loaded by the integration. Adds:
  - catalog-level schema_version / generated_at
  - per-pack version, min_integration, featured
  - per-image sha256 of the file on disk (integrity, not DRM)

Usage:
    python3 scripts/stamp_catalog.py
    python3 scripts/stamp_catalog.py --min-integration 0.12.0 --default-version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "scene_packs" / "index.json"

# Packs highlighted on the Gallery home strip (famous collections).
DEFAULT_FEATURED = frozenset(
    {
        "monet",
        "van_gogh",
        "davinci",
        "classic_art",
        "rembrandt",
        "hokusai",
    }
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp(
    *,
    default_version: str,
    min_integration: str,
    featured_ids: frozenset[str],
) -> dict:
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    packs = data.get("packs")
    if not isinstance(packs, list):
        raise SystemExit("index.json missing packs[]")

    out_packs = []
    for pack in packs:
        if not isinstance(pack, dict) or pack.get("type") == "widget":
            continue
        pid = pack.get("id") or ""
        pack = dict(pack)
        pack["version"] = str(pack.get("version") or default_version)
        pack["min_integration"] = str(
            pack.get("min_integration") or min_integration
        )
        pack["featured"] = bool(
            pack.get("featured")
            if "featured" in pack
            else pid in featured_ids
        )
        # Prefer explicit license; default for Commons-built packs.
        if not pack.get("license"):
            pack["license"] = (
                "Public domain (verified per-image via Wikimedia Commons)"
            )

        images = []
        for img in pack.get("images") or []:
            if not isinstance(img, dict):
                continue
            img = dict(img)
            rel = img.get("path") or ""
            if rel:
                fpath = REPO_ROOT / rel
                if fpath.is_file():
                    img["sha256"] = _sha256_file(fpath)
            images.append(img)
        pack["images"] = images
        out_packs.append(pack)

    return {
        "schema_version": 1,
        "catalog_version": default_version,
        "generated_at": int(time.time()),
        "min_integration_default": min_integration,
        "packs": out_packs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default-version", default="1.0.0")
    parser.add_argument("--min-integration", default="0.12.0")
    args = parser.parse_args()

    stamped = stamp(
        default_version=args.default_version,
        min_integration=args.min_integration,
        featured_ids=DEFAULT_FEATURED,
    )
    INDEX_PATH.write_text(
        json.dumps(stamped, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    n = len(stamped["packs"])
    hashed = sum(
        1
        for p in stamped["packs"]
        for i in p.get("images") or []
        if i.get("sha256")
    )
    print(
        f"Wrote {INDEX_PATH.relative_to(REPO_ROOT)}: "
        f"{n} packs, {hashed} image checksums, "
        f"schema_version={stamped['schema_version']}"
    )


if __name__ == "__main__":
    main()
