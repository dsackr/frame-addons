# Fraimic Scripture of the Day Add-on

A Python utility that fetches a daily Bible verse, renders it onto a premium high-contrast layout, and uploads it to a target Fraimic e-ink canvas frame.

---

## Features

* **High-End Typography & Layout**: Generates a visually stunning canvas with a decorative border, a bold centered verse, a reference citation, and a translation badge.
* **Spectra 6 Palette Optimization**: Draws fonts and glyphs natively in the e-ink display's exact primary colors, producing crisp lines and readable text with zero fuzziness.
* **Flexible Sourcing**:
  * **Daily Verse of the Day (Default)**: Fetches from OurManna, falling back to Bible-API if needed.
  * **Custom Scriptures List**: Cycles through a local list of your own chosen verses instead.
  * **Built-in Fallback**: Bundled with a premium list of classic verses to ensure the system works offline or if both APIs are down.
* **Multi-Layout Support**: Handles Portrait (`1200 x 1600`) and Landscape (`800 x 480`) display frames, dynamically sizing text wrapping to fit perfectly.

---

## Setup & Installation

### 1. Install Dependencies
Make sure you have **Pillow** installed:
```bash
pip install Pillow
```

### 2. Configure Settings
Copy `config.example.json` to `config.json`:
```bash
cp config.example.json config.json
```
Edit `config.json` with your details:
* **`frame`**: Set the local IP address or host name of your frame, its resolution, and the byte layout (e.g. `split_half` for `1200x1600` or `sequential` for `800x480`).
* **`bible_translation`**: Preferred translation for the daily-verse API (e.g. `niv`, `kjv`, `web`, `bbe`).
* **`scripture_source`**: Set to `"daily_api"` to pull the verse of the day, or `"custom_list"` to cycle through the `custom_scriptures` list in the config file.
* **`custom_scriptures`**: Fill in a list of your own verses (`"q"` for the verse text, `"r"` for the reference, `"t"` for the translation) to display.

---

## Running Standalone

To run the renderer and update the frame immediately:
```bash
python3 scripture_renderer.py
```

This will save `scripture_preview.png` and `scripture.bin` locally, and upload the payload directly to the frame's REST API.
