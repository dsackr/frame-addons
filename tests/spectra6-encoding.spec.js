const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);

// Regression coverage for a real bug: scripture_of_the_day's encode_spectra6_bin
// (now merged into xotd_renderer.py) had a "split_half" branch that, despite its
// name and comment, packed pixels in plain row-major sequential order --
// identical to the "sequential" branch. On a real split-half panel (e.g. the
// 1200x1600 portrait frame, which expects every row's left-half pixels for the
// whole image followed by every row's right-half pixels) this scrambled the
// image: right content landed on the left, left on the right, and
// adjacent-but-unrelated pixels got packed into the same byte, reading as
// "blurry". daily_agenda's encoder was already correct (see pack_split_halves),
// so this check pins both renderers' encoders to agree byte-for-byte for the
// same image, for both layouts -- a pure byte-count assertion (as xotd.spec.js
// has) can't catch a byte-ordering bug like this since the total length is
// unaffected.
//
// This can't easily be driven through the real render pipeline (that needs
// live/mocked network calls per add-on), so it talks to a small inline Python
// script that imports both renderer modules directly and compares their
// encode_spectra6_bin output for an identical synthetic image.

const ADDONS_DIR = path.join(__dirname, '../addons');
const TMP_SCRIPT_PATH = path.join(__dirname, '_verify_spectra6_encoding_tmp.py');

test.describe('Spectra 6 byte packing', () => {
  test.afterEach(() => {
    if (fs.existsSync(TMP_SCRIPT_PATH)) fs.unlinkSync(TMP_SCRIPT_PATH);
  });

  test('daily_agenda and xotd_renderer encoders agree byte-for-byte', async () => {
    const verifyScript = `
import sys, json, random
sys.path.insert(0, ${JSON.stringify(path.join(ADDONS_DIR, 'daily_agenda'))})
sys.path.insert(0, ${JSON.stringify(path.join(ADDONS_DIR, 'xotd'))})
import agenda_renderer as ar
import xotd_renderer as xr
from PIL import Image

random.seed(42)
# Odd dimensions deliberately exercise the "trailing unpaired pixel" edge case
# in pack_row_half's 2-pixels-per-byte packing.
w, h = 51, 33
palette = list(xr.SPECTRA6_REAL_WORLD_RGB)
img = Image.new("RGB", (w, h))
px = img.load()
for y in range(h):
    for x in range(w):
        px[x, y] = random.choice(palette)

result = {}
for layout in ("split_half", "sequential"):
    b_agenda = ar.encode_spectra6_bin(img, layout)
    b_xotd = xr.encode_spectra6_bin(img, layout)
    result[layout] = {
        "agenda_matches_xotd": b_agenda == b_xotd,
        "length": len(b_xotd),
    }

print("RESULT_JSON:" + json.dumps(result))
`;
    fs.writeFileSync(TMP_SCRIPT_PATH, verifyScript);

    const { stdout, stderr } = await execPromise(`python3 ${TMP_SCRIPT_PATH}`);
    if (stderr) console.error('stderr:', stderr);

    const resultLine = stdout.split('\n').find((l) => l.startsWith('RESULT_JSON:'));
    expect(resultLine).toBeTruthy();
    const result = JSON.parse(resultLine.slice('RESULT_JSON:'.length));

    for (const layout of ['split_half', 'sequential']) {
      expect(result[layout].agenda_matches_xotd, `${layout}: agenda vs xotd`).toBe(true);
    }
    // split_half packs the whole image at 4bpp (2 px/byte): (51*33)/2 rounded
    // up per row-half since pack_row_half pads a trailing odd pixel per half.
    expect(result.split_half.length).toBeGreaterThan(0);
    expect(result.sequential.length).toBeGreaterThan(0);
  });
});
