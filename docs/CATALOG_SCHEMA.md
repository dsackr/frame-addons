# Gallery art catalog schema (Content Platform Phase 7)

Marketplace foundations for **static art packs only**. Dynamic generators
(Live skills) are first-party and pinned in the integration — never shipped
as installable remote Python from this index.

## Index file

`scene_packs/index.json` is fetched by Digital Frames from:

`https://raw.githubusercontent.com/dsackr/frame-addons/main/scene_packs/index.json`

### Root object

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | int | yes (v1+) | Catalog format version. Integration accepts `1`. |
| `catalog_version` | string | recommended | Human/semver stamp of the whole catalog build. |
| `generated_at` | int | optional | Unix time the index was stamped. |
| `min_integration_default` | string | optional | Default floor for packs missing `min_integration`. |
| `packs` | array | yes | Art pack entries (see below). **No `type: widget`.** |

### Pack object

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Stable slug (`monet`, `van_gogh`). |
| `name` | string | yes | Display title. |
| `description` | string | recommended | Short blurb. |
| `categories` | string[] | recommended | Tags (e.g. `famous_artists`, `seasons`). |
| `category` | string | legacy | Single category; still accepted. |
| `license` | string | yes | Must state public-domain / free-to-use terms. |
| `cover` | string | yes | Repo-relative path to cover image. |
| `images` | array | yes | Image specs (see below). |
| `version` | string | recommended | Pack content version (`1.0.0`). |
| `min_integration` | string | recommended | Lowest Digital Frames version that may install this pack (`0.12.0`). |
| `featured` | bool | optional | Show in Gallery “Featured” strip. |

**Forbidden on packs:** `type: "widget"`, `script_url`, or any executable payload.

### Image object

| Field | Type | Required | Description |
|---|---|---|---|
| `filename` | string | yes | File name under the pack folder. |
| `path` | string | yes | Repo-relative path (e.g. `scene_packs/monet/01_….jpg`). |
| `title` | string | recommended | Work title (used as voice name). |
| `source` | string | recommended | Provenance label (e.g. Wikimedia Commons). |
| `commons_url` | string | recommended when from Commons | Source page URL. |
| `sha256` | string | recommended | Hex SHA-256 of the image bytes on disk. |

## Integrity

On install, Digital Frames verifies `sha256` when present. Mismatch fails that
image (same partial-install semantics as a download error). Checksums are for
**integrity**, not DRM.

## Stamping

After editing packs or rebuilding with `build_scene_pack.py`:

```bash
python3 scripts/stamp_catalog.py
```

This rewrites `index.json` with versions, feature flags, and checksums.

## Community contributions

See [CONTRIBUTING.md](../CONTRIBUTING.md) and the PR template. **Images and
JSON only** — no Python renderers in PRs to this catalog.
