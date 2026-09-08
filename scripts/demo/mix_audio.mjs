#!/usr/bin/env node
// Places every voice clip at its scene start (from timeline.json) and muxes
// the result with the silent H.264 video.
// Usage: node mix_audio.mjs --out runtime/demo/2026-09-08

import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';

const argv = process.argv.slice(2);
const outArg = argv.includes('--out') ? argv[argv.indexOf('--out') + 1] : undefined;
const OUT_DIR = path.resolve(outArg ?? `runtime/demo/${new Date().toISOString().slice(0, 10)}`);

const timeline = JSON.parse(await readFile(path.join(OUT_DIR, 'timeline.json'), 'utf8'));
const manifest = JSON.parse(await readFile(path.join(OUT_DIR, 'voice', 'manifest.json'), 'utf8'));
const video = path.join(OUT_DIR, 'bidfusion-demo-silent.mp4');
const target = path.join(OUT_DIR, 'bidfusion-demo.mp4');
if (!existsSync(video)) throw new Error(`missing ${video}`);

const inputs = ['-i', video];
const delayed = [];
let n = 0;
for (const scene of timeline.scenes) {
  const clip = manifest[scene.id];
  if (!clip) continue;
  n += 1;
  inputs.push('-i', path.join(OUT_DIR, clip.file));
  const ms = Math.round(scene.start * 1000);
  delayed.push(`[${n}:a]adelay=${ms}|${ms}[a${n}]`);
}
const mix = `${delayed.map((_, i) => `[a${i + 1}]`).join('')}amix=inputs=${n}:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]`;
const filter = [...delayed, mix].join(';');
const args = [
  '-y', ...inputs,
  '-filter_complex', filter,
  '-map', '0:v', '-map', '[aout]',
  '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart',
  target,
];
const ff = spawn('ffmpeg', args, { stdio: ['ignore', 'inherit', 'pipe'] });
let stderr = '';
ff.stderr.on('data', (d) => { stderr += d; });
ff.on('close', (code) => {
  if (code !== 0) {
    console.error(stderr.slice(-2000));
    process.exit(code);
  }
  process.stdout.write(`mixed ${n} clips → ${target}\n`);
});
