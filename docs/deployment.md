# Deployment Guide

Step-by-step instructions for deploying the disaggregated voice pipeline on GPU infrastructure.

## Architecture Overview

The system requires **6 processes** across at least 2 machines (or 1 machine with GPU + CPU):

| Process | Runs On | Port | Purpose |
|---------|---------|------|---------|
| LiveKit server | Any (CPU) | 7880 | WebRTC SFU — routes audio between browser and agent |
| faster-whisper-server | Any (CPU) | 8001 | Speech-to-Text (OpenAI-compatible) |
| vLLM (LLM) | GPU server | 8002 | Language model inference |
| vLLM-Omni (TTS) | GPU server | 8003 | Text-to-Speech synthesis |
| Python agent | Any (CPU) | — | Orchestrates STT → LLM → TTS pipeline via LiveKit |
| Next.js frontend | Any (CPU) | 3000 | Browser UI |

All 6 can run on the same GPU server, or you can split CPU processes (LiveKit, STT, agent, frontend) onto a separate machine.

---

## Option A: Single GPU Server (H100 / multi-GPU)

Best for: 4x H100 lab machines, multi-GPU cloud instances.

### 1. System requirements

- NVIDIA GPU(s) with CUDA 12.1+
- nvidia-driver 535+, nvidia-container-toolkit (for Docker GPU access)
- Python 3.10+
- Docker
- Node.js 18+ with pnpm (`npm install -g pnpm`)

### 2. Install vLLM and vLLM-Omni

```bash
pip install vllm
pip install vllm-omni --upgrade
```

Verify GPU access:

```bash
python -c "import torch; print(torch.cuda.device_count(), 'GPUs available')"
```

### 3. Install LiveKit server

```bash
curl -sSL https://get.livekit.io | bash
```

Or download from [livekit releases](https://github.com/livekit/livekit/releases).

### 4. Clone and configure

```bash
git clone https://github.com/Shaun-Walsh/voice-pipeline-disaggregated.git
cd voice-pipeline-disaggregated

cp .env.example .env.local
```

Edit `.env.local` — for a single-machine deployment, localhost defaults are correct:

```bash
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

STT_BASE_URL=http://localhost:8001/v1
STT_MODEL=Systran/faster-whisper-large-v3

LLM_BASE_URL=http://localhost:8002/v1
LLM_MODEL=google/gemma-3-4b-it

TTS_BASE_URL=http://localhost:8003/v1
TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
TTS_VOICE=vivian
```

Copy to subdirectories:

```bash
cp .env.local agent/.env.local
cp .env.local frontend/.env.local
```

### 5. Start services (6 terminals or tmux panes)

**Terminal 1 — LiveKit:**

```bash
./scripts/start-livekit.sh
```

**Terminal 2 — STT (CPU):**

```bash
./scripts/start-stt.sh
```

Wait for `Uvicorn running on http://0.0.0.0:8000` before proceeding.

**Terminal 3 — LLM (GPU 0):**

```bash
LLM_GPU=0 ./scripts/start-vllm-llm.sh
```

Wait for `Uvicorn running on http://0.0.0.0:8002`. Model download happens on first run (~2-5 min for gemma-3-4b-it).

**Terminal 4a — TTS Stage 0 (GPU 1):**

```bash
TTS_GPU=1 ./scripts/start-vllm-tts.sh stage0
```

**Terminal 4b — TTS Stage 1 (GPU 2):**

```bash
TTS_GPU_STAGE1=2 ./scripts/start-vllm-tts.sh stage1
```

Wait for both TTS stages to report ready. Model download happens on first run (~3-5 min for Qwen3-TTS-1.7B).

**Terminal 5 — Agent:**

```bash
cd agent
pip install -e .
python src/agent.py dev
```

**Terminal 6 — Frontend:**

```bash
cd frontend
pnpm install
pnpm dev --hostname 0.0.0.0
```

### 6. Access the demo

Open `http://<server-ip>:3000` in a browser with microphone access.

If accessing from a different machine, the frontend needs to know the LiveKit server's public address. Edit `frontend/.env.local`:

```bash
LIVEKIT_URL=ws://<server-ip>:7880
```

---

## Option B: AWS g5.xlarge / g6.xlarge (single 24 GB GPU)

Best for: when the H100s are gone. Uses smaller models that co-fit on one GPU.

### 1. Launch instance

- **g5.xlarge**: 1x A10G (24 GB), 4 vCPU, 16 GB RAM
- **g6.xlarge**: 1x L4 (24 GB), 4 vCPU, 16 GB RAM
- AMI: Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)
- Storage: 100 GB+ (model weights)
- Security group: open ports 3000, 7880, 8001, 8002, 8003

### 2. Install dependencies

```bash
# Python
sudo apt update && sudo apt install -y python3-pip python3-venv docker.io
pip install vllm vllm-omni --upgrade

# Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
npm install -g pnpm

# LiveKit
curl -sSL https://get.livekit.io | bash

# Docker permissions
sudo usermod -aG docker $USER
newgrp docker
```

### 3. Model selection for 24 GB GPU

On a single 24 GB GPU, use smaller models:

```bash
# .env.local for A10G/L4
LLM_MODEL=google/gemma-3-4b-it          # ~8 GB
TTS_MODEL=mistralai/Voxtral-4B-TTS-2603  # ~8-16 GB (single-stage, no 2-stage needed)
TTS_VOICE=casual_male
STT_MODEL=Systran/faster-whisper-medium   # CPU, lighter model
```

Qwen3-TTS-1.7B will NOT fit alongside the LLM on 24 GB — use Voxtral instead.

### 4. Start services

Same as Option A, but with single-process TTS (Voxtral is single-stage):

```bash
# Terminal 3 — LLM + TTS share GPU 0
LLM_GPU=0 ./scripts/start-vllm-llm.sh

# Terminal 4 — TTS (single-process, same GPU)
TTS_GPU=0 ./scripts/start-vllm-tts.sh single
```

If GPU memory is too tight, start LLM first, then TTS. vLLM will claim remaining memory.

### 5. Remote access

For the demo audience to access from their browsers:

```bash
# Edit frontend/.env.local — point at the public IP:
LIVEKIT_URL=ws://<ec2-public-ip>:7880
```

> **Do not use SSH tunnels.** WebRTC audio uses UDP, which SSH cannot forward. The signaling will connect but audio frames will be silence. Always access the server directly.

WebRTC microphone capture requires HTTPS in production browsers. For demo purposes, launch Chrome with the insecure-origin flag:

```bash
chrome --unsafely-treat-insecure-origin-as-secure="http://<ec2-ip>:3000" \
  --user-data-dir=/tmp/chrome-voice-demo \
  "http://<ec2-ip>:3000"
```

---

## Option C: Split deployment (laptop + GPU server)

Best for: running the frontend and agent locally while GPU services run remotely.

### GPU server (remote)

Start only the GPU-dependent services:

```bash
./scripts/start-vllm-llm.sh    # port 8002
./scripts/start-vllm-tts.sh    # port 8003
```

### Laptop (local)

```bash
# .env.local — point at remote GPU server
STT_BASE_URL=http://localhost:8001/v1          # STT runs locally
LLM_BASE_URL=http://<gpu-server>:8002/v1       # remote
TTS_BASE_URL=http://<gpu-server>:8003/v1       # remote
LIVEKIT_URL=ws://localhost:7880                 # LiveKit runs locally

cp .env.local agent/.env.local
cp .env.local frontend/.env.local

# Start local services
./scripts/start-livekit.sh      # Terminal 1
./scripts/start-stt.sh          # Terminal 2 (Docker, CPU)
cd agent && pip install -e . && python src/agent.py dev   # Terminal 3
cd frontend && pnpm install && pnpm dev                   # Terminal 4
```

---

## Verifying the deployment

### Health checks

```bash
# STT — should return model info
curl http://localhost:8001/v1/models

# LLM — should list loaded model
curl http://localhost:8002/v1/models

# TTS — should list loaded model
curl http://localhost:8003/v1/models

# LiveKit — should return server info
curl http://localhost:7880
```

### End-to-end test

1. Open `http://localhost:3000`
2. Click "Start Conversation"
3. Speak: "What is the capital of France?"
4. Expect: spoken response within 3 seconds
5. Check: timing overlay appears below the visualizer (STT → LLM → TTS → Total)
6. Check: agent terminal shows per-stage log lines:
   ```
   [speech_id] STT complete: 245ms (model=Systran/faster-whisper-large-v3)
   [speech_id] LLM complete: ttft=312ms total=1842ms (model=google/gemma-3-4b-it)
   [speech_id] TTS complete: ttfb=187ms total=956ms (model=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
   [speech_id] === Pipeline total: 744ms (STT=245 + LLM_TTFT=312 + TTS_TTFB=187) ===
   ```

### Model swap test

```bash
# Stop agent (Ctrl+C in agent terminal)
# Edit agent/.env.local — change LLM_MODEL
# Restart agent
cd agent && python src/agent.py dev

# Speak again — agent logs should show new model name
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Failed to get token" in browser | Frontend can't reach LiveKit or env vars missing | Check `frontend/.env.local` has `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` |
| Agent starts but no audio response | STT/LLM/TTS service not running or wrong URL | Check `curl http://localhost:800{1,2,3}/v1/models` — all three must respond |
| "CUDA out of memory" on TTS start | Models too large for GPU | Use smaller models (Voxtral instead of Qwen3-TTS) or assign separate GPUs |
| TTS returns silence | vLLM-Omni Stage 1 not running (Qwen3-TTS only) | Ensure both stage0 and stage1 are running for Qwen3-TTS |
| High latency (>5s) | Model loading on first request, or GPU contention | First request is slow (model warmup). Subsequent requests should be <3s |
| No timing overlay | Agent not publishing metrics, or frontend not listening | Check agent logs for `Pipeline total` lines. Check browser console for errors |
| Microphone not working | Browser requires HTTPS for mic access (except localhost) | Use localhost, or launch Chrome with `--unsafely-treat-insecure-origin-as-secure` |
| "Connection refused" on port 8001 | Docker not running or faster-whisper-server failed | Run `docker ps` to verify container is up. Check `docker logs` |

---

## tmux cheat sheet

Running 6 terminals is easier with tmux:

```bash
tmux new-session -s demo

# Split into panes (Ctrl+B then keys below)
# Ctrl+B %     — vertical split
# Ctrl+B "     — horizontal split
# Ctrl+B o     — switch pane
# Ctrl+B z     — zoom pane (toggle fullscreen)

# Or create named windows
tmux new-window -n livekit './scripts/start-livekit.sh'
tmux new-window -n stt './scripts/start-stt.sh'
tmux new-window -n llm 'LLM_GPU=0 ./scripts/start-vllm-llm.sh'
tmux new-window -n tts-0 'TTS_GPU=1 ./scripts/start-vllm-tts.sh stage0'
tmux new-window -n tts-1 'TTS_GPU_STAGE1=2 ./scripts/start-vllm-tts.sh stage1'
tmux new-window -n agent 'cd agent && pip install -e . && python src/agent.py dev'
tmux new-window -n frontend 'cd frontend && pnpm install && pnpm dev'
```
