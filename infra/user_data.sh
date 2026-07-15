#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/voice-pipeline-setup.log) 2>&1
echo "========== voice-pipeline setup started: $(date -u) =========="

HF_TOKEN="${hf_token}"
TTS_GPU_UTIL="${tts_gpu_util}"
LLM_GPU_UTIL="${llm_gpu_util}"

DEFAULT_LLM="google/gemma-3-4b-it"

REPO_URL="https://github.com/Shaun-Walsh/voice-pipeline-disaggregated.git"
REPO_BRANCH="feature/runtime-model-selection"
WORKDIR="/opt/voice-pipeline"

# -----------------------------------------------------------------------
# 1. Install Docker CE
# -----------------------------------------------------------------------
apt-get update -y
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable --now docker

# -----------------------------------------------------------------------
# 2. Install NVIDIA Container Toolkit
# -----------------------------------------------------------------------
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update -y
apt-get install -y nvidia-container-toolkit

nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo ">>> Docker + NVIDIA Container Toolkit installed"
nvidia-smi || echo "WARNING: nvidia-smi failed — GPU may not be ready yet"

# -----------------------------------------------------------------------
# 3. Wait for public IP (EIP attaches after boot)
# -----------------------------------------------------------------------
echo ">>> Waiting for public IP via IMDSv2..."
PUBLIC_IP=""
for i in $(seq 1 60); do
  TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)
  if [ -n "$TOKEN" ]; then
    PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
      http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)
  fi
  if [ -n "$PUBLIC_IP" ] && [ "$PUBLIC_IP" != "None" ]; then
    echo ">>> Public IP: $PUBLIC_IP"
    break
  fi
  echo "  waiting for EIP... attempt $i/60"
  sleep 5
done

if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "ERROR: Could not determine public IP after 5 minutes"
  exit 1
fi

PRIVATE_IP=$(hostname -I | awk '{print $1}')
echo ">>> Private IP: $PRIVATE_IP"

# -----------------------------------------------------------------------
# 4. Clone the repo (agent & frontend Dockerfiles live here)
# -----------------------------------------------------------------------
git clone -b "$REPO_BRANCH" "$REPO_URL" "$WORKDIR"
cd "$WORKDIR"

# -----------------------------------------------------------------------
# 5. Pre-cache LLM models so swapping is instant (loads from disk)
# -----------------------------------------------------------------------
echo ">>> Pre-caching LLM models to /opt/hf-cache..."
mkdir -p /opt/hf-cache
pip3 install -q huggingface-hub
export HF_HOME=/opt/hf-cache
for model in "google/gemma-3-4b-it" "Qwen/Qwen3-0.6B" "mistralai/Mistral-7B-Instruct-v0.3"; do
  echo ">>> Downloading $model..."
  huggingface-cli download --token "$HF_TOKEN" "$model" 2>&1 || echo "WARNING: Failed to download $model"
done
unset HF_HOME
echo ">>> Model pre-cache complete"

# -----------------------------------------------------------------------
# 6. LiveKit config — WebRTC needs UDP port range + external IP discovery
# -----------------------------------------------------------------------
mkdir -p livekit-config
cat > livekit-config/livekit.yaml <<'LKEOF'
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 50100
  use_external_ip: true
keys:
  devkey: secret
LKEOF

# -----------------------------------------------------------------------
# 7. .env for docker-compose — LLM_ACTIVE_MODEL is swapped at runtime
# -----------------------------------------------------------------------
cat > .env <<ENVEOF
LLM_ACTIVE_MODEL=$DEFAULT_LLM
ENVEOF

# -----------------------------------------------------------------------
# 8. docker-compose.yml
#
# Key points:
#   - Single LLM container using ${LLM_ACTIVE_MODEL} from .env
#   - HF cache mounted so model swaps load from disk, not network
#   - Model manager on host (port 8006) handles stop/start via docker compose
#   - LiveKit uses host networking for proper ICE candidate advertisement
#   - STT maps 8001:8000 (image listens on 8000, not 8001)
#   - TTS (vllm-omni) needs "vllm serve" prefix — image has NO entrypoint
#   - LLM (vllm-openai) omits "vllm serve" — entrypoint already includes it
# -----------------------------------------------------------------------
cat > docker-compose.yml <<DCEOF
services:
  livekit:
    image: livekit/livekit-server:latest
    network_mode: host
    volumes:
      - ./livekit-config/livekit.yaml:/etc/livekit.yaml
    command: --config /etc/livekit.yaml
    restart: unless-stopped

  stt:
    image: fedirz/faster-whisper-server:0.5-cpu
    environment:
      - WHISPER__MODEL=Systran/faster-whisper-large-v3
    ports:
      - "8001:8000"
    restart: unless-stopped

  tts:
    image: vllm/vllm-omni:v0.24.0
    runtime: nvidia
    shm_size: "8g"
    environment:
      - "HF_TOKEN=$HF_TOKEN"
    command: >-
      vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
      --omni
      --host 0.0.0.0
      --port 8003
      --gpu-memory-utilization $TTS_GPU_UTIL
    ports:
      - "8003:8003"
    volumes:
      - /opt/hf-cache:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped

  llm:
    image: vllm/vllm-openai:latest
    runtime: nvidia
    shm_size: "8g"
    environment:
      - "HF_TOKEN=$HF_TOKEN"
      - VLLM_USAGE_SOURCE=production
    command: >-
      \${LLM_ACTIVE_MODEL}
      --host 0.0.0.0
      --port 8002
      --gpu-memory-utilization $LLM_GPU_UTIL
      --max-model-len 2048
      --enforce-eager
    ports:
      - "8002:8002"
    volumes:
      - /opt/hf-cache:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    restart: unless-stopped

  agent:
    build:
      context: ./agent
      dockerfile: Dockerfile
    depends_on:
      - livekit
      - stt
      - llm
      - tts
    environment:
      - LIVEKIT_URL=ws://$PRIVATE_IP:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
      - STT_BASE_URL=http://stt:8000/v1
      - STT_MODEL=Systran/faster-whisper-large-v3
      - LLM_BASE_URL=http://llm:8002/v1
      - LLM_MODEL=$DEFAULT_LLM
      - TTS_BASE_URL=http://tts:8003/v1
      - TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
      - TTS_VOICE=vivian
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    depends_on:
      - livekit
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - LIVEKIT_URL=ws://$PUBLIC_IP:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
      - STT_BASE_URL=http://stt:8000
      - LLM_BASE_URL=http://llm:8002
      - TTS_BASE_URL=http://tts:8003
      - MODEL_MANAGER_URL=http://host.docker.internal:8006
    ports:
      - "3000:3000"
    restart: unless-stopped
DCEOF

echo ">>> docker-compose.yml generated"

# -----------------------------------------------------------------------
# 9. Model manager — host-level API that swaps the LLM container
# -----------------------------------------------------------------------
cat > /opt/voice-pipeline/model-manager.py <<'MMEOF'
#!/usr/bin/env python3
"""Host-level HTTP API that swaps the active LLM model by restarting
the vLLM container via docker compose. Models are pre-cached so swaps
load from disk (~10-30s) not network."""

import http.server
import json
import os
import subprocess
import time
import urllib.request

COMPOSE_DIR = "/opt/voice-pipeline"
AVAILABLE_MODELS = [
    "google/gemma-3-4b-it",
    "Qwen/Qwen3-0.6B",
    "mistralai/Mistral-7B-Instruct-v0.3",
]

def get_current_model():
    try:
        with open(os.path.join(COMPOSE_DIR, ".env")) as f:
            for line in f:
                if line.startswith("LLM_ACTIVE_MODEL="):
                    return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    return AVAILABLE_MODELS[0]

def switch_model(model):
    with open(os.path.join(COMPOSE_DIR, ".env"), "w") as f:
        f.write(f"LLM_ACTIVE_MODEL={model}\n")

    subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", "llm"],
        cwd=COMPOSE_DIR, check=True,
    )

    for _ in range(120):
        try:
            resp = urllib.request.urlopen("http://localhost:8002/v1/models", timeout=2)
            data = json.loads(resp.read())
            if any(m["id"] == model for m in data.get("data", [])):
                return True
        except Exception:
            pass
        time.sleep(5)
    return False

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/switch-llm":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            model = body.get("model", "")

            if model not in AVAILABLE_MODELS:
                self._json(400, {"error": f"unknown model: {model}", "available": AVAILABLE_MODELS})
                return

            current = get_current_model()
            if model == current:
                self._json(200, {"model": model, "status": "already_active"})
                return

            print(f"Switching LLM: {current} -> {model}")
            if switch_model(model):
                self._json(200, {"model": model, "status": "ready"})
            else:
                self._json(504, {"model": model, "status": "timeout"})
        else:
            self._json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/llm-status":
            self._json(200, {"model": get_current_model(), "available": AVAILABLE_MODELS})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        print(fmt % args)

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8006), Handler)
    print("Model manager listening on :8006")
    server.serve_forever()
MMEOF

cat > /etc/systemd/system/model-manager.service <<'SVCEOF'
[Unit]
Description=Voice Pipeline Model Manager
After=docker.service

[Service]
ExecStart=/usr/bin/python3 /opt/voice-pipeline/model-manager.py
WorkingDirectory=/opt/voice-pipeline
Restart=always
RestartSec=5
StandardOutput=append:/var/log/model-manager.log
StandardError=append:/var/log/model-manager.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable --now model-manager
echo ">>> Model manager started on port 8006"

# -----------------------------------------------------------------------
# 10. Sequential GPU startup
# -----------------------------------------------------------------------
echo ">>> Starting non-GPU services..."
docker compose up -d livekit stt

echo ">>> Starting TTS (GPU service 1/2)..."
docker compose up -d tts

echo ">>> Waiting for TTS model to load..."
for i in $(seq 1 180); do
  if curl -s http://localhost:8003/v1/models 2>/dev/null | grep -q "Qwen"; then
    echo ">>> TTS ready after ~$((i * 10))s"
    break
  fi
  if [ "$i" -eq 180 ]; then
    echo "WARNING: TTS did not become ready after 30 minutes"
  fi
  sleep 10
done

echo ">>> Starting LLM / $DEFAULT_LLM (GPU service 2/2)..."
docker compose up -d llm

echo ">>> Waiting for LLM to load..."
for i in $(seq 1 180); do
  if curl -s http://localhost:8002/v1/models 2>/dev/null | grep -qi "gemma\|qwen\|mistral"; then
    echo ">>> LLM ready after ~$((i * 10))s"
    break
  fi
  if [ "$i" -eq 180 ]; then
    echo "WARNING: LLM did not become ready after 30 minutes"
  fi
  sleep 10
done

echo ">>> Building and starting agent + frontend..."
docker compose up -d --build agent frontend

echo "========== voice-pipeline setup completed: $(date -u) =========="
echo ">>> Frontend: http://$PUBLIC_IP:3000"
echo ">>> LiveKit:  ws://$PUBLIC_IP:7880"
echo ""
echo ">>> NOTE: Browser mic access requires HTTPS or insecure origin flag."
echo ">>> Launch Chrome with: google-chrome --user-data-dir=/tmp/chrome-insecure --unsafely-treat-insecure-origin-as-secure=http://$PUBLIC_IP:3000"
