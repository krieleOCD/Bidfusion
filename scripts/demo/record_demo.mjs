#!/usr/bin/env node
// Records the BidFusion product demo as a video by driving the local UI with
// Playwright. Reads scenes.mjs, injects a visible cursor and a lower-third
// title overlay (the app itself ships no JavaScript and a strict CSP, so the
// browser context bypasses CSP for the overlay only), and writes:
//   <out>/demo.webm          raw recording (1920x1080)
//   <out>/timeline.json      real start/end of every scene in seconds
//   <out>/demo-script.md     narration script with timestamps
//   <out>/demo-script.srt    narration as subtitle cues
//
// Usage: node record_demo.mjs --base-url http://127.0.0.1:8765 --out runtime/demo/2026-09-08
// Env:   DEMO_SPEED=0.2  scales every pause/dwell (dry run)
//        DEMO_HEADED=1   show the browser while recording

import { chromium } from 'playwright';
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { scenes, ACT_LABELS } from './scenes.mjs';

const args = parseArgs(process.argv.slice(2));
const BASE_URL = (args['base-url'] ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
const OUT_DIR = path.resolve(args.out ?? `runtime/demo/${new Date().toISOString().slice(0, 10)}`);
const SPEED = Number(process.env.DEMO_SPEED ?? '1') || 1;
const HEADED = process.env.DEMO_HEADED === '1';
const VOICE_GAP_SECONDS = 0.8;
const LEAD_IN_SECONDS = 1.0;
const WIDTH = 1920;
const HEIGHT = 1080;

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith('--')) {
        out[key] = next;
        i += 1;
      } else {
        out[key] = true;
      }
    }
  }
  return out;
}

const sleep = (seconds) => new Promise((resolve) => setTimeout(resolve, Math.max(0, seconds * 1000 * SPEED)));

// Injected on every navigation. Keeps cursor position and current title in
// sessionStorage so form POSTs and redirects do not reset the overlay.
const OVERLAY_SCRIPT = `
(() => {
  const STYLE = \`
    #__demo-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; margin: -4px 0 0 -4px;
      pointer-events: none; z-index: 2147483646; transform: translate(-50%, -50%);
      border-radius: 50%; background: rgba(0,0,0,.85); border: 3px solid #fff;
      box-shadow: 0 2px 8px rgba(0,0,0,.45); transition: transform .08s ease-out; }
    #__demo-cursor.is-down { transform: translate(-50%, -50%) scale(.7); background: #ff7900; }
    #__demo-lower { position: fixed; left: 40px; bottom: 36px; z-index: 2147483645; pointer-events: none;
      max-width: 60vw; padding: 14px 22px 14px 20px; border-left: 5px solid #ff7900;
      background: rgba(10,10,10,.86); color: #fff; font: 500 22px/1.25 -apple-system, "Helvetica Neue", Arial, sans-serif;
      letter-spacing: .01em; border-radius: 4px; box-shadow: 0 6px 24px rgba(0,0,0,.35);
      opacity: 0; transform: translateY(8px); transition: opacity .35s ease, transform .35s ease; }
    #__demo-lower.is-visible { opacity: 1; transform: translateY(0); }
    #__demo-lower small { display: block; font-size: 12px; font-weight: 600; letter-spacing: .12em;
      text-transform: uppercase; color: #ffb066; margin-bottom: 4px; }
  \`;
  const state = () => {
    try { return JSON.parse(sessionStorage.getItem('__demo') || '{}'); } catch (e) { return {}; }
  };
  const save = (patch) => {
    try { sessionStorage.setItem('__demo', JSON.stringify({ ...state(), ...patch })); } catch (e) {}
  };
  const mount = () => {
    if (!document.body || document.getElementById('__demo-cursor')) return;
    const style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);
    const cursor = document.createElement('div');
    cursor.id = '__demo-cursor';
    const lower = document.createElement('div');
    lower.id = '__demo-lower';
    document.body.appendChild(cursor);
    document.body.appendChild(lower);
    const s = state();
    cursor.style.left = (s.x ?? ${WIDTH / 2}) + 'px';
    cursor.style.top = (s.y ?? ${HEIGHT / 2}) + 'px';
    if (s.title) {
      lower.innerHTML = '<small></small><span></span>';
      lower.querySelector('small').textContent = s.kicker || '';
      lower.querySelector('span').textContent = s.title;
      lower.classList.add('is-visible');
    }
  };
  document.addEventListener('mousemove', (e) => {
    const c = document.getElementById('__demo-cursor');
    if (!c) return;
    c.style.left = e.clientX + 'px';
    c.style.top = e.clientY + 'px';
    save({ x: e.clientX, y: e.clientY });
  }, true);
  document.addEventListener('mousedown', () => document.getElementById('__demo-cursor')?.classList.add('is-down'), true);
  document.addEventListener('mouseup', () => document.getElementById('__demo-cursor')?.classList.remove('is-down'), true);
  window.__demo = {
    setTitle(title, kicker) {
      save({ title, kicker });
      const lower = document.getElementById('__demo-lower');
      if (!lower) return;
      lower.classList.remove('is-visible');
      setTimeout(() => {
        lower.innerHTML = '<small></small><span></span>';
        lower.querySelector('small').textContent = kicker || '';
        lower.querySelector('span').textContent = title;
        lower.classList.add('is-visible');
      }, 220);
    },
    hideTitle() {
      save({ title: '', kicker: '' });
      document.getElementById('__demo-lower')?.classList.remove('is-visible');
    },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
`;

function resolveLocator(page, spec) {
  if (typeof spec === 'string') spec = { text: spec };
  let loc;
  if (spec.role) loc = page.getByRole(spec.role, { name: spec.name, exact: spec.exact ?? false });
  else if (spec.label) loc = page.getByLabel(spec.label, { exact: spec.exact ?? false });
  else if (spec.summary) loc = page.locator('summary', { hasText: spec.summary });
  else if (spec.text) loc = page.getByText(spec.text, { exact: spec.exact ?? false });
  else if (spec.css) loc = page.locator(spec.css);
  else throw new Error(`Unknown locator spec ${JSON.stringify(spec)}`);
  if (spec.nth !== undefined) loc = loc.nth(spec.nth);
  return loc.first();
}

async function moveTo(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error('Element has no bounding box');
  const x = box.x + Math.min(box.width / 2, 160);
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y, { steps: 28 });
  await sleep(0.25);
}

async function clickAt(page, locator) {
  await moveTo(page, locator);
  const nav = page.waitForLoadState('load').catch(() => {});
  await locator.click();
  await nav;
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function smoothScroll(page, pixels) {
  const stepCount = 16;
  const per = pixels / stepCount;
  for (let i = 0; i < stepCount; i += 1) {
    await page.mouse.wheel(0, per);
    await sleep(0.04);
  }
}

async function runStep(page, step) {
  if (step.goto !== undefined) {
    await page.goto(BASE_URL + step.goto, { waitUntil: 'networkidle' });
    return;
  }
  if (step.pause !== undefined) return sleep(step.pause);
  if (step.scroll !== undefined) return smoothScroll(page, step.scroll);
  if (step.scrollTo !== undefined) {
    const loc = resolveLocator(page, step.scrollTo);
    await loc.evaluate((el) => el.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    await sleep(0.9);
    await page.mouse.wheel(0, -90);
    await sleep(0.3);
    return;
  }
  if (step.click !== undefined) return clickAt(page, resolveLocator(page, step.click));
  if (step.hover !== undefined) return moveTo(page, resolveLocator(page, step.hover));
  if (step.fill !== undefined) {
    const loc = resolveLocator(page, step.fill);
    await moveTo(page, loc);
    await loc.click();
    await loc.pressSequentially(step.value, { delay: 35 * SPEED });
    return;
  }
  if (step.select !== undefined) {
    const loc = resolveLocator(page, step.select);
    await moveTo(page, loc);
    await loc.selectOption(step.value);
    return;
  }
  throw new Error(`Unknown step ${JSON.stringify(step)}`);
}

async function loadVoiceManifest() {
  const file = path.join(OUT_DIR, 'voice', 'manifest.json');
  if (!existsSync(file)) return {};
  return JSON.parse(await readFile(file, 'utf8'));
}

function fmt(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

function srtTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.round((seconds - Math.floor(seconds)) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function writeScript(timeline) {
  const lines = [
    '# BidFusion product demo — narration script',
    '',
    `Recorded ${new Date().toISOString()} against ${BASE_URL}. Internal use only: the Knowledge scenes show real MTD golden-knowledge data.`,
    '',
    'Timestamps are measured from the recording, so voice-over cues align with the video. Status says what the page really is.',
    '',
    '| # | In | Out | Screen | Status | Title |',
    '|---|---|---|---|---|---|',
  ];
  for (const t of timeline) {
    lines.push(`| ${t.index} | ${fmt(t.start)} | ${fmt(t.end)} | \`${t.url}\` | ${t.status} | ${t.title} |`);
  }
  lines.push('', '## Scenes', '');
  for (const t of timeline) {
    lines.push(`### ${t.index}. ${t.title}  (${fmt(t.start)} – ${fmt(t.end)})`, '');
    lines.push(`- Screen: \`${t.url}\``);
    lines.push(`- Status: ${t.status}`);
    lines.push(`- On screen: ${t.onScreen}`);
    if (t.voiceSeconds) lines.push(`- Voice clip: ${t.voiceSeconds.toFixed(1)} s`);
    lines.push('', `> ${t.narration}`, '');
  }
  return lines.join('\n');
}

function writeSrt(timeline) {
  return timeline
    .map((t, i) => `${i + 1}\n${srtTime(t.start)} --> ${srtTime(t.end - 0.2)}\n${t.narration}\n`)
    .join('\n');
}

function describeSteps(steps) {
  const parts = [];
  for (const s of steps) {
    if (s.goto) parts.push(`open ${s.goto}`);
    else if (s.click) parts.push(`click ${describeSpec(s.click)}`);
    else if (s.fill) parts.push(`type "${s.value}" into ${describeSpec(s.fill)}`);
    else if (s.select) parts.push(`choose ${s.value} in ${describeSpec(s.select)}`);
    else if (s.scrollTo) parts.push(`scroll to ${describeSpec(s.scrollTo)}`);
    else if (s.scroll) parts.push('scroll');
  }
  return parts.join(', ');
}

function describeSpec(spec) {
  if (typeof spec === 'string') return `"${spec}"`;
  if (spec.name) return `"${spec.name instanceof RegExp ? spec.name.source.replace(/[\^$]/g, '') : spec.name}"`;
  if (spec.label) return `"${spec.label}"`;
  if (spec.summary) return `"${spec.summary}"`;
  if (spec.text) return `"${spec.text}"`;
  return spec.css;
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const voice = await loadVoiceManifest();
  const browser = await chromium.launch({ headless: !HEADED });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT_DIR, size: { width: WIDTH, height: HEIGHT } },
    bypassCSP: true,
    colorScheme: 'light',
    reducedMotion: 'no-preference',
  });
  await context.addInitScript(OVERLAY_SCRIPT);
  const page = await context.newPage();
  const videoStart = Date.now();
  const now = () => (Date.now() - videoStart) / 1000;

  await page.goto(BASE_URL + scenes[0].url, { waitUntil: 'networkidle' });
  await page.mouse.move(WIDTH / 2, HEIGHT / 2);
  await sleep(LEAD_IN_SECONDS);

  const timeline = [];
  for (const [i, scene] of scenes.entries()) {
    const clipSeconds = voice[scene.id]?.seconds ?? 0;
    const dwell = Math.max(scene.minDwell, clipSeconds ? clipSeconds + VOICE_GAP_SECONDS : 0);
    const start = now();
    process.stdout.write(`[${fmt(start)}] ${scene.id} (dwell ${dwell.toFixed(1)} s)\n`);
    await page.evaluate(([t, k]) => window.__demo?.setTitle(t, k), [scene.title, ACT_LABELS[scene.act]]);
    for (const step of scene.steps) {
      try {
        await runStep(page, step);
      } catch (error) {
        throw new Error(`Scene ${scene.id}, step ${JSON.stringify(step)}: ${error.message}`);
      }
    }
    const elapsed = now() - start;
    const remaining = dwell * SPEED - elapsed;
    if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining * 1000));
    const end = now();
    timeline.push({
      index: i + 1,
      id: scene.id,
      title: scene.title,
      status: scene.status,
      act: scene.act,
      url: scene.url,
      start,
      end,
      dwell,
      voiceSeconds: clipSeconds,
      onScreen: describeSteps(scene.steps),
      narration: scene.narration,
    });
  }
  await page.evaluate(() => window.__demo?.hideTitle());
  await sleep(1.2);
  const total = now();

  const video = page.video();
  await page.close();
  await context.close();
  await browser.close();
  const rawPath = await video.path();
  const webm = path.join(OUT_DIR, 'demo.webm');
  await rename(rawPath, webm);

  await writeFile(path.join(OUT_DIR, 'timeline.json'), JSON.stringify({ baseUrl: BASE_URL, speed: SPEED, total, scenes: timeline }, null, 2));
  await writeFile(path.join(OUT_DIR, 'demo-script.md'), writeScript(timeline));
  await writeFile(path.join(OUT_DIR, 'demo-script.srt'), writeSrt(timeline));
  process.stdout.write(`Recorded ${fmt(total)} → ${webm}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
