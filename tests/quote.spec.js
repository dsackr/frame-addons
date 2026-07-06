const { test, expect } = require('@playwright/test');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

const PORT = 18124; // separate port to avoid collision if run concurrently
const QUOTE_DIR = path.join(__dirname, '../addons/quote_of_the_day');
const CONFIG_PATH = path.join(QUOTE_DIR, 'config.json');
const PREVIEW_PATH = path.join(QUOTE_DIR, 'quote_preview.png');
const BIN_PATH = path.join(QUOTE_DIR, 'quote.bin');

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
          battery: { percent: 99, charging: true },
          wifi: { rssi: -45, ip: '127.0.0.1' },
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
      // Mock Quote API (ZenQuotes response schema)
      else if (req.method === 'GET' && url.pathname === '/today') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify([
          {
            q: "This is an automated Playwright test quote to assert rendering layouts work.",
            a: "Playwright Runner"
          }
        ]));
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

test.describe('Quote of the Day Add-on Tests', () => {
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

  test('should render and upload quote successfully in Portrait Mode (1200x1600 split_half)', async () => {
    // 1. Create a config.json pointing to our mock server
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [1200, 1600],
        layout: "split_half"
      },
      quote_source: "api",
      quote_api_url: `http://localhost:${PORT}/today`,
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run the quote_renderer.py script
    console.log("Running quote_renderer.py in Portrait mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(QUOTE_DIR, 'quote_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    // Check files were generated
    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    // Check mock server logged requests
    const paths = requestsLog.map((r) => r.path);
    expect(paths).toContain('/today');
    expect(paths).toContain('/api/image');

    // Portrait 1200x1600 4bpp split_half should be exactly 1200 * 1600 / 2 = 960,000 bytes
    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(960000);
  });

  test('should render and upload quote successfully in Landscape Mode (800x480 sequential)', async () => {
    // 1. Create a config.json pointing to our mock server (landscape, sequential)
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      quote_source: "api",
      quote_api_url: `http://localhost:${PORT}/today`,
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run the quote_renderer.py script
    console.log("Running quote_renderer.py in Landscape mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(QUOTE_DIR, 'quote_renderer.py')}`);
    
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

  test('should fall back to custom quotes configured in JSON', async () => {
    // 1. Create a config.json specifying quote_source: "custom"
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      quote_source: "custom",
      timezone: "America/Los_Angeles",
      custom_quotes: [
        {
          q: "Custom quote from local JSON file.",
          a: "Test Author"
        }
      ]
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run the quote_renderer.py script
    console.log("Running quote_renderer.py with custom source...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(QUOTE_DIR, 'quote_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    // Assert that the API was NOT hit, but the image upload was
    const paths = requestsLog.map((r) => r.path);
    expect(paths).not.toContain('/today');
    expect(paths).toContain('/api/image');

    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);
  });
});
