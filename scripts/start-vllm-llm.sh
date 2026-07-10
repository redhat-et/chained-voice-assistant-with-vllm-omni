#!/usr/bin/env bash
set -euo pipefail

# Start vLLM serving the LLM on port 8002
# OpenAI-compatible /v1/chat/completions endpoint

LLM_MODEL="${LLM_MODEL:-google/gemma-3-4b-it}"
LLM_PORT="${LLM_PORT:-8002}"
LLM_GPU="${LLM_GPU:-0}"

echo "Starting vLLM LLM server..."
echo "  Model: ${LLM_MODEL}"
echo "  Port:  ${LLM_PORT}"
echo "  GPU:   ${LLM_GPU}"

# H100 (80GB): can run larger models like gemma-3-12b-it or Mistral-Small-3.1-24B
# A10G/L4 (24GB): use gemma-3-4b-it (fits in ~8GB)
CUDA_VISIBLE_DEVICES="${LLM_GPU}" vllm serve "${LLM_MODEL}" \
    --host 0.0.0.0 \
    --port "${LLM_PORT}"
