#!/usr/bin/env bash
set -euo pipefail

# Start vLLM-Omni serving TTS on port 8003
# OpenAI-compatible /v1/audio/speech endpoint

TTS_MODEL="${TTS_MODEL:-Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice}"
TTS_PORT="${TTS_PORT:-8003}"
TTS_GPU="${TTS_GPU:-1}"
MASTER_PORT="${TTS_MASTER_PORT:-26000}"
MODE="${1:-single}"

echo "Starting vLLM-Omni TTS server..."
echo "  Model: ${TTS_MODEL}"
echo "  Port:  ${TTS_PORT}"
echo "  GPU:   ${TTS_GPU}"
echo "  Mode:  ${MODE}"

case "${MODE}" in
    single)
        # Single-process mode — all stages in one process, auto GPU assignment
        # Works for Voxtral (single-stage) or Qwen3-TTS on multi-GPU
        CUDA_VISIBLE_DEVICES="${TTS_GPU}" vllm serve "${TTS_MODEL}" \
            --omni \
            --host 0.0.0.0 \
            --port "${TTS_PORT}"
        ;;

    stage0)
        # Multi-process mode — Stage 0: Talker LLM + HTTP API server
        # For Qwen3-TTS 2-stage pipeline on separate GPUs
        CUDA_VISIBLE_DEVICES="${TTS_GPU}" vllm serve "${TTS_MODEL}" \
            --omni \
            --host 0.0.0.0 \
            --port "${TTS_PORT}" \
            --stage-id 0 \
            --omni-master-address 127.0.0.1 \
            --omni-master-port "${MASTER_PORT}"
        ;;

    stage1)
        # Multi-process mode — Stage 1: Audio Codec (headless worker)
        # Run on a different GPU than stage0
        TTS_GPU_STAGE1="${TTS_GPU_STAGE1:-2}"
        CUDA_VISIBLE_DEVICES="${TTS_GPU_STAGE1}" vllm serve "${TTS_MODEL}" \
            --omni \
            --stage-id 1 \
            --headless \
            --omni-master-address 127.0.0.1 \
            --omni-master-port "${MASTER_PORT}"
        ;;

    *)
        echo "Usage: $0 [single|stage0|stage1]"
        echo ""
        echo "  single  — All stages in one process (default)"
        echo "  stage0  — Stage 0 only (Talker LLM + API), pair with stage1"
        echo "  stage1  — Stage 1 only (Audio Codec, headless worker)"
        echo ""
        echo "For Qwen3-TTS 2-stage on H100:"
        echo "  Terminal 1: TTS_GPU=1 $0 stage0"
        echo "  Terminal 2: TTS_GPU_STAGE1=2 $0 stage1"
        echo ""
        echo "For Voxtral single-stage:"
        echo "  TTS_MODEL=mistralai/Voxtral-4B-TTS-2603 $0 single"
        exit 1
        ;;
esac
