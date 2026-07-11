const { test, expect } = require('@playwright/test');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

const PORT = 18123;
const AGENDA_DIR = path.join(__dirname, '../addons/daily_agenda');
const CONFIG_PATH = path.join(AGENDA_DIR, 'config.json');
const PREVIEW_PATH = path.join(AGENDA_DIR, 'agenda_preview.png');
const BIN_PATH = path.join(AGENDA_DIR, 'agenda.bin');

let mockServer;
let lastUploadedImage = null;
let requestsLog = [];

function startMockServer() {
  lastUploadedImage = null;
  requestsLog = [];
  
  return new Promise((resolve) => {
    mockServer = http.createServer((req, res) => {
      const url = new URL(req.url, `http://${req.headers.host}`);
      requestsLog.push({ method: req.method, path: url.pathname, query: url.search });

      // Mock Frame Info
      if (req.method === 'GET' && url.pathname === '/api/info') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          battery: { percent: 82, charging: false },
          wifi: { rssi: -62, ip: '127.0.0.1' },
          firmware_version: '1.0.0'
        }));
      } 
      // Mock Frame Upload
      else if (req.method === 'POST' && url.pathname === '/api/image') {
        let body = [];
        req.on('data', (chunk) => body.push(chunk));
        req.on('end', () => {
          lastUploadedImage = Buffer.concat(body);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: "success" }));
        });
      } 
      // Mock Open-Meteo Weather API
      else if (req.method === 'GET' && url.pathname === '/v1/forecast') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          current: { temperature_2m: 72, weather_code: 0 },
          daily: {
            weather_code: [0],
            temperature_2m_max: [76],
            temperature_2m_min: [55]
          }
        }));
      } 
      // Mock Calendar iCal File
      else if (req.method === 'GET' && url.pathname === '/calendar.ics') {
        const today = new Date();
        const formatDate = (d) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
        
        // Generate mock start and end times for today
        const start = new Date(today);
        start.setHours(9, 30, 0, 0);
        const end = new Date(today);
        end.setHours(10, 30, 0, 0);
        
        const icsData = `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Mock Calendar//EN
BEGIN:VEVENT
SUMMARY:Important Project Sync
DTSTART:${formatDate(start)}
DTEND:${formatDate(end)}
LOCATION:Meeting Room A
DESCRIPTION:Discussing new features
END:VEVENT
BEGIN:VEVENT
SUMMARY:All Day Event Example
DTSTART;VALUE=DATE:${start.toISOString().split('T')[0].replace(/-/g, '')}
DTEND;VALUE=DATE:${end.toISOString().split('T')[0].replace(/-/g, '')}
LOCATION:Home Office
DESCRIPTION:Focus time
END:VEVENT
END:VCALENDAR`;

        res.writeHead(200, { 'Content-Type': 'text/calendar' });
        res.end(icsData);
      }
      // Mock Home Assistant REST calendar API -- /api/calendars/<entity_id>
      else if (req.method === 'GET' && url.pathname.startsWith('/api/calendars/')) {
        const entity = decodeURIComponent(url.pathname.slice('/api/calendars/'.length));
        const today = new Date();
        const start = new Date(today);
        start.setHours(13, 0, 0, 0);
        const end = new Date(today);
        end.setHours(14, 0, 0, 0);

        const eventsByEntity = {
          'calendar.personal': [{
            summary: 'Personal Calendar Event',
            start: { dateTime: start.toISOString() },
            end: { dateTime: end.toISOString() },
          }],
          'calendar.family': [{
            summary: 'Family Calendar Event',
            start: { dateTime: start.toISOString() },
            end: { dateTime: end.toISOString() },
          }],
        };

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(eventsByEntity[entity] || []));
      } else {
        res.writeHead(404);
        res.end('Not Found');
      }
    });

    mockServer.listen(PORT, () => {
      resolve();
    });
  });
}

function stopMockServer() {
  return new Promise((resolve) => {
    if (mockServer) {
      mockServer.close(() => {
        resolve();
      });
    } else {
      resolve();
    }
  });
}

test.describe('Daily Agenda Add-on Tests', () => {
  test.beforeEach(async () => {
    await startMockServer();
  });

  test.afterEach(async () => {
    await stopMockServer();
    // Clean up temporary config and output files if they exist
    [CONFIG_PATH, PREVIEW_PATH, BIN_PATH].forEach((file) => {
      if (fs.existsSync(file)) {
        fs.unlinkSync(file);
      }
    });
  });

  test('should render and upload successfully in Portrait Mode (1200x1600 split_half)', async () => {
    // 1. Create a config.json pointing to our mock server
    const mockConfig = {
      calendar: {
        source_type: "ical",
        ical_url: `http://localhost:${PORT}/calendar.ics`
      },
      weather: {
        enabled: true,
        latitude: 37.7749,
        longitude: -122.4194,
        temp_unit: "fahrenheit",
        api_url: `http://localhost:${PORT}/v1/forecast`
      },
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [1200, 1600],
        layout: "split_half"
      },
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run the agenda_renderer.py script
    console.log("Running agenda_renderer.py in Portrait mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(AGENDA_DIR, 'agenda_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    // Check files were generated
    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    // Check mock server logged requests
    const paths = requestsLog.map((r) => r.path);
    expect(paths).toContain('/calendar.ics');
    expect(paths).toContain('/v1/forecast');
    expect(paths).toContain('/api/info');
    expect(paths).toContain('/api/image');

    // Portrait 1200x1600 4bpp split_half should be exactly 1200 * 1600 / 2 = 960,000 bytes
    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(960000);
  });

  test('should render and upload successfully in Landscape Mode (800x480 sequential)', async () => {
    // 1. Create a config.json pointing to our mock server (landscape, sequential)
    const mockConfig = {
      calendar: {
        source_type: "ical",
        ical_url: `http://localhost:${PORT}/calendar.ics`
      },
      weather: {
        enabled: true,
        latitude: 37.7749,
        longitude: -122.4194,
        temp_unit: "fahrenheit",
        api_url: `http://localhost:${PORT}/v1/forecast`
      },
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run the agenda_renderer.py script
    console.log("Running agenda_renderer.py in Landscape mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(AGENDA_DIR, 'agenda_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    // Check files were generated
    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    // Landscape 800x480 4bpp sequential should be exactly 800 * 480 / 2 = 192,000 bytes
    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(192000);
  });

  test('should merge events from multiple configured calendars (source_type "ha")', async () => {
    // "Configured Calendars" lets a user pick more than one calendar.* entity
    // (Google Calendar, Local Calendar, CalDAV, whatever) -- ha_calendar_entities
    // is a list, and events from every entity in it should be fetched and merged.
    const mockConfig = {
      calendar: {
        source_type: "ha",
        ha_url: `http://localhost:${PORT}`,
        ha_token: "test-token",
        ha_calendar_entities: ["calendar.personal", "calendar.family"]
      },
      weather: {
        enabled: true,
        latitude: 37.7749,
        longitude: -122.4194,
        temp_unit: "fahrenheit",
        api_url: `http://localhost:${PORT}/v1/forecast`
      },
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    console.log("Running agenda_renderer.py with multiple HA calendar entities...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(AGENDA_DIR, 'agenda_renderer.py')}`);

    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    // Both entities must have been queried -- proof the list was actually
    // iterated, not just the first one.
    const paths = requestsLog.map((r) => r.path);
    expect(paths).toContain('/api/calendars/calendar.personal');
    expect(paths).toContain('/api/calendars/calendar.family');

    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(192000);
  });
});
