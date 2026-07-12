# Fraimic xOTD (Day-of-the-Day) Add-on

A Python utility that fetches a daily joke, quote, or Bible verse -- depending on the configured `content_mode` -- renders it onto a premium high-contrast layout, and uploads it to a target Fraimic e-ink canvas frame.

Within the full Fraimic Home Assistant integration, this add-on is managed from the **Daily Content** tab, where you can create multiple independent instances -- each pairing one content mode with one target frame and its own schedule (e.g. Joke of the Day hourly on one frame, Scripture of the Day daily on another).

---

## Features

* **Four Content Modes**:
  * **Joke of the Day**: Fetches from icanhazdadjoke.com (default), or a custom API/list.
  * **Quote of the Day**: ZenQuotes or FavQs APIs (default), or a custom API/list.
  * **Scripture of the Day**: Daily Verse of the Day (OurManna, with Bible-API translation lookup), or a custom list.
  * **Word of the Day**: A random word paired with a free dictionary lookup (definition, part of speech, example sentence) by default, or a custom API/list.
* **High-End Typography & Layout**: Each mode gets its own premium composition -- decorative quote marks and an author signature for quotes, a co-equal verse+reference block with a translation badge for scripture, a setup/punchline reveal for jokes, and a hero word with a part-of-speech badge and definition for words -- all with a shared double decorative border.
* **Spectra 6 Palette Optimization**: Draws fonts and glyphs natively in the e-ink display's exact primary colors, producing crisp lines and readable text with zero fuzziness.
* **Built-in Fallbacks**: Each mode bundles a premium list of classic content so the system keeps working offline or if an API is down.
* **Multi-Layout Support**: Handles Portrait (`1200 x 1600`) and Landscape (`800 x 480`) display frames, dynamically sizing text wrapping to fit perfectly.
* **Themes**: `classic` (Outfit typography, the original look) or `retro_atomic` (a bold 1950s-poster display font with a yellow/red/black accent scheme) -- applies across all four content modes.
* **Drop Cap**: an optional large decorative tile around the first letter of the main text (the quote, verse, joke setup, or definition), left-aligning that block in an editorial style.

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
* **`content_mode`**: `"joke"`, `"quote"`, `"scripture"`, or `"word"`.
* **`theme`**: `"classic"` (default) or `"retro_atomic"`.
* **`drop_cap`**: `true`/`false` (default `false`).
* Mode-specific fields (`joke_feed`/`custom_jokes`, `quote_feed`/`custom_quotes`, `bible_translation`/`scripture_source`/`custom_scriptures`, `word_feed`/`custom_words`) -- only the fields for the selected `content_mode` matter.

---

## Running Standalone

To run the renderer and update the frame immediately:
```bash
python3 xotd_renderer.py
```

This will save `xotd_preview.png` and `xotd.bin` locally, and upload the payload directly to the frame's REST API.
