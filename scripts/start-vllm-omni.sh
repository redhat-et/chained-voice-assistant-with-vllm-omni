#!/usr/bin/env bash
set -euo pipefail

MULTIMODAL_MODEL="${MULTIMODAL_MODEL:-Qwen/Qwen3-Omni-30B-A3B-Instruct}"
VLLM_OMNI_PORT="${VLLM_OMNI_PORT:-8091}"
GPU="${GPU:-0}"

echo "Starting vLLM Omni server..."
echo "  Model: ${MULTIMODAL_MODEL}"
echo "  Port:  ${VLLM_OMNI_PORT}"
echo "  GPU:   ${GPU}"

CUDA_VISIBLE_DEVICES="${GPU}" vllm serve --omni "${MULTIMODAL_MODEL}" \
    --host 0.0.0.0 \
    --port "${VLLM_OMNI_PORT}"
