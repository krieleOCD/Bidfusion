# BidFusion product demo recorder

Records a 3-minute walkthrough of the local UI as a video, with a visible
cursor, a subtle lower-third title per scene, and an optional ElevenLabs
voice-over. The scene list in `scenes.mjs` is the single source of truth for
what is clicked, what the lower third says, and what the narrator says.

**Internal only.** The Knowledge scenes show the real MTD golden-knowledge
pilot data from `runtime/golden_dataset/`. Do not share the recording outside
Orange Cyberdefense.

## Prerequisites

- `uv sync --extra dev` (the UI itself)
- Node ≥ 20 and `ffmpeg`/`ffprobe` on the PATH (`brew install ffmpeg`)
- Playwright is installed locally into `scripts/demo/node_modules` on first run
  (pinned so that it matches an already downloaded Chromium build; run
  `npx playwright install chromium` inside `scripts/demo` if Chromium is missing)
- Optional voice-over: `ELEVENLABS_API_KEY` in the environment. The key is
  never written to disk inside the repo. Default voice is George
  (`JBFqnCBsd6RMkjVDRZzb`), override with `ELEVENLABS_VOICE_ID`.

## Record

```bash
# dry run: every pause scaled down, no voice-over
DEMO_SPEED=0.2 scripts/demo/record_demo.sh --out runtime/demo/dry-run

# full recording with voice-over
export ELEVENLABS_API_KEY=…   # from your shell, not from a file in the repo
scripts/demo/record_demo.sh
```

Outputs land in `runtime/demo/<date>/` (gitignored):

| File | Purpose |
|---|---|
| `bidfusion-demo.mp4` | final video with voice-over |
| `bidfusion-demo-silent.mp4` | same timeline without audio, for your own narration |
| `demo-script.md` | narration script with measured in/out timestamps and page status |
| `demo-script.srt` | the narration as subtitle cues |
| `timeline.json` | raw scene timings |
| `voice/` | one MP3 per scene plus `manifest.json` |
| `demo.webm` | raw Playwright recording |

## How timing works

Voice clips are synthesized first. The recorder holds each scene for
`max(minDwell, clip length + 0.8 s)`, so narration is never cut off and the
video length follows the script. Scene actions run at the start of the scene;
the rest is a calm hold. `mix_audio.mjs` places each clip at the measured
scene start, so re-recording never needs manual alignment.

## Editing the demo

- Change wording, order or click path in `scenes.mjs` only.
- Locators use roles, labels and `<summary>` text, so small template changes
  rarely break the recording. If a step fails, the error names the scene and
  the step.
- Re-running with the same `--out` reuses voice clips whose text is unchanged;
  `--resynth` forces new clips.
