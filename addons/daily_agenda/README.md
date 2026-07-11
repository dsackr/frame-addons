# Fraimic Daily Agenda Add-on

A Python utility that queries Google Calendar and local weather forecasts, renders a premium high-contrast wall dashboard (drawn in native Spectra 6 e-ink colors), and uploads it directly to your Fraimic e-ink canvas frame.

---

## Features

* **High-Contrast, Crisp Drawing**: Draws elements natively in the e-ink display's exact physical color values, ensuring that text and weather graphics are razor-sharp with zero fuzzy dithering noise.
* **Dual Calendar Input**:
  * **iCal URL (Recommended for simplicity)**: Directly parses Google Calendar's private iCal address without requiring API registration or developer setups.
  * **Configured Calendars**: Fetches events from one or more `calendar.*` entities already set up in your Home Assistant instance -- Google Calendar, Local Calendar, CalDAV, or any other calendar integration.
* **Open-Meteo Weather**: Integrates current temperature, daily high/lows, and weather condition details using a keyless, public API.
* **Frame Info Diagnostics**: Queries the frame's `/api/info` REST endpoint to check battery and WiFi levels, overlaying them right onto your dashboard screen.
* **Automated Layout Resizing**: Supports both **Portrait** (`1200 x 1600`) and **Landscape** (`800 x 480`) layout frames, automatically adapting visual column designs to make the best use of screen dimensions.

---

## Setup & Installation

### 1. Install Dependencies
The script is written in pure Python and only requires the **Pillow** image library:
```bash
pip install Pillow
```

### 2. Configure Settings
Copy `config.example.json` to `config.json` in the same directory:
```bash
cp config.example.json config.json
```
Edit `config.json` with your details:
* **`calendar`**:
  * Set `source_type` to `"ical"` and enter your Google Calendar private iCal address in `ical_url` (see below for instructions on how to get it).
  * Alternatively, set `source_type` to `"ha"` and supply your Home Assistant URL, Long-Lived Access Token, and one or more calendar entity IDs in `ha_calendar_entities` (a list -- events from all of them are merged together).
* **`weather`**: Set coordinates for local forecasts.
* **`frame`**: Set the local IP address or host name of your frame, its resolution, and the byte layout (e.g. `split_half` for `1200x1600` or `sequential` for `800x480`).
* **`timezone`**: Specify your IANA Timezone name (e.g. `America/Los_Angeles`).

#### How to find your Google Calendar Private iCal Link:
1. Open [Google Calendar](https://calendar.google.com) on a computer.
2. In the left panel, hover over the calendar you want to use, click the three vertical dots (options menu), and select **Settings and sharing**.
3. Scroll down to the **Integrate calendar** section.
4. Copy the link in the **Secret address in iCal format** field. 
   *(Caution: Do not share this URL; it allows anyone to view your calendar events).*

---

## Running the Add-on

Run the script directly to render your agenda and upload it to the frame:
```bash
python3 agenda_renderer.py
```

Upon running, the script:
1. Saves a local debug preview image named `agenda_preview.png`.
2. Encodes the visual board into a raw Spectra 6 frame buffer `agenda.bin`.
3. Uploads the buffer to the frame's REST API.

---

## Automation & Scheduling

To keep your agenda frame updated throughout the day, automate the script's execution:

### Option A: Local Cron Job
Set up a standard cron job to refresh the frame every hour. Open your crontab editor:
```bash
crontab -e
```
Add the following line (pointing to your absolute script path):
```cron
0 * * * * cd /path/to/frame-addons/addons/daily_agenda && python3 agenda_renderer.py >> cron.log 2>&1
```

### Option B: Home Assistant Shell Command
If running Home Assistant, add this script as a Shell Command in your `configuration.yaml`:
```yaml
shell_command:
  update_fraimic_agenda: "python3 /path/to/frame-addons/addons/daily_agenda/agenda_renderer.py"
```
Then, reload shell commands and set up a standard HA automation to trigger the command periodically:
```yaml
alias: "Refresh Daily Agenda Frame"
trigger:
  - platform: time_pattern
    hours: "/1"
action:
  - action: shell_command.update_fraimic_agenda
```
