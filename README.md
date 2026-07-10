# Disaggregated Voice Pipeline

**Demo #2 for RHAISTRAT-1928** — vLLM-Omni Tech Preview

A voice assistant that chains three independent AI services — Speech-to-Text, Language Model, and Text-to-Speech — via LiveKit agents. Unlike monolithic voice models, each pipeline stage can be swapped independently to meet data sovereignty requirements.

```
┌──────────┐     ┌──────────┐     ┌─────────────────────────────────────┐
│  Browser  │◄──►│  LiveKit  │◄──►│          Python Agent               │
│ (React)   │    │   SFU     │    │                                     │
└──────────┘     └──────────┘    │  ┌─────┐   ┌─────┐   ┌─────┐      │
                                  │  │ STT │──►│ LLM │──►│ TTS │      │
                                  │  └──┬──┘   └──┬──┘   └──┬──┘      │
                                  └─────┼─────────┼─────────┼──────────┘
                                        │         │         │
                                        ▼         ▼         ▼
                                  faster-whisper  vLLM    vLLM-Omni
                                    (CPU)        (GPU)     (GPU)
```

## Model Menu (Sovereignty Provenance)

| Stage | Model | Origin | GPU Memory | Notes |
|-------|-------|--------|------------|-------|
| **STT** | Systran/faster-whisper-large-v3 | 🇫🇷 France | CPU only | Default |
| **STT** | Systran/faster-whisper-medium | 🇫🇷 France | CPU only | Lighter |
| **LLM** | google/gemma-3-4b-it | 🇺🇸 US | ~8 GB | Default |
| **LLM** | google/gemma-3-12b-it | 🇺🇸 US | ~24 GB | H100 |
| **LLM** | mistralai/Mistral-Small-3.1-24B-Instruct-2503 | 🇪🇺 EU | ~48 GB | H100 |
| **TTS** | Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice | 🇨🇳 China | ~24-30 GB | Default, 2-stage |
| **TTS** | mistralai/Voxtral-4B-TTS-2603 | 🇪🇺 EU | ~8-16 GB | Single-stage |

## Prerequisites

- **GPU server**: NVIDIA H100 (80 GB) recommended, or A10G/L4 (24 GB) with smaller models
- **Python**: 3.10+
- **Node.js**: 18+ with pnpm
- **Docker**: for faster-whisper-server
- **vLLM** and **vLLM-Omni**: installed on GPU server
- **LiveKit server**: [livekit-server](https://docs.livekit.io/home/self-hosting/local/)

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env.local
# Edit .env.local with your GPU server IP and model choices
cp .env.local agent/.env.local
cp .env.local frontend/.env.local
```

### 2. Start infrastructure (on GPU server)

```bash
# Terminal 1: LiveKit server
./scripts/start-livekit.sh

# Terminal 2: STT (CPU, any machine)
./scripts/start-stt.sh

# Terminal 3: LLM
./scripts/start-vllm-llm.sh

# Terminal 4: TTS (single-process mode)
./scripts/start-vllm-tts.sh single

# Or for Qwen3-TTS 2-stage on separate GPUs:
# Terminal 4a: TTS_GPU=1 ./scripts/start-vllm-tts.sh stage0
# Terminal 4b: TTS_GPU_STAGE1=2 ./scripts/start-vllm-tts.sh stage1
```

### 3. Start the agent

```bash
cd agent
pip install -e .
python src/agent.py dev
```

### 4. Start the frontend

```bash
cd frontend
pnpm install
pnpm dev
```

### 5. Open browser

Navigate to `http://localhost:3000`, click "Start Conversation", and speak.

## Model Swap (Sovereignty Demo)

To swap a model, change the environment variable and restart the agent:

```bash
# Example: switch LLM from Gemma (US) to Mistral (EU)
# Edit agent/.env.local:
#   LLM_MODEL=mistralai/Mistral-Small-3.1-24B-Instruct-2503
#   LLM_BASE_URL=http://<gpu-server>:8002/v1

# Restart agent
cd agent && python src/agent.py dev
```

The frontend timing overlay shows per-stage latency, confirming which services are active.

## Hardware Configurations

### H100 (80 GB) — Full Demo

| GPU | Service | Model |
|-----|---------|-------|
| 0 | vLLM LLM | gemma-3-4b-it (~8 GB) |
| 1 | vLLM-Omni TTS Stage 0 | Qwen3-TTS Talker (~15 GB) |
| 2 | vLLM-Omni TTS Stage 1 | Qwen3-TTS Codec (~15 GB) |
| CPU | faster-whisper-server | faster-whisper-large-v3 |

### A10G / L4 (24 GB) — Compact Demo

| GPU | Service | Model |
|-----|---------|-------|
| 0 | vLLM LLM + vLLM-Omni TTS | gemma-3-4b-it + Voxtral-4B (~16-20 GB) |
| CPU | faster-whisper-server | faster-whisper-medium |

## Project Structure

```
agent/src/agent.py          # Disaggregated pipeline (STT → LLM → TTS)
agent/src/vllm_realtime.py  # Demo #1 reference (monolithic, unchanged)
frontend/                   # React/Next.js + LiveKit (from upstream)
scripts/                    # Service launch scripts
specs/                      # Feature specification and design docs
```

## Upstream

Forked from [oglok/voice-assistant-with-vllm-omni](https://github.com/oglok/voice-assistant-with-vllm-omni) by Ricardo Noriega.
