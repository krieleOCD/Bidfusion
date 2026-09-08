#!/usr/bin/env node
// Synthesizes one ElevenLabs voice clip per scene from scenes.mjs.
// Writes <out>/voice/<scene id>.mp3 and <out>/voice/manifest.json with clip
// durations (measured with ffprobe) so record_demo.mjs can size each scene.
//
// Usage: node synthesize_voiceover.mjs --out runtime/demo/2026-09-08 [--force]
// Env:   ELEVENLABS_API_KEY   required (never stored in the repo)
//        ELEVENLABS_VOICE_ID  default George (JBFqnCBsd6RMkjVDRZzb), British narrator
//        ELEVENLABS_MODEL_ID  default eleven_multilingual_v2

import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { scenes } from './scenes.mjs';

const execFileAsync = promisify(execFile);
const argv = process.argv.slice(2);
const outArg = argv.includes('--out') ? argv[argv.indexOf('--out') + 1] : undefined;
const FORCE = argv.includes('--force');
const OUT_DIR = path.resolve(outArg ?? `runtime/demo/${new Date().toISOString().slice(0, 10)}`);
const VOICE_DIR = path.join(OUT_DIR, 'voice');
const API_KEY = process.env.ELEVENLABS_API_KEY;
const VOICE_ID = process.env.ELEVENLABS_VOICE_ID ?? 'JBFqnCBsd6RMkjVDRZzb';
const MODEL_ID = process.env.ELEVENLABS_MODEL_ID ?? 'eleven_multilingual_v2';

if (!API_KEY) {
  console.error('ELEVENLABS_API_KEY is not set; skipping voice-over.');
  process.exit(2);
}

async function durationSeconds(file) {
  const { stdout } = await execFileAsync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]);
  return Number(stdout.trim());
}

async function synthesize(scene, previousText, nextText) {
  const url = `https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}?output_format=mp3_44100_128`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'xi-api-key': API_KEY, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    body: JSON.stringify({
      text: scene.narration,
      model_id: MODEL_ID,
      previous_text: previousText,
      next_text: nextText,
      voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.15, use_speaker_boost: true },
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`ElevenLabs ${response.status} for ${scene.id}: ${body.slice(0, 300)}`);
  }
  return Buffer.from(await response.arrayBuffer());
}

async function main() {
  await mkdir(VOICE_DIR, { recursive: true });
  const manifestFile = path.join(VOICE_DIR, 'manifest.json');
  const manifest = existsSync(manifestFile) && !FORCE ? JSON.parse(await readFile(manifestFile, 'utf8')) : {};
  let characters = 0;
  for (const [i, scene] of scenes.entries()) {
    const file = path.join(VOICE_DIR, `${scene.id}.mp3`);
    const unchanged = manifest[scene.id]?.text === scene.narration && existsSync(file) && !FORCE;
    if (!unchanged) {
      process.stdout.write(`synthesizing ${scene.id} (${scene.narration.length} chars)\n`);
      const audio = await synthesize(scene, scenes[i - 1]?.narration, scenes[i + 1]?.narration);
      await writeFile(file, audio);
      characters += scene.narration.length;
    }
    manifest[scene.id] = {
      file: path.relative(OUT_DIR, file),
      seconds: await durationSeconds(file),
      text: scene.narration,
      voiceId: VOICE_ID,
      modelId: MODEL_ID,
    };
  }
  await writeFile(manifestFile, JSON.stringify(manifest, null, 2));
  const total = Object.values(manifest).reduce((a, m) => a + m.seconds, 0);
  process.stdout.write(`voice-over ready: ${scenes.length} clips, ${total.toFixed(1)} s of speech, ${characters} chars synthesized → ${manifestFile}\n`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
