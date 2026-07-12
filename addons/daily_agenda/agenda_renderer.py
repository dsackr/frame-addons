#!/usr/bin/env python3
"""Daily Agenda Renderer & Frame Uploader.

Fetches daily events from Google Calendar (via direct iCal link or Home Assistant API),
retrieves weather forecast from Open-Meteo, queries the frame status, renders a
gorgeous high-contrast wall dashboard, encodes it to the Spectra 6 4-bit binary format,
and uploads it to the Fraimic e-ink canvas frame.
"""

from __future__ import annotations

import os
import sys
import json
import math
import datetime
import urllib.request
import urllib.parse
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Constants & Color Palette
# ---------------------------------------------------------------------------
# Exact RGB values expected by the Spectra 6 hardware to avoid dithering noise
COLOR_BLACK = (0, 0, 0)         # Primary text, timeline lines
COLOR_WHITE = (255, 255, 255)   # Background
COLOR_YELLOW = (239, 222, 68)   # Sun, highlights
COLOR_RED = (178, 19, 24)      # Alert icons, meetings, agenda title
COLOR_BLUE = (33, 87, 186)     # Cloud outlines, rain drops, weather detail
COLOR_GREEN = (18, 95, 32)     # Secondary tags, battery OK state

SPECTRA6_REAL_WORLD_RGB = (
    COLOR_BLACK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_BLUE,
    COLOR_GREEN,
)

SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)

WMO_WEATHER_CODES = {
    0: ("Sunny", 0),
    1: ("Mainly Clear", 1),
    2: ("Partly Cloudy", 2),
    3: ("Overcast", 3),
    45: ("Foggy", 45),
    48: ("Foggy", 48),
    51: ("Light Drizzle", 51),
    53: ("Drizzle", 51),
    55: ("Heavy Drizzle", 51),
    61: ("Light Rain", 61),
    63: ("Moderate Rain", 61),
    65: ("Heavy Rain", 61),
    71: ("Light Snow", 71),
    73: ("Moderate Snow", 71),
    75: ("Heavy Snow", 71),
    80: ("Showers", 80),
    81: ("Rain Showers", 80),
    82: ("Violent Showers", 80),
    95: ("Thunderstorm", 95),
    96: ("Storm with Hail", 95),
    99: ("Severe Storm", 95)
}

# ---------------------------------------------------------------------------
# Helper: Timezone & Font loaders
# ---------------------------------------------------------------------------
def get_timezone(tz_name: str):
    """Retrieve timezone object, falling back gracefully to UTC if needed."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        pass
    
    # Fallback to local system time or basic offset mapping if zoneinfo is not available
    print(f"Warning: zoneinfo not available. Operating in UTC offset fallback.")
    class FallbackTZ(datetime.tzinfo):
        def __init__(self, name):
            self._name = name
        def utcoffset(self, dt):
            # Map standard US timezones roughly
            offsets = {"America/New_York": -5, "America/Chicago": -6, 
                       "America/Denver": -7, "America/Los_Angeles": -8}
            hours = offsets.get(self._name, 0)
            # Add DST (rough estimate)
            dst_months = (3, 4, 5, 6, 7, 8, 9, 10)
            if dt and dt.month in dst_months:
                hours += 1
            return datetime.timedelta(hours=hours)
        def tzname(self, dt):
            return self._name
        def dst(self, dt):
            return datetime.timedelta(hours=1)
            
    return FallbackTZ(tz_name)

def load_font(font_name="Outfit", font_style="Regular", size=24) -> ImageFont.ImageFont:
    """Download standard ttf font from Google Fonts if not cached locally, else load it."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "fonts")
    os.makedirs(font_dir, exist_ok=True)
    
    style_map = {
        "Regular": "Regular",
        "Medium": "Medium",
        "SemiBold": "SemiBold",
        "Bold": "Bold"
    }
    style_suffix = style_map.get(font_style, "Regular")
    font_filename = f"Outfit-{style_suffix}.ttf"
    font_path = os.path.join(font_dir, font_filename)
    
    if not os.path.exists(font_path):
        url = f"https://raw.githubusercontent.com/Outfitio/Outfit-Fonts/main/fonts/ttf/{font_filename}"
        try:
            print(f"Downloading {font_filename} font from Google Fonts (Outfitio)...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(font_path, "wb") as f:
                    f.write(response.read())
        except Exception as e:
            print(f"Error downloading font: {e}. Falling back to default system font.")
            return ImageFont.load_default()
            
    try:
        return ImageFont.truetype(font_path, size)
    except Exception as e:
        print(f"Error loading font {font_path}: {e}. Falling back to default.")
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Event Parsers (iCal / Home Assistant)
# ---------------------------------------------------------------------------
def parse_ics_date(date_str: str, default_tz) -> datetime.datetime:
    """Parse dates from iCal files, adjusting timezone tags."""
    date_str = date_str.strip()
    if len(date_str) == 8:  # All-day (YYYYMMDD)
        dt = datetime.datetime.strptime(date_str, "%Y%m%d")
        return dt.replace(hour=0, minute=0, second=0, tzinfo=default_tz)
    
    if date_str.endswith("Z"):  # UTC
        dt = datetime.datetime.strptime(date_str, "%Y%m%dT%H%M%SZ")
        return dt.replace(tzinfo=datetime.timezone.utc)
    
    # Check for timezone in format
    try:
        return datetime.datetime.strptime(date_str, "%Y%m%dT%H%M%S").replace(tzinfo=default_tz)
    except ValueError:
        # Fallback to general truncation
        dt = datetime.datetime.strptime(date_str[:8], "%Y%m%d")
        return dt.replace(tzinfo=default_tz)

def fetch_ical_events(ical_url: str, target_tz) -> list[dict]:
    """Download and parse calendar events directly from a public/private iCal address."""
    print("Fetching events from iCal URL...")
    try:
        req = urllib.request.Request(ical_url, headers={"User-Agent": "FraimicAgendaAddon/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8")
    except Exception as e:
        print(f"Error downloading iCal calendar: {e}")
        return []

    events = []
    current_event = None
    
    # Handle line folding in ICS files
    lines = []
    for line in content.splitlines():
        if line.startswith((' ', '\t')) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
            
    today = datetime.datetime.now(target_tz).date()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line == "BEGIN:VEVENT":
            current_event = {}
        elif line == "END:VEVENT":
            if current_event and "summary" in current_event and "start" in current_event:
                # Filter for today's events (or multiday starting/ending today)
                start_dt = current_event["start"].astimezone(target_tz)
                end_dt = current_event.get("end", start_dt).astimezone(target_tz)
                
                # Check if event overlaps with today
                if start_dt.date() <= today <= end_dt.date():
                    events.append(current_event)
            current_event = None
        elif current_event is not None:
            if ":" in line:
                key_part, val = line.split(":", 1)
                key = key_part.split(";")[0].upper()
                if key == "SUMMARY":
                    current_event["summary"] = val.replace("\\,", ",").replace("\\;", ";")
                elif key == "LOCATION":
                    current_event["location"] = val.replace("\\,", ",").replace("\\;", ";")
                elif key == "DESCRIPTION":
                    current_event["description"] = val.replace("\\n", "\n").replace("\\,", ",")
                elif key == "DTSTART":
                    current_event["start"] = parse_ics_date(val, target_tz)
                elif key == "DTEND":
                    current_event["end"] = parse_ics_date(val, target_tz)
                    
    # Sort events chronologically
    events.sort(key=lambda x: x["start"])
    return events

def fetch_ha_events(config: dict, target_tz) -> list[dict]:
    """Fetch calendar events from the Home Assistant API."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ha_events_path = os.path.join(script_dir, "ha_events.json")
    
    data = []
    if os.path.exists(ha_events_path):
        print("Loading calendar events from local pre-fetched ha_events.json...")
        try:
            with open(ha_events_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading local ha_events.json: {e}")
            data = []
            
    if not data:
        print("Fetching calendar from Home Assistant API...")
        ha_url = config.get("ha_url")
        token = config.get("ha_token")
        # ha_calendar_entities (plural) is the current config_schema field --
        # one or more entities the user picked from the "Configured
        # Calendars" checklist (any calendar integration: Google Calendar,
        # Local Calendar, CalDAV, etc., not specifically Google). Falls back
        # to the older singular ha_calendar_entity for configs saved before
        # multi-select existed.
        entities = config.get("ha_calendar_entities")
        if not entities:
            legacy_entity = config.get("ha_calendar_entity")
            entities = [legacy_entity] if legacy_entity else []

        if not (ha_url and token and entities):
            print("Warning: Home Assistant connection credentials missing. No calendar events loaded.")
            return []

        ha_url = ha_url.rstrip("/")
        now = datetime.datetime.now(target_tz)
        start_str = now.replace(hour=0, minute=0, second=0).isoformat()
        end_str = now.replace(hour=23, minute=59, second=59).isoformat()

        data = []
        for entity in entities:
            url = f"{ha_url}/api/calendars/{entity}?start={urllib.parse.quote(start_str)}&end={urllib.parse.quote(end_str)}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    data.extend(json.loads(response.read().decode("utf-8")))
            except Exception as e:
                print(f"Error fetching from Home Assistant Calendar API ({entity}): {e}")
        
    events = []
    for item in data:
        start_raw = item["start"].get("dateTime") or item["start"].get("date")
        end_raw = item["end"].get("dateTime") or item["end"].get("date")
        
        # Check if all day
        is_all_day = "dateTime" not in item["start"]
        
        if is_all_day:
            start_dt = datetime.datetime.strptime(start_raw, "%Y-%m-%d").replace(tzinfo=target_tz)
            end_dt = datetime.datetime.strptime(end_raw, "%Y-%m-%d").replace(tzinfo=target_tz)
        else:
            # Parse ISO-8601 with timezone offsets (e.g. 2026-07-06T09:00:00-07:00).
            # fromisoformat handles numeric offsets natively in Python 3.7+, but
            # only accepts a trailing "Z" (UTC) from Python 3.11 -- normalize it
            # to "+00:00" so this still works on older Python (e.g. 3.9) against
            # calendar APIs that return "Z"-suffixed times.
            start_dt = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(target_tz)
            end_dt = datetime.datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(target_tz)
            
        events.append({
            "summary": item.get("summary", "No Title"),
            "start": start_dt,
            "end": end_dt,
            "location": item.get("location", ""),
            "description": item.get("description", ""),
            "all_day": is_all_day
        })
        
    events.sort(key=lambda x: x["start"])
    return events

def get_coordinates_from_location(location: str) -> tuple[float, float] | None:
    """Look up latitude and longitude using Open-Meteo's free Geocoding API."""
    import urllib.parse
    query = urllib.parse.quote(location)
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={query}&count=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FraimicAgendaAddon/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results")
            if results and len(results) > 0:
                res = results[0]
                return float(res["latitude"]), float(res["longitude"])
    except Exception as e:
        print(f"Error during location geocoding lookup: {e}")
    return None

# ---------------------------------------------------------------------------
# Weather Fetcher (Open-Meteo)
# ---------------------------------------------------------------------------
def fetch_weather(lat: float, lon: float, temp_unit: str = "fahrenheit", api_url: str = None) -> dict:
    """Download current weather conditions using Open-Meteo's keyless API."""
    print("Fetching weather forecast...")
    base_url = api_url or "https://api.open-meteo.com/v1/forecast"
    url = (
        f"{base_url}?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,weather_code"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min"
        f"&temperature_unit={temp_unit}&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FraimicAgendaAddon/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            
        curr_temp = int(round(data["current"]["temperature_2m"]))
        curr_code = data["current"]["weather_code"]
        desc, icon_code = get_weather_desc_and_icon(curr_code)
        
        high = int(round(data["daily"]["temperature_2m_max"][0]))
        low = int(round(data["daily"]["temperature_2m_min"][0]))
        
        return {
            "temp": curr_temp,
            "desc": desc,
            "icon_code": icon_code,
            "high": high,
            "low": low,
            "unit": "°F" if temp_unit == "fahrenheit" else "°C"
        }
    except Exception as e:
        print(f"Error fetching weather forecast: {e}")
        return {}

# ---------------------------------------------------------------------------
# Frame Info Fetcher
# ---------------------------------------------------------------------------
def fetch_frame_info(frame_ip: str) -> dict:
    """Fetch battery percentage and wifi RSSI from the frame's REST API."""
    print(f"Fetching status info from frame at {frame_ip}...")
    url = f"http://{frame_ip}/api/info"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            
        battery = data.get("battery", {}).get("percent", 100)
        wifi = data.get("wifi", {}).get("rssi", -50)
        return {"battery": battery, "wifi": wifi, "connected": True}
    except Exception as e:
        print(f"Could not connect to frame: {e}. Proceeding without live status.")
        return {"battery": None, "wifi": None, "connected": False}

# ---------------------------------------------------------------------------
# Vector Weather Icon Drawer
# ---------------------------------------------------------------------------
def draw_weather_icon(draw: ImageDraw.ImageDraw, code: int, x: int, y: int, size: int = 120):
    """Draw clean geometry weather icons in native Spectra 6 colors."""
    cx = x + size // 2
    cy = y + size // 2
    
    if code == 0:  # Sun (Sunny)
        r = size // 4
        # Draw rays
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = cx + int((r + 6) * math.cos(rad))
            y1 = cy + int((r + 6) * math.sin(rad))
            x2 = cx + int((r + 20) * math.cos(rad))
            y2 = cy + int((r + 20) * math.sin(rad))
            draw.line((x1, y1, x2, y2), fill=COLOR_YELLOW, width=5)
        # Core sun
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=COLOR_YELLOW, outline=COLOR_BLACK, width=3)
        
    elif code in (1, 2, 3, 45, 48):  # Cloudy / Foggy
        r = size // 5
        # Left bubble
        draw.ellipse((cx - r * 1.4, cy, cx - r * 0.4, cy + r * 1.3), fill=COLOR_WHITE, outline=COLOR_BLUE, width=3)
        # Right bubble
        draw.ellipse((cx + r * 0.4, cy, cx + r * 1.4, cy + r * 1.3), fill=COLOR_WHITE, outline=COLOR_BLUE, width=3)
        # Middle bubble (higher)
        draw.ellipse((cx - r, cy - r * 0.5, cx + r, cy + r * 1.2), fill=COLOR_WHITE, outline=COLOR_BLUE, width=3)
        # Fill center
        draw.rectangle((cx - r * 1.1, cy + r * 0.2, cx + r * 1.1, cy + r * 1.25), fill=COLOR_WHITE)
        # Redraw bottom outline
        draw.line((cx - r * 1.3, cy + r * 1.3, cx + r * 1.3, cy + r * 1.3), fill=COLOR_BLUE, width=3)
        
    elif code in (51, 53, 55, 61, 63, 65, 80, 81, 82):  # Rain / Showers
        # Cloudy base
        draw_weather_icon(draw, 1, x, y - 10, size)
        # Rain drops
        r = size // 5
        rx = cx
        ry = cy + r * 1.2
        draw.line((rx - 25, ry, rx - 29, ry + 15), fill=COLOR_BLUE, width=4)
        draw.line((rx, ry + 5, rx - 4, ry + 20), fill=COLOR_BLUE, width=4)
        draw.line((rx + 25, ry, rx + 21, ry + 15), fill=COLOR_BLUE, width=4)
        
    elif code in (95, 96, 99):  # Thunderstorm
        # Cloudy base
        draw_weather_icon(draw, 1, x, y - 10, size)
        # Lightning bolt
        r = size // 5
        rx = cx
        ry = cy + r * 1.2
        draw.polygon([
            (rx, ry), (rx - 15, ry + 15), (rx - 5, ry + 15), 
            (rx - 12, ry + 32), (rx + 8, ry + 12), (rx - 2, ry + 12)
        ], fill=COLOR_RED)
        
    elif code in (71, 73, 75):  # Snow
        # Cloudy base
        draw_weather_icon(draw, 1, x, y - 10, size)
        # Snow flakes (dots)
        r = size // 5
        rx = cx
        ry = cy + r * 1.2
        draw.ellipse((rx - 22, ry, rx - 17, ry + 5), fill=COLOR_BLUE)
        draw.ellipse((rx - 2, ry + 6, rx + 3, ry + 11), fill=COLOR_BLUE)
        draw.ellipse((rx + 18, ry, rx + 23, ry + 5), fill=COLOR_BLUE)
        
    else:  # Sun + Cloud mix
        draw_weather_icon(draw, 0, x - 15, y - 15, size - 20)
        draw_weather_icon(draw, 1, x + 10, y + 10, size - 15)

# ---------------------------------------------------------------------------
# Event Timeline Layout Helpers
# ---------------------------------------------------------------------------
def wrap_text(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Wrap words to fit within a maximum width boundary."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]

        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []

    if current_line:
        lines.append(" ".join(current_line))

    return lines

def wrap_text_max_lines(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    """Word-wrap, then cap to max_lines -- marking the last line with an
    ellipsis if anything had to be dropped, instead of chopping mid-word."""
    lines = wrap_text(text, draw, font, max_width)
    if len(lines) <= max_lines:
        return lines
    truncated = lines[:max_lines]
    truncated[-1] = truncated[-1].rstrip() + "…"
    return truncated

def layout_events(
    draw: ImageDraw.ImageDraw,
    events: list[dict],
    font_time: ImageFont.ImageFont,
    font_title: ImageFont.ImageFont,
    font_sub: ImageFont.ImageFont,
    wrap_width: int,
    time_line_h: int,
    title_line_h: int,
    sub_line_h: int,
    row_gap: int,
    max_title_lines: int = 2,
) -> list[dict]:
    """Word-wrap each event's title/location and compute the real vertical
    height its row needs, instead of every event claiming the same fixed
    slot regardless of how much text it actually has."""
    laid_out = []
    for ev in events:
        is_all_day = ev.get("all_day", False)
        if is_all_day:
            time_lbl = "ALL DAY"
        else:
            time_lbl = f"{ev['start'].strftime('%-I:%M %p')} - {ev['end'].strftime('%-I:%M %p')}"

        title_lines = wrap_text_max_lines(ev["summary"], draw, font_title, wrap_width, max_title_lines)

        sub_raw = (ev.get("location") or ev.get("description", "")).split("\n")[0].strip()
        sub_lines = wrap_text_max_lines(sub_raw, draw, font_sub, wrap_width, 1) if sub_raw else []

        row_height = time_line_h + len(title_lines) * title_line_h + len(sub_lines) * sub_line_h + row_gap
        laid_out.append({
            "time_lbl": time_lbl,
            "is_all_day": is_all_day,
            "title_lines": title_lines,
            "sub_lines": sub_lines,
            "row_height": row_height,
        })
    return laid_out

def fit_events_to_height(laid_out: list[dict], available_height: int) -> tuple[list[dict], int]:
    """Accumulate laid-out event rows until the available vertical space
    runs out, so the timeline shows as many events as actually fit today
    instead of a fixed per-orientation cap. Always shows at least one event
    (even if it overflows slightly) rather than rendering an empty timeline."""
    total = 0
    visible = []
    for item in laid_out:
        if visible and total + item["row_height"] > available_height:
            break
        total += item["row_height"]
        visible.append(item)
    hidden = len(laid_out) - len(visible)
    return visible, hidden

# ---------------------------------------------------------------------------
# Pillow Rendering Engine
# ---------------------------------------------------------------------------
def render_portrait(width: int, height: int, events: list[dict], weather: dict, frame_stats: dict, target_tz) -> Image.Image:
    """Create the 1200 x 1600 Portrait Daily Agenda canvas."""
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    font_bold_huge = load_font("Outfit", "Bold", 92)
    font_bold_lg = load_font("Outfit", "Bold", 48)
    font_bold_md = load_font("Outfit", "Bold", 36)
    font_regular_md = load_font("Outfit", "SemiBold", 28)
    font_regular_sm = load_font("Outfit", "SemiBold", 22)

    now = datetime.datetime.now(target_tz)

    # 1. Date Header (Left side) -- this display only refreshes once a
    # day/hour, so a live clock just reads as stale/wrong. Give that space
    # to the date instead: big weekday on top, month + day below.
    weekday_str = now.strftime("%A").upper()
    month_day_str = now.strftime("%B %-d").upper()
    draw.text((80, 70), weekday_str, fill=COLOR_BLACK, font=font_bold_huge)
    draw.text((80, 195), month_day_str, fill=COLOR_RED, font=font_bold_lg)

    # 2. Weather Widget (Right side)
    if weather:
        # Bounding box coordinates
        wx, wy = 750, 70
        draw_weather_icon(draw, weather["icon_code"], wx, wy, 150)
        
        temp_str = f"{weather['temp']}{weather['unit']}"
        draw.text((wx + 170, wy + 20), temp_str, fill=COLOR_BLACK, font=font_bold_lg)
        
        desc_str = weather["desc"]
        draw.text((wx + 170, wy + 80), desc_str, fill=COLOR_BLUE, font=font_regular_md)
        
        range_str = f"H {weather['high']}°  L {weather['low']}°"
        draw.text((wx + 170, wy + 120), range_str, fill=COLOR_BLACK, font=font_regular_sm)
        
    # Divider line separating header and content
    draw.line((80, 290, width - 80, 290), fill=COLOR_BLACK, width=4)
    
    # 3. Agenda Title
    draw.text((80, 330), "TODAY'S SCHEDULE", fill=COLOR_RED, font=font_bold_lg)
    
    # 4. Events Timeline -- sized to how many events there actually are
    # today, not a fixed per-orientation cap. Each event's row height comes
    # from its own wrapped title/location instead of every event claiming
    # the same fixed slot, so a light day spaces out and a busy day still
    # fits without hard-truncating text mid-word.
    start_y = 450
    timeline_x = 120
    bottom_boundary = height - 140  # leaves room for the footer line + status text
    time_line_h, title_line_h, sub_line_h, row_gap = 34, 46, 32, 36

    if not events:
        draw.text((width // 2, 750), "No events scheduled for today.",
                  fill=COLOR_BLUE, font=font_bold_md, anchor="ma")
        draw.text((width // 2, 810), "Enjoy your free day!",
                  fill=COLOR_BLACK, font=font_regular_md, anchor="ma")
    else:
        wrap_width = width - timeline_x - 40 - 80
        laid_out = layout_events(
            draw, events, font_regular_sm, font_bold_md, font_regular_sm, wrap_width,
            time_line_h, title_line_h, sub_line_h, row_gap, max_title_lines=2
        )
        # Reserve room for a "+N more" note in case not everything fits.
        display_events, hidden_count = fit_events_to_height(laid_out, bottom_boundary - start_y - 40)

        curr_y = start_y
        row_tops = []
        for item in display_events:
            row_tops.append(curr_y)
            curr_y += item["row_height"]
        content_bottom = curr_y - row_gap

        draw.line((timeline_x, start_y + 10, timeline_x, content_bottom + 10), fill=COLOR_BLACK, width=3)

        for item, row_y in zip(display_events, row_tops):
            dot_color = COLOR_GREEN if item["is_all_day"] else COLOR_BLUE
            draw.ellipse((timeline_x - 10, row_y + 8, timeline_x + 10, row_y + 28),
                         fill=dot_color, outline=COLOR_BLACK, width=2)

            draw.text((timeline_x + 40, row_y), item["time_lbl"], fill=COLOR_RED, font=font_regular_sm)

            line_y = row_y + time_line_h
            for line in item["title_lines"]:
                draw.text((timeline_x + 40, line_y), line, fill=COLOR_BLACK, font=font_bold_md)
                line_y += title_line_h
            for line in item["sub_lines"]:
                draw.text((timeline_x + 40, line_y), line, fill=COLOR_BLUE, font=font_regular_sm)
                line_y += sub_line_h

        if hidden_count:
            draw.text((timeline_x + 40, content_bottom + 10), f"+ {hidden_count} more today",
                       fill=COLOR_BLUE, font=font_regular_sm)

    # 5. Footer Line
    draw.line((80, height - 100, width - 80, height - 100), fill=COLOR_BLACK, width=2)
    
    # Status
    stats_list = []
    if frame_stats.get("battery") is not None:
        stats_list.append(f"Battery: {frame_stats['battery']}%")
    if frame_stats.get("wifi") is not None:
        # simple classification
        rssi = frame_stats["wifi"]
        sig = "Excellent" if rssi > -50 else "Good" if rssi > -70 else "Fair" if rssi > -85 else "Weak"
        stats_list.append(f"WiFi: {sig}")
        
    status_left = " | ".join(stats_list) if stats_list else "Fraimic Canvas System Active"
    draw.text((80, height - 70), status_left, fill=COLOR_BLACK, font=font_regular_sm)
    
    update_str = f"Updated: {now.strftime('%m/%d %-I:%M %p')}"
    draw.text((width - 80, height - 70), update_str, fill=COLOR_BLACK, font=font_regular_sm, anchor="ra")
    
    return img

def render_landscape(width: int, height: int, events: list[dict], weather: dict, frame_stats: dict, target_tz) -> Image.Image:
    """Create the 800 x 480 Landscape Daily Agenda canvas."""
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    font_bold_huge = load_font("Outfit", "Bold", 50)
    font_bold_lg = load_font("Outfit", "Bold", 28)
    font_bold_md = load_font("Outfit", "Bold", 22)
    font_regular_md = load_font("Outfit", "SemiBold", 18)
    font_regular_sm = load_font("Outfit", "SemiBold", 15)

    now = datetime.datetime.now(target_tz)

    # Split column layout: Divider at x = 300
    draw.line((300, 30, 300, height - 30), fill=COLOR_BLACK, width=2)

    # Left Column (Date & Weather) -- no live clock (this refreshes once a
    # day/hour, so a time-of-day reads as stale/wrong); the date gets the
    # freed space instead, as a big weekday over the month + day.
    weekday_str = now.strftime("%A").upper()
    month_day_str = now.strftime("%b %-d").upper()
    draw.text((40, 32), weekday_str, fill=COLOR_BLACK, font=font_bold_huge)
    draw.text((40, 92), month_day_str, fill=COLOR_RED, font=font_bold_lg)

    if weather:
        wx, wy = 40, 140
        draw_weather_icon(draw, weather["icon_code"], wx, wy, 80)
        
        temp_str = f"{weather['temp']}{weather['unit']}"
        draw.text((wx + 95, wy + 10), temp_str, fill=COLOR_BLACK, font=font_bold_lg)
        
        desc_str = weather["desc"]
        draw.text((wx + 95, wy + 42), desc_str, fill=COLOR_BLUE, font=font_regular_sm)
        
        range_str = f"High {weather['high']}° / Low {weather['low']}°"
        draw.text((40, 240), range_str, fill=COLOR_BLACK, font=font_regular_sm)
        
    # Frame stats bottom left
    bat_val = frame_stats.get("battery")
    wifi_val = frame_stats.get("wifi")
    stats_y = 350
    if bat_val is not None:
        draw.text((40, stats_y), f"Battery: {bat_val}%", fill=COLOR_GREEN if bat_val > 25 else COLOR_RED, font=font_regular_sm)
        stats_y += 22
    if wifi_val is not None:
        draw.text((40, stats_y), f"WiFi Strength: {wifi_val} dBm", fill=COLOR_BLACK, font=font_regular_sm)
        stats_y += 22
        
    update_str = f"Updated: {now.strftime('%-I:%M %p')}"
    draw.text((40, 410), update_str, fill=COLOR_BLACK, font=font_regular_sm)
    
    # Right Column (Agenda Events) -- sized to how many events there
    # actually are today, not a fixed 3-event cap (see layout_events /
    # fit_events_to_height, shared with render_portrait).
    draw.text((330, 40), "TODAY'S SCHEDULE", fill=COLOR_RED, font=font_bold_lg)

    start_y = 100
    timeline_x = 350
    bottom_boundary = height - 20
    time_line_h, title_line_h, sub_line_h, row_gap = 20, 26, 20, 24

    if not events:
        draw.text((550, 220), "No events scheduled.", fill=COLOR_BLUE, font=font_bold_md, anchor="ma")
        draw.text((550, 250), "Enjoy your day!", fill=COLOR_BLACK, font=font_regular_md, anchor="ma")
    else:
        wrap_width = width - timeline_x - 25 - 20
        laid_out = layout_events(
            draw, events, font_regular_sm, font_bold_md, font_regular_sm, wrap_width,
            time_line_h, title_line_h, sub_line_h, row_gap, max_title_lines=2
        )
        display_events, hidden_count = fit_events_to_height(laid_out, bottom_boundary - start_y - 24)

        curr_y = start_y
        row_tops = []
        for item in display_events:
            row_tops.append(curr_y)
            curr_y += item["row_height"]
        content_bottom = curr_y - row_gap

        draw.line((timeline_x, start_y + 10, timeline_x, content_bottom + 10), fill=COLOR_BLACK, width=2)

        for item, row_y in zip(display_events, row_tops):
            dot_color = COLOR_GREEN if item["is_all_day"] else COLOR_BLUE
            draw.ellipse((timeline_x - 6, row_y + 6, timeline_x + 6, row_y + 18),
                         fill=dot_color, outline=COLOR_BLACK, width=2)

            draw.text((timeline_x + 25, row_y), item["time_lbl"], fill=COLOR_RED, font=font_regular_sm)

            line_y = row_y + time_line_h
            for line in item["title_lines"]:
                draw.text((timeline_x + 25, line_y), line, fill=COLOR_BLACK, font=font_bold_md)
                line_y += title_line_h
            for line in item["sub_lines"]:
                draw.text((timeline_x + 25, line_y), line, fill=COLOR_BLUE, font=font_regular_sm)
                line_y += sub_line_h

        if hidden_count:
            draw.text((timeline_x + 25, content_bottom + 10), f"+ {hidden_count} more",
                       fill=COLOR_BLUE, font=font_regular_sm)

    return img

# ---------------------------------------------------------------------------
# Binary Encoding for Spectra 6
# ---------------------------------------------------------------------------
def get_closest_nibble(r: int, g: int, b: int) -> int:
    """Map any RGB value to the closest hardware-supported Spectra 6 color code."""
    min_dist = float('inf')
    best_nibble = 1  # Default to white
    
    for i, color in enumerate(SPECTRA6_REAL_WORLD_RGB):
        dist = (r - color[0])**2 + (g - color[1])**2 + (b - color[2])**2
        if dist < min_dist:
            min_dist = dist
            best_nibble = SPECTRA6_NIBBLE_VALUES[i]
            
    return best_nibble

def pack_row_half(image: Image.Image, y: int, start_x: int, end_x: int) -> bytes:
    """Pack an interval of pixels into 4-bit nibbles (2 pixels per byte)."""
    out = bytearray()
    pixels = image.load()
    width = image.width
    
    for x in range(start_x, end_x, 2):
        r, g, b = pixels[x, y][:3]
        high_nibble = get_closest_nibble(r, g, b)
        
        odd_x = x + 1
        if odd_x < end_x and odd_x < width:
            r2, g2, b2 = pixels[odd_x, y][:3]
            low_nibble = get_closest_nibble(r2, g2, b2)
        else:
            low_nibble = 1  # Pad missing pixel with White (nibble 1)
            
        out.append((high_nibble << 4) | low_nibble)
        
    return bytes(out)

def pack_split_halves(image: Image.Image) -> bytes:
    """Pack portrait/split-half display buffers (e.g. 13.3" 1200x1600)."""
    width, height = image.size
    half = width // 2
    
    left_bytes = bytearray()
    right_bytes = bytearray()
    
    for y in range(height):
        left_bytes.extend(pack_row_half(image, y, 0, half))
        right_bytes.extend(pack_row_half(image, y, half, width))
        
    return bytes(left_bytes) + bytes(right_bytes)

def pack_sequential(image: Image.Image) -> bytes:
    """Pack landscape/sequential display buffers (e.g. 7.3" 800x480)."""
    width, height = image.size
    out = bytearray()
    
    for y in range(height):
        out.extend(pack_row_half(image, y, 0, width))
        
    return bytes(out)

def encode_spectra6_bin(image: Image.Image, layout: str) -> bytes:
    """Convert a rendered PIL Image to the raw packed 4bpp binary format."""
    print(f"Encoding image buffer using layout: {layout}...")
    if layout == "split_half":
        return pack_split_halves(image)
    else:
        return pack_sequential(image)

# ---------------------------------------------------------------------------
# Weather Code Mapper Helper
# ---------------------------------------------------------------------------
def get_weather_desc_and_icon(code: int) -> tuple[str, int]:
    """Map WMO code to friendly string description and simplified icon index."""
    return WMO_WEATHER_CODES.get(code, ("Unknown", 0))

# ---------------------------------------------------------------------------
# Frame REST API Uploader
# ---------------------------------------------------------------------------
def upload_bin_to_frame(frame_ip: str, binary_bytes: bytes) -> bool:
    """Upload raw packed .bin file directly to the frame's /api/image REST API endpoint."""
    url = f"http://{frame_ip}/api/image"
    print(f"Uploading {len(binary_bytes)} bytes to frame at {url}...")
    
    try:
        req = urllib.request.Request(
            url,
            data=binary_bytes,
            headers={"Content-Type": "application/octet-stream"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            status = response.status
            print(f"Upload successful! Frame returned status: {status}")
            return True
    except Exception as e:
        print(f"Error during upload: {e}")
        return False

# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please copy config.example.json to config.json and adjust settings.")
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    # Set timezone
    tz_name = config.get("timezone", "UTC")
    target_tz = get_timezone(tz_name)
    
    # 1. Fetch Calendar Events
    cal_conf = config.get("calendar", {})
    source_type = cal_conf.get("source_type", "ical")
    events = []
    
    if source_type == "ical":
        ical_url = cal_conf.get("ical_url")
        if ical_url:
            events = fetch_ical_events(ical_url, target_tz)
        else:
            print("Error: ical_url is not configured.")
    elif source_type == "ha":
        events = fetch_ha_events(cal_conf, target_tz)
    else:
        print(f"Error: Unknown calendar source_type '{source_type}'.")
        
    # 2. Fetch Weather Forecast
    weather_conf = config.get("weather", {})
    weather = {}
    if weather_conf.get("enabled", True):
        lat = weather_conf.get("latitude")
        lon = weather_conf.get("longitude")
        zip_code = weather_conf.get("zip_code")
        
        if (lat is None or lon is None) and zip_code:
            print(f"Resolving coordinates for location '{zip_code}'...")
            coords = get_coordinates_from_location(zip_code)
            if coords:
                lat, lon = coords
                print(f"Resolved coordinates: {lat}, {lon}")
                
        temp_unit = weather_conf.get("temp_unit", "fahrenheit")
        api_url = weather_conf.get("api_url")
        if lat is not None and lon is not None:
            weather = fetch_weather(lat, lon, temp_unit, api_url)
        else:
            print("Warning: Location coordinates missing for weather forecast.")
            
    # 3. Query Frame Status
    frame_conf = config.get("frame", {})
    frame_ip = frame_conf.get("ip_address", "fraimic.local")
    frame_stats = fetch_frame_info(frame_ip)
    
    # 4. Render Canvas Image
    resolution = frame_conf.get("resolution", [1200, 1600])
    width, height = resolution[0], resolution[1]
    
    print(f"Generating layout ({width}x{height})...")
    # Dispatch layout based on aspect ratio/orientation
    if width > height:
        img = render_landscape(width, height, events, weather, frame_stats, target_tz)
    else:
        img = render_portrait(width, height, events, weather, frame_stats, target_tz)
        
    # Save a PNG preview next to the script for debug/visual verification
    preview_path = os.path.join(script_dir, "agenda_preview.png")
    img.save(preview_path)
    print(f"Saved local PNG preview to {preview_path}")
    
    # 5. Pack binary file
    layout_type = frame_conf.get("layout", "split_half")
    binary_bytes = encode_spectra6_bin(img, layout_type)
    
    # Save local bin backup
    bin_path = os.path.join(script_dir, "agenda.bin")
    with open(bin_path, "wb") as f:
        f.write(binary_bytes)
    print(f"Saved local Spectra 6 binary to {bin_path}")
    
    # 6. Upload
    if frame_stats["connected"]:
        success = upload_bin_to_frame(frame_ip, binary_bytes)
        if success:
            print("Successfully updated Daily Agenda frame!")
        else:
            print("Failed to upload Daily Agenda.")
    else:
        print("Frame is currently offline or unreachable. Skipping REST upload.")

if __name__ == "__main__":
    main()
