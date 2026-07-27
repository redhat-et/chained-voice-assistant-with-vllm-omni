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
| **STT** | Systran/faster-whisper-large-v3 | US (OpenAI) | Default, CPU |
| **STT** | Systran/faster-whisper-medium | US (OpenAI) | Lighter, CPU |
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

### Option C: OpenShift / Kubernetes

Deploy to an OpenShift cluster with GPU nodes. Manifests are in `openshift/`.

**Prerequisites**: `oc` CLI logged in, a namespace with GPU node access, a HuggingFace token for gated models.

```bash
# 1. Create namespace and secrets
oc apply -f openshift/00-namespace.yaml
oc create secret generic hf-token --from-literal=HF_TOKEN=<your-token> -n voice-pipeline
oc create secret generic livekit-credentials \
  --from-literal=LIVEKIT_API_KEY=<key> \
  --from-literal=LIVEKIT_API_SECRET=<secret> \
  --from-literal=LIVEKIT_URL=ws://livekit-server.voice-pipeline.svc:7880 \
  -n voice-pipeline

# 2. Deploy model config and LiveKit
oc apply -f openshift/02-configmap-livekit.yaml
oc apply -f openshift/03-configmap-models.yaml

# 3. Deploy services (order matters — GPU pods take 2-5 min)
oc apply -f openshift/10-livekit.yaml
oc apply -f openshift/11-stt.yaml
oc apply -f openshift/12-llm.yaml
oc apply -f openshift/13-tts.yaml

# 4. Deploy agent, frontend, and model manager
oc apply -f openshift/14-agent.yaml
oc apply -f openshift/15-frontend.yaml
oc apply -f openshift/16-model-manager.yaml

# 5. (Optional) Build frontend from source
oc apply -f openshift/20-buildconfig-frontend.yaml
```

The frontend Route is created by `15-frontend.yaml` with TLS edge termination. Access via the route hostname (e.g., `voice-pipeline.apps.<cluster-domain>`).

**Node selectors**: The GPU manifests (`12-llm.yaml`, `13-tts.yaml`) include `nodeSelector` entries. Update these to match your cluster's GPU node hostnames.

**Model switching**: The model manager (`16-model-manager.yaml`) deploys with a ServiceAccount and RBAC to patch ConfigMaps and Deployments in the namespace. It exposes the same `/switch-llm`, `/switch-stt`, `/switch-tts` API as the Docker-based model manager.

<details>
<summary>Option D: Manual Scripts (Development)</summary>

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

The **model manager** is an HTTP API on port 8006 that swaps models without restarting the whole stack:

- **Docker Compose** (`scripts/model-manager.py`): Updates `.env` and runs `docker compose up -d --no-deps <service>` to restart the container with the new model. STT stops the current container and starts the one for the selected engine.
- **OpenShift** (`model-manager/model-manager.py`): Runs as an in-cluster Deployment with RBAC. Patches the `model-config` ConfigMap and Deployment args directly via the Kubernetes API.

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
  00-namespace.yaml             #   Namespace
  01-secrets.yaml               #   Secret templates (livekit-credentials, hf-token)
  03-configmap-models.yaml      #   Model defaults (active models, GPU util)
  10-livekit.yaml               #   LiveKit SFU server
  11-stt.yaml                   #   STT deployment (CPU) + Service
  12-llm.yaml                   #   LLM deployment (GPU) + Service
  13-tts.yaml                   #   TTS deployment (GPU) + Service
  14-agent.yaml                 #   LiveKit agent
  15-frontend.yaml              #   Frontend + Route (TLS edge)
  16-model-manager.yaml         #   Model manager + ServiceAccount + RBAC
  20-buildconfig-frontend.yaml  #   (Optional) BuildConfig from git
model-manager/
  model-manager.py              # Kubernetes-native model switching API
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

Based on [oglok/voice-assistant-with-vllm-omni](https://github.com/oglok/voice-assistant-with-vllm-omni).
