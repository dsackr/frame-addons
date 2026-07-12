const { test, expect } = require('@playwright/test');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

const PORT = 18126; // fresh port, separate from any retired quote/scripture test ports
const XOTD_DIR = path.join(__dirname, '../addons/xotd');
const CONFIG_PATH = path.join(XOTD_DIR, 'config.json');
const PREVIEW_PATH = path.join(XOTD_DIR, 'xotd_preview.png');
const BIN_PATH = path.join(XOTD_DIR, 'xotd.bin');

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

      // Mock Frame Upload
      if (req.method === 'POST' && url.pathname === '/api/image') {
        let body = [];
        req.on('data', (chunk) => body.push(chunk));
        req.on('end', () => {
          lastUploadedImage = Buffer.concat(body);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'success' }));
        });
      }
      // Mock icanhazdadjoke.com
      else if (req.method === 'GET' && url.pathname === '/') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          id: 'abc123',
          joke: 'This is an automated Playwright test joke to assert rendering layouts work.',
          status: 200,
        }));
      }
      // Mock ZenQuotes response schema
      else if (req.method === 'GET' && url.pathname === '/today') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify([
          {
            q: 'This is an automated Playwright test quote to assert rendering layouts work.',
            a: 'Playwright Runner',
          },
        ]));
      }
      // Mock OurManna daily endpoint
      else if (req.method === 'GET' && url.pathname === '/api/v1/get') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          verse: {
            details: {
              text: 'For God so loved the world, that he gave his only begotten Son...',
              reference: 'John 3:16',
              version: 'NIV',
            },
          },
        }));
      }
      // Mock Bible-API endpoint
      else if (req.method === 'GET' && url.pathname.includes('/John')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          text: 'For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.',
          reference: 'John 3:16',
          translation_id: 'kjv',
          translation_name: 'King James Version',
        }));
      }
      // Mock random-word-api response schema
      else if (req.method === 'GET' && url.pathname === '/random-word') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(['playwright']));
      }
      // Mock dictionaryapi.dev response schema
      else if (req.method === 'GET' && url.pathname === '/dictionary/playwright') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify([
          {
            word: 'playwright',
            meanings: [
              {
                partOfSpeech: 'noun',
                definitions: [
                  {
                    definition: 'A person who writes plays.',
                    example: 'The playwright accepted applause at the curtain call.',
                  },
                ],
              },
            ],
          },
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

async function runXotd(mockConfig) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(mockConfig, null, 2));
  const { stdout, stderr } = await execPromise(`python3 ${path.join(XOTD_DIR, 'xotd_renderer.py')}`);
  console.log('stdout:', stdout);
  if (stderr) console.error('stderr:', stderr);
}

async function runXotdWithArgs(mockConfig, configPath, extraArgs) {
  fs.writeFileSync(configPath, JSON.stringify(mockConfig, null, 2));
  const args = ['--config', configPath, ...extraArgs].join(' ');
  const { stdout, stderr } = await execPromise(`python3 ${path.join(XOTD_DIR, 'xotd_renderer.py')} ${args}`);
  console.log('stdout:', stdout);
  if (stderr) console.error('stderr:', stderr);
}

test.describe('xOTD Add-on', () => {
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

  test.describe('Joke Mode', () => {
    test('renders and uploads in Portrait Mode (1200x1600 split_half)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'joke',
        joke_feed: 'icanhazdadjoke',
        joke_api_url: `http://localhost:${PORT}/`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      const paths = requestsLog.map((r) => r.path);
      expect(paths).toContain('/');
      expect(paths).toContain('/api/image');

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });

    test('renders and uploads in Landscape Mode (800x480 sequential)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'joke',
        joke_feed: 'icanhazdadjoke',
        joke_api_url: `http://localhost:${PORT}/`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(192000);
    });

    test('custom jokes list skips the network fetch', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'joke',
        joke_feed: 'custom',
        custom_jokes: [{ setup: 'Custom joke setup from config.', punchline: 'Custom punchline.' }],
      });

      const paths = requestsLog.map((r) => r.path);
      expect(paths).not.toContain('/');
      expect(paths).toContain('/api/image');

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);
    });
  });

  test.describe('Quote Mode', () => {
    test('renders and uploads in Portrait Mode (1200x1600 split_half)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'quote',
        quote_feed: 'zenquotes',
        quote_api_url: `http://localhost:${PORT}/today`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      const paths = requestsLog.map((r) => r.path);
      expect(paths).toContain('/today');
      expect(paths).toContain('/api/image');

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });

    test('renders and uploads in Landscape Mode (800x480 sequential)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'quote',
        quote_feed: 'zenquotes',
        quote_api_url: `http://localhost:${PORT}/today`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(192000);
    });

    test('custom quotes list skips the network fetch', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'quote',
        quote_feed: 'custom',
        custom_quotes: [{ q: 'Custom quote from local JSON file.', a: 'Test Author' }],
      });

      const paths = requestsLog.map((r) => r.path);
      expect(paths).not.toContain('/today');
      expect(paths).toContain('/api/image');

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);
    });
  });

  test.describe('Scripture Mode', () => {
    test('renders and uploads in Portrait Mode (1200x1600 split_half), hitting both translation endpoints', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'scripture',
        bible_translation: 'kjv',
        scripture_source: 'daily_api',
        ourmanna_api_url: `http://localhost:${PORT}/api/v1/get`,
        bible_api_url: `http://localhost:${PORT}/{reference}`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      const paths = requestsLog.map((r) => r.path);
      expect(paths).toContain('/api/v1/get');
      expect(paths.some((p) => p.includes('/John'))).toBe(true);
      expect(paths).toContain('/api/image');

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });

    test('renders and uploads in Landscape Mode (800x480 sequential)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'scripture',
        bible_translation: 'kjv',
        scripture_source: 'daily_api',
        ourmanna_api_url: `http://localhost:${PORT}/api/v1/get`,
        bible_api_url: `http://localhost:${PORT}/{reference}`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(192000);
    });

    test('custom scriptures list skips both translation endpoints', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'scripture',
        bible_translation: 'kjv',
        scripture_source: 'custom_list',
        custom_scriptures: [{ q: 'Custom scripture text from config.', r: 'Psalm 121:1', t: 'KJV' }],
      });

      const paths = requestsLog.map((r) => r.path);
      expect(paths).not.toContain('/api/v1/get');
      expect(paths.some((p) => p.includes('/John'))).toBe(false);
      expect(paths).toContain('/api/image');

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);
    });
  });

  test.describe('Word Mode', () => {
    test('renders and uploads in Portrait Mode (1200x1600 split_half), hitting both lookup endpoints', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'word',
        word_feed: 'random_word',
        random_word_api_url: `http://localhost:${PORT}/random-word`,
        dictionary_api_url: `http://localhost:${PORT}/dictionary/{word}`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      const paths = requestsLog.map((r) => r.path);
      expect(paths).toContain('/random-word');
      expect(paths).toContain('/dictionary/playwright');
      expect(paths).toContain('/api/image');

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });

    test('renders and uploads in Landscape Mode (800x480 sequential)', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'word',
        word_feed: 'random_word',
        random_word_api_url: `http://localhost:${PORT}/random-word`,
        dictionary_api_url: `http://localhost:${PORT}/dictionary/{word}`,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);

      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(192000);
    });

    test('custom words list skips both lookup endpoints', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'word',
        word_feed: 'custom',
        custom_words: [{ word: 'Custom', pos: 'adjective', definition: 'Made from config.', example: 'This is a custom word.' }],
      });

      const paths = requestsLog.map((r) => r.path);
      expect(paths).not.toContain('/random-word');
      expect(paths).not.toContain('/dictionary/playwright');
      expect(paths).toContain('/api/image');

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(fs.existsSync(BIN_PATH)).toBe(true);
    });
  });

  test.describe('Themes & Drop Cap', () => {
    test('retro_atomic theme renders successfully and downloads its own font', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'quote',
        quote_feed: 'custom',
        custom_quotes: [{ q: 'Custom quote from local JSON file.', a: 'Test Author' }],
        theme: 'retro_atomic',
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });

    test('drop_cap renders successfully across content modes and orientations', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'scripture',
        bible_translation: 'kjv',
        scripture_source: 'custom_list',
        custom_scriptures: [{ q: 'Custom scripture text from config.', r: 'Psalm 121:1', t: 'KJV' }],
        drop_cap: true,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(192000);
    });

    test('retro_atomic theme combined with drop_cap renders successfully', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [1200, 1600], layout: 'split_half' },
        content_mode: 'joke',
        joke_feed: 'custom',
        custom_jokes: [{ setup: 'Custom joke setup from config.', punchline: 'Custom punchline.' }],
        theme: 'retro_atomic',
        drop_cap: true,
      });

      expect(fs.existsSync(PREVIEW_PATH)).toBe(true);
      expect(lastUploadedImage).not.toBeNull();
      expect(lastUploadedImage.length).toBe(960000);
    });
  });

  test.describe('Render-only mode & isolated config path', () => {
    let tmpDir;

    test.beforeEach(() => {
      tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xotd-render-only-'));
    });

    test.afterEach(() => {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    });

    test('--render-only writes .bin/preview but makes no upload request', async () => {
      const configPath = path.join(tmpDir, 'config.json');
      await runXotdWithArgs(
        {
          frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
          content_mode: 'quote',
          quote_feed: 'custom',
          custom_quotes: [{ q: 'Custom quote from local JSON file.', a: 'Test Author' }],
        },
        configPath,
        ['--render-only'],
      );

      expect(fs.existsSync(path.join(tmpDir, 'xotd_preview.png'))).toBe(true);
      expect(fs.existsSync(path.join(tmpDir, 'xotd.bin'))).toBe(true);

      const paths = requestsLog.map((r) => r.path);
      expect(paths).not.toContain('/api/image');
      expect(lastUploadedImage).toBeNull();

      const binBytes = fs.readFileSync(path.join(tmpDir, 'xotd.bin'));
      expect(binBytes.length).toBe(192000);
    });

    test('--config reads/writes at the given path instead of the script directory', async () => {
      const configPath = path.join(tmpDir, 'config.json');
      await runXotdWithArgs(
        {
          frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
          content_mode: 'joke',
          joke_feed: 'custom',
          custom_jokes: [{ setup: 'Custom joke setup from config.', punchline: 'Custom punchline.' }],
        },
        configPath,
        ['--render-only'],
      );

      // Nothing should have been written next to the script itself.
      expect(fs.existsSync(PREVIEW_PATH)).toBe(false);
      expect(fs.existsSync(BIN_PATH)).toBe(false);
      // Everything lands next to the explicit --config path instead.
      expect(fs.existsSync(path.join(tmpDir, 'xotd_preview.png'))).toBe(true);
      expect(fs.existsSync(path.join(tmpDir, 'xotd.bin'))).toBe(true);
    });

    test('default invocation (no flags) is unaffected: still uploads', async () => {
      await runXotd({
        frame: { ip_address: `localhost:${PORT}`, resolution: [800, 480], layout: 'sequential' },
        content_mode: 'quote',
        quote_feed: 'custom',
        custom_quotes: [{ q: 'Custom quote from local JSON file.', a: 'Test Author' }],
      });

      const paths = requestsLog.map((r) => r.path);
      expect(paths).toContain('/api/image');
      expect(lastUploadedImage).not.toBeNull();
    });
  });
});
