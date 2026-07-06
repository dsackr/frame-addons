# Fraimic Quote of the Day Add-on

A Python utility that fetches a daily inspiring quote, formats it onto a premium high-contrast layout, and uploads it to a target Fraimic e-ink canvas frame.

---

## Features

* **High-End Typography & Layout**: Generates a visually stunning canvas. Includes a double decorative border, giant red quotation marks, a bold centered quote body, and an aligned-right author signature.
* **Spectra 6 Palette Optimization**: Draws fonts and glyphs natively in the e-ink display's exact primary colors, producing crisp lines and readable text with zero fuzziness.
* **Flexible Sourcing**:
  * **ZenQuotes API (Default)**: Fetches the public quote of the day.
  * **Custom Quotes List**: Selects quotes randomly or sequentially from a local list of your favorite quotes.
  * **Built-in Fallback**: Bundled with a premium list of classic quotes to ensure the system works offline or if the API is down.
* **Multi-Layout Support**: Handles Portrait (`1200 x 1600`) and Landscape (`800 x 480`) display frames, dynamically sizing text wrapping and quotation marks to fit perfectly.

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
* **`quote_source`**: Set to `"api"` to pull from the web, or `"custom"` to pull from the `custom_quotes` list in the config file.
* **`custom_quotes`**: Fill in a list of your own quotes (consisting of `"q"` for quote and `"a"` for author) to display.

---

## Running Standalone

To run the renderer and update the frame immediately:
```bash
python3 quote_renderer.py
```

This will save `quote_preview.png` and `quote.bin` locally, and upload the payload directly to the frame's REST API.

---

## Home Assistant Automation (UI Setup)

You can manage which frame receives the quote and schedule the refresh time directly from the Home Assistant UI using the included Blueprint:

### Step 1: Add Shell Command
Add the script to your Home Assistant `configuration.yaml` file:
```yaml
shell_command:
  update_fraimic_quote: "python3 /path/to/frame-addons/addons/quote_of_the_day/quote_renderer.py"
```
Reload Shell Commands in Developer Tools.

### Step 2: Install the Blueprint
Copy the contents of **`blueprint.yaml`** from this directory into your Home Assistant server at:
`/config/blueprints/automation/fraimic_quote_updater.yaml`

### Step 3: Create Automation
1. Navigate to **Settings > Automations & Scenes > Blueprints**.
2. Locate **Fraimic Quote of the Day Updater** and click **Create Automation**.
3. In the UI configuration:
   * **Daily Update Time**: Select your preferred time (e.g. `07:30 AM`).
   * **Quote Shell Command**: Keep as `shell_command.update_fraimic_quote` (or match whatever name you declared in Step 1).
4. Save the automation.
