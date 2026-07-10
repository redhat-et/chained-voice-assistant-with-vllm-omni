#!/usr/bin/env bash
set -euo pipefail

MULTIMODAL_MODEL="${MULTIMODAL_MODEL:-Qwen/Qwen3-Omni-30B-A3B-Instruct}"
VLLM_OMNI_PORT="${VLLM_OMNI_PORT:-8091}"

exec vllm serve "${MULTIMODAL_MODEL}" \
    --omni \
    --host 0.0.0.0 \
    --port "${VLLM_OMNI_PORT}"
