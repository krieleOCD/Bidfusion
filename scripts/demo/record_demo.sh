#!/usr/bin/env bash
# Records the BidFusion product demo end to end:
#   1. starts the local UI on a private port
#   2. synthesizes the voice-over (only if ELEVENLABS_API_KEY is set)
#   3. records the walkthrough with Playwright
#   4. converts to MP4 and mixes the voice-over in
#
# Usage: scripts/demo/record_demo.sh [--out runtime/demo/<date>] [--resynth]
# Env:   DEMO_PORT (default 8765), DEMO_SPEED (e.g. 0.2 for a dry run),
#        ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID (optional voice-over)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEMO_DIR="$REPO_ROOT/scripts/demo"
PORT="${DEMO_PORT:-8765}"
OUT="$REPO_ROOT/runtime/demo/$(date +%F)"
RESYNTH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --resynth) RESYNTH=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done
case "$OUT" in /*) ;; *) OUT="$REPO_ROOT/$OUT" ;; esac
mkdir -p "$OUT"

if [[ ! -d "$DEMO_DIR/node_modules/playwright" ]]; then
  echo "Installing Playwright into scripts/demo (one-time)..."
  (cd "$DEMO_DIR" && npm install --no-audit --no-fund)
fi

cd "$REPO_ROOT"
echo "Starting BidFusion UI on port ${PORT}..."
uv run bidfusion-ui --port "$PORT" >"$OUT/ui.log" 2>&1 &
UI_PID=$!
trap 'kill "$UI_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/overview" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/overview" >/dev/null || { echo "UI did not start; see $OUT/ui.log" >&2; exit 1; }

if [[ -n "${ELEVENLABS_API_KEY:-}" ]]; then
  if [[ $RESYNTH -eq 1 ]]; then
    node "$DEMO_DIR/synthesize_voiceover.mjs" --out "$OUT" --force
  else
    node "$DEMO_DIR/synthesize_voiceover.mjs" --out "$OUT"
  fi
else
  echo "ELEVENLABS_API_KEY not set — recording without voice-over (scene lengths use minDwell)."
fi

rm -f "$OUT"/page@*.webm
node "$DEMO_DIR/record_demo.mjs" --base-url "http://127.0.0.1:$PORT" --out "$OUT"

echo "Encoding MP4..."
ffmpeg -y -loglevel error -i "$OUT/demo.webm" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 \
  -movflags +faststart "$OUT/bidfusion-demo-silent.mp4"

if [[ -f "$OUT/voice/manifest.json" ]]; then
  node "$DEMO_DIR/mix_audio.mjs" --out "$OUT"
fi

echo
echo "Done. Outputs in $OUT:"
ls -1 "$OUT" | sed 's/^/  /'
