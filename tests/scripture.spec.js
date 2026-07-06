const { test, expect } = require('@playwright/test');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

const PORT = 18125; // separate port to avoid collision
const SCRIPTURE_DIR = path.join(__dirname, '../addons/scripture_of_the_day');
const CONFIG_PATH = path.join(SCRIPTURE_DIR, 'config.json');
const PREVIEW_PATH = path.join(SCRIPTURE_DIR, 'scripture_preview.png');
const BIN_PATH = path.join(SCRIPTURE_DIR, 'scripture.bin');

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
      // Mock OurManna daily endpoint
      else if (req.method === 'GET' && url.pathname === '/api/v1/get') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          verse: {
            details: {
              text: "For God so loved the world, that he gave his only begotten Son...",
              reference: "John 3:16",
              version: "NIV"
            }
          }
        }));
      }
      // Mock Bible-API endpoint
      else if (req.method === 'GET' && url.pathname.includes('/John')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          text: "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.",
          reference: "John 3:16",
          translation_id: "kjv",
          translation_name: "King James Version"
        }));
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

test.describe('Scripture of the Day Add-on Tests', () => {
  test.beforeEach(async () => {
    await startMockServer();
  });

  test.afterEach(async () => {
    await stopMockServer();
    [CONFIG_PATH, PREVIEW_PATH, BIN_PATH].forEach((file) => {
      if (fs.existsSync(file)) {
        fs.unlinkSync(file);
      }
    });
  });

  test('should render and upload scripture successfully in Portrait Mode (1200x1600 split_half)', async () => {
    // 1. Create config pointing to mock server
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [1200, 1600],
        layout: "split_half"
      },
      bible_translation: "kjv",
      scripture_source: "daily_api",
      ourmanna_api_url: `http://localhost:${PORT}/api/v1/get`,
      bible_api_url: `http://localhost:${PORT}/{reference}`,
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run scripture_renderer.py
    console.log("Running scripture_renderer.py in Portrait mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(SCRIPTURE_DIR, 'scripture_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    const paths = requestsLog.map((r) => r.path);
    expect(paths).toContain('/api/v1/get');
    expect(paths.some(p => p.includes('/John'))).toBe(true);
    expect(paths).toContain('/api/image');

    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(960000);
  });

  test('should render and upload scripture successfully in Landscape Mode (800x480 sequential)', async () => {
    // 1. Create config
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      bible_translation: "kjv",
      scripture_source: "daily_api",
      ourmanna_api_url: `http://localhost:${PORT}/api/v1/get`,
      bible_api_url: `http://localhost:${PORT}/{reference}`,
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run scripture_renderer.py
    console.log("Running scripture_renderer.py in Landscape mode...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(SCRIPTURE_DIR, 'scripture_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);

    expect(lastUploadedImage).not.toBeNull();
    expect(lastUploadedImage.length).toBe(192000);
  });

  test('should fall back to custom scriptures configured in JSON', async () => {
    // 1. Create config
    const mockConfig = {
      frame: {
        ip_address: `localhost:${PORT}`,
        resolution: [800, 480],
        layout: "sequential"
      },
      bible_translation: "kjv",
      scripture_source: "custom_list",
      custom_scriptures: [
        {
          q: "Custom scripture text from config.",
          r: "Psalm 121:1",
          t: "KJV"
        }
      ],
      timezone: "America/Los_Angeles"
    };

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));

    // 2. Run scripture_renderer.py
    console.log("Running scripture_renderer.py with custom list...");
    const { stdout, stderr } = await execPromise(`python3 ${path.join(SCRIPTURE_DIR, 'scripture_renderer.py')}`);
    
    console.log("stdout:", stdout);
    if (stderr) console.error("stderr:", stderr);

    // 3. Assertions
    const paths = requestsLog.map((r) => r.path);
    expect(paths).not.toContain('/api/v1/get');
    expect(paths).not.toContain('/John');
    expect(paths).toContain('/api/image');

    expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
    expect(fs.existsSync(BIN_PATH)).toBe(true);
  });
});
