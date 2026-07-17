# Disaggregated Voice Pipeline

A voice assistant that chains three independent AI services — Speech-to-Text, Language Model, and Text-to-Speech — via LiveKit agents. Each pipeline stage can be swapped independently at runtime to meet data sovereignty requirements.

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

All models can be swapped at runtime via the frontend dropdown — no restarts needed.

| Stage | Model | Origin | Notes |
|-------|-------|--------|-------|
| **STT** | Systran/faster-whisper-large-v3 | France | Default, CPU |
| **STT** | Systran/faster-whisper-medium | France | Lighter, CPU |
| **STT** | Qwen/Qwen3-ASR-0.6B | China | CPU |
| **LLM** | google/gemma-3-4b-it | US | Default |
| **LLM** | Qwen/Qwen3-0.6B | China | |
| **LLM** | mistralai/Mistral-7B-Instruct-v0.3 | EU | |
| **TTS** | Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice | China | Default |
| **TTS** | mistralai/Voxtral-4B-TTS-2603 | EU | |

## Deploy

### Option A: Terraform (AWS) — Fully Automated

Provisions a GPU EC2 instance with everything pre-configured. Requires an AWS account and [Terraform](https://developer.hashicorp.com/terraform/install).

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set key_pair_name, my_ip, hf_token
terraform init
terraform apply
```

The instance boots in ~15 minutes (model downloads + GPU warm-up). Terraform outputs the frontend URL and SSH command.

To deploy from a fork, set `repo_url` and `repo_branch` in your tfvars.

### Option B: Docker Compose (Any GPU Server)

Requires: Docker with NVIDIA Container Toolkit, an NVIDIA GPU (24+ GB VRAM).

```bash
# 1. Configure
cp .env.example .env
# Edit .env: set HF_TOKEN (required), adjust GPU_UTIL if needed

# 2. Pre-download models (optional but recommended — avoids long first-start)
pip install huggingface-hub
for model in google/gemma-3-4b-it Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice; do
  huggingface-cli download "$model" --token "$(grep HF_TOKEN .env | cut -d= -f2)"
done

# 3. Start services (GPU services take 2-5 min to load models)
docker compose up -d livekit stt-whisper
docker compose up -d tts        # wait for model load
docker compose up -d llm        # wait for model load
docker compose up -d --build agent frontend

# 4. Start model manager (runs on host, manages container lifecycle)
python3 scripts/model-manager.py &
```

Open `http://localhost:3000`, click **Start Conversation**, and speak.

<details>
<summary>Option C: Manual Scripts (Development)</summary>

For local development without Docker Compose. Requires Python 3.10+, Node 18+ with pnpm, and individual services installed.

```bash
cp .env.example .env.local
cp .env.local agent/.env.local
cp .env.local frontend/.env.local

# Terminal 1: LiveKit
./scripts/start-livekit.sh

# Terminal 2: STT (CPU)
./scripts/start-stt.sh

# Terminal 3: LLM (GPU)
./scripts/start-vllm-llm.sh

# Terminal 4: TTS (GPU)
./scripts/start-vllm-tts.sh single

# Terminal 5: Agent
cd agent && pip install -e . && python src/agent.py dev

# Terminal 6: Frontend
cd frontend && pnpm install && pnpm dev --hostname 0.0.0.0
```

</details>

## Runtime Model Switching

The **model manager** (`scripts/model-manager.py`) is a host-level HTTP API on port 8006 that swaps models without restarting the whole stack:

- **LLM/TTS**: Updates `.env` and runs `docker compose up -d --no-deps <service>` to restart the container with the new model
- **STT**: Stops the current STT container and starts the one for the selected engine (different Docker images per STT engine)

The frontend dropdown triggers these switches automatically. You can also call the API directly:

```bash
# Switch LLM to Mistral (EU)
curl -X POST http://localhost:8006/switch-llm \
  -H 'Content-Type: application/json' \
  -d '{"model": "mistralai/Mistral-7B-Instruct-v0.3"}'

# Check status
curl http://localhost:8006/llm-status
```

Switches take 30-120 seconds (model loading). Pre-cached models load from disk.

## Remote Access (non-localhost)

WebRTC microphone capture requires HTTPS or localhost. When accessing from a remote browser over HTTP, launch Chrome with the insecure-origin flag:

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --unsafely-treat-insecure-origin-as-secure="http://<server-ip>:3000" \
  --user-data-dir=/tmp/chrome-voice-demo \
  "http://<server-ip>:3000"
```

Do not use SSH tunnels — WebRTC audio uses UDP, which SSH cannot forward.

## Testing

```bash
make test-unit          # Agent + frontend unit tests
make smoke              # Health checks (requires running services)
make test-integration   # Full integration tests
```

## Project Structure

```
docker-compose.yml              # Service topology (8 containers)
.env.example                    # Configuration template
livekit-config/livekit.yaml     # LiveKit server config
scripts/model-manager.py        # Runtime model switching API (port 8006)
agent/
  src/agent.py                  # LiveKit voice agent (STT -> LLM -> TTS)
  tests/test_agent.py           # Unit tests
frontend/                       # React/Next.js UI with model selector
infra/
  main.tf                       # AWS infrastructure (VPC, EC2, EIP)
  variables.tf                  # Terraform variables
  user_data.sh                  # EC2 bootstrap script
  terraform.tfvars.example      # Variable template
openshift/                      # OpenShift/Kubernetes manifests
Makefile                        # Test targets
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Stuck on "Listening" | Cloud turn detection auth fails on self-hosted LiveKit | Already fixed — agent uses `turn_detection=None` |
| No audio from microphone | Browser blocks mic over HTTP | Launch Chrome with `--unsafely-treat-insecure-origin-as-secure` flag |
| Model switch times out | GPU memory insufficient for the new model | Reduce `LLM_GPU_UTIL` / `TTS_GPU_UTIL` in `.env` |
| TTS produces gibberish | vLLM-Omni v0.24.0 Voxtral bug | Apply hot-patch (done automatically in Terraform deploy) |
| `HF_TOKEN` errors on startup | Gated models require a HuggingFace token | Set `HF_TOKEN` in `.env` with a token from huggingface.co/settings/tokens |
| Frontend model dropdown empty | Model manager not running | Start with `python3 scripts/model-manager.py` |

## Upstream

Forked from [redhat-et/chained-voice-assistant-with-vllm-omni](https://github.com/redhat-et/chained-voice-assistant-with-vllm-omni).
