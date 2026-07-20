# Digital Frames — content catalog (art packs + renderers)

This repository hosts **Gallery** art packs and first-party **Live** renderer
scripts for the [Digital Frames Home Assistant integration](https://github.com/dsackr/ha-digital-frames)
(package `digital_frames`). Content can update without a new integration release.

## Contents

* **`scene_packs/`**: Curated, public-domain art and seasonal image bundles
  (Gallery). Central manifest: `scene_packs/index.json`.
* **`addons/`**: First-party renderer scripts used by the integration:
  * **[Daily Agenda](addons/daily_agenda/)** — calendar + weather layout (still
    installed as a catalog widget until Content Platform Phase 4 migrates it
    to Live generators — see `docs/CONTENT_PLATFORM_ROADMAP.md` in the
    integration repo).
  * **[xOTD renderer](addons/xotd/)** — text layout engine for Live content
    (joke/quote/word/scripture). **Not** a user-installable catalog entry;
    `skills.py` downloads a **pinned** commit of this script for
    `--render-only` subprocess renders.

## Related

👉 **[ha-digital-frames](https://github.com/dsackr/ha-digital-frames)** — core
integration, panel UI, FramePort drivers.

## Contributing art packs

1. Edit the `PACKS` registry in `scripts/build_scene_pack.py`.
2. Run the generator to fetch and package public-domain artwork.
3. Commit and push here.

**Do not add new `type: widget` packs** while the integration’s Content
Platform Phases 4–5 are open (see the integration roadmap). New dynamic
features should land as Live generators, not frame-IP widgets.
