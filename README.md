# Fraimic Add-ons & Scene Packs

This repository hosts official and community-curated add-on packs, scene packs, and future expansion content for the **Fraimic Home Assistant Integration**.

By hosting these resources separately, users can discover and install new content immediately without needing to update the core Home Assistant integration itself.

## Contents

* **`scene_packs/`**: Curated, public-domain art and seasonal image bundles designed for one-click installation on Fraimic e-ink canvas frames.
  * Includes a central manifest (`scene_packs/index.json`) mapping all available packs and image specifications.
  * Automatically and dynamically fetched at runtime by the Home Assistant integration.
* **`addons/`**: Custom layout scripts, diagnostics, and widgets to display dynamic information on your canvas.
  * **[Daily Agenda](file:///Users/dsackrider/repos/frame-addons/addons/daily_agenda/README.md)**: Reads your calendar (a Google/iCal URL, or one or more calendars already configured in Home Assistant) and weather forecast, rendering a beautiful dashboard natively in e-ink Spectra 6 colors.
  * **[xOTD (Day-of-the-Day)](file:///Users/dsackrider/repos/frame-addons/addons/xotd/README.md)**: Displays a daily joke, quote, or Bible verse -- fetched from the web or a local custom list -- on a premium decorative layout. Create multiple instances to run different content on different frames and schedules.



## Related Repositories

👉 **[Fraimic Home Assistant Integration](https://github.com/dsackr/fraimic-homeassistant)** — The main integration repository containing the core driver, local libraries, and panel UI.

## Contributing Scene Packs

To add or update a scene pack:
1. Modify the `PACKS` registry in `scripts/build_scene_pack.py`.
2. Run the generator script to fetch, downsize, and package the public-domain artwork.
3. Commit and push the changes here.
