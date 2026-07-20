# Contributing to the Digital Frames content catalog

This repository supplies **Gallery art packs** (and first-party Live renderer
sources) for [ha-digital-frames](https://github.com/dsackr/ha-digital-frames).

**Images and JSON only for community PRs.** Do not contribute remote-exec
Python “widgets” or installable scripts. Generators ship first-party via the
integration’s pinned Live skills.

See [docs/CATALOG_SCHEMA.md](docs/CATALOG_SCHEMA.md) for the index format
(version, `min_integration`, `sha256`, `featured`).

---

## Licensing (critical)

All images **must** be free to redistribute:

1. **Public domain** (preferred) — e.g. artists deceased 70+ years; US government works (NASA, etc.).
2. **Open licenses** (CC0 / CC-BY / CC-BY-SA) with verifiable attribution.
3. **No** modern copyrighted photos, film stills, or proprietary art.

`scripts/build_scene_pack.py` only keeps Wikimedia Commons files whose
metadata explicitly says public domain (plus artist checks where configured).

---

## Adding an art pack

### 1. Define the pack

Edit `PACKS` in `scripts/build_scene_pack.py`:

```python
    {
        "id": "my_new_pack",
        "name": "My New Pack Name",
        "description": "A brief description of what this pack contains.",
        "categories": ["famous_artists"],
        "queries": [
            ("Claude Monet Water Lilies painting", "Water Lilies", "Monet"),
            ("File:Exact_Commons_Name.jpg", "Friendly Title", ""),
        ],
    },
```

Category tags (non-exhaustive): `famous_artists`, `nature`, `architecture`,
`seasons`, `history`, `speed`, `AI Art`. The Gallery builds tiles from tags
in `scene_packs/index.json`.

### 2. Build assets

```bash
python3 scripts/build_scene_pack.py my_new_pack
python3 scripts/stamp_catalog.py
```

`stamp_catalog.py` writes `version`, `min_integration`, `featured`, and
per-image `sha256` for marketplace integrity checks.

### 3. Open a PR

Use the **art pack** PR template. Include provenance notes and confirm
licensing.

---

## Forbidden

- `type: "widget"` catalog entries  
- `script_url` or any executable payload for community packs  
- Copyrighted imagery  

---

## First-party renderers

`addons/xotd/` and `addons/daily_agenda/` are **not** Gallery installs.
They are pinned by SHA in the integration for Live skill rendering
(`--render-only`).
