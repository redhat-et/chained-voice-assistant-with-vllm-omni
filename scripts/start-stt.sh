#!/usr/bin/env bash
set -euo pipefail

# Start faster-whisper-server for STT (CPU-only, OpenAI-compatible)
# Exposes /v1/audio/transcriptions on port 8001

STT_MODEL="${STT_MODEL:-Systran/faster-whisper-large-v3}"
STT_PORT="${STT_PORT:-8001}"

echo "Starting faster-whisper-server..."
echo "  Model: ${STT_MODEL}"
echo "  Port:  ${STT_PORT}"
echo "  Device: CPU"

docker run --rm \
    -p "${STT_PORT}:8000" \
    -e WHISPER__MODEL="${STT_MODEL}" \
    -e WHISPER__INFERENCE_DEVICE=cpu \
    fedirz/faster-whisper-server
