#!/usr/bin/env node
// Captures the README screenshots from the local UI on the repository's own
// synthetic `rfp-minimal` package. Drives the same click path as the demo
// recorder (select package, run security checks, run full analysis) and
// stores one PNG per page below docs/assets/screenshots/.
//
// Only synthetic-fixture pages are captured. Golden Knowledge pages render a
// local pilot store derived from real internal documents and are deliberately
// not part of this script.
//
// Usage: node capture_screenshots.mjs --base-url http://127.0.0.1:8765 --out docs/assets/screenshots

import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const args = parseArgs(process.argv.slice(2));
const BASE_URL = (args['base-url'] ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const OUT_DIR = path.resolve(args.out ?? 'docs/assets/screenshots');
const VIEWPORT = { width: 1440, height: 900 };

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith('--')) {
        out[a.slice(2)] = next;
        i += 1;
      } else {
        out[a.slice(2)] = true;
      }
    }
  }
  return out;
}

async function shot(page, name, options = {}) {
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: false, ...options });
  console.log(`captured ${name}.png (${page.url()})`);
}

await mkdir(OUT_DIR, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1.5, colorScheme: 'light' });
const page = await context.newPage();

try {
  // 1. Product overview
  await page.goto(`${BASE_URL}/overview`);
  await shot(page, 'overview');

  // 2. Intake: run the synthetic package through the security gate and the full pipeline
  await page.goto(`${BASE_URL}/`);
  await page.locator('input[name="package"][value="rfp-minimal"]').check();
  await page.getByRole('button', { name: 'Run security checks' }).click();
  await page.waitForURL(/\/runs\//);
  await page.getByRole('button', { name: 'Run full analysis' }).click();
  await page.waitForURL(/\/runs\//);
  await page.getByRole('heading', { name: 'Where this bid stands' }).waitFor();
  await shot(page, 'bid-command-center');

  // 3. Working package (structured view)
  await page.locator('.bid-context-nav a[href$="/working-package"]').click();
  await page.waitForURL(/working-package/);
  await shot(page, 'working-package');

  // 4. Extraction quality (frozen evaluation record)
  await page.goto(`${BASE_URL}/extraction-quality`);
  await shot(page, 'extraction-quality');
} finally {
  await browser.close();
}
