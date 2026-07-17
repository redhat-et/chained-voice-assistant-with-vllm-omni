#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/voice-pipeline-setup.log) 2>&1
echo "========== voice-pipeline setup started: $(date -u) =========="

HF_TOKEN="${hf_token}"
TTS_GPU_UTIL="${tts_gpu_util}"
LLM_GPU_UTIL="${llm_gpu_util}"

DEFAULT_STT="Systran/faster-whisper-large-v3"
DEFAULT_LLM="google/gemma-3-4b-it"
DEFAULT_TTS="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

REPO_URL="https://github.com/redhat-et/chained-voice-assistant-with-vllm-omni.git"
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
# 5. Pre-cache LLM + TTS models so swapping is instant (loads from disk)
# -----------------------------------------------------------------------
echo ">>> Pre-caching models to /opt/hf-cache..."
mkdir -p /opt/hf-cache
pip3 install -q huggingface-hub
export HF_HOME=/opt/hf-cache
for model in \
  "google/gemma-3-4b-it" "Qwen/Qwen3-0.6B" "mistralai/Mistral-7B-Instruct-v0.3" \
  "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" "mistralai/Voxtral-4B-TTS-2603"; do
  echo ">>> Downloading $model..."
  hf download "$model" --token "$HF_TOKEN" 2>&1 || echo "WARNING: Failed to download $model"
done
unset HF_HOME
echo ">>> Model pre-cache complete"

echo ">>> Pre-pulling STT Docker images..."
docker pull lancelrq/qwen3-asr-service:latest-cpu &
QWEN_ASR_PULL_PID=$!

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
# 7. .env for docker-compose — active models swapped at runtime
# -----------------------------------------------------------------------
cat > .env <<ENVEOF
STT_ACTIVE_MODEL=$DEFAULT_STT
LLM_ACTIVE_MODEL=$DEFAULT_LLM
TTS_ACTIVE_MODEL=$DEFAULT_TTS
ENVEOF

# -----------------------------------------------------------------------
# 8. docker-compose.yml
#
# Key points:
#   - Single LLM container using ${LLM_ACTIVE_MODEL} from .env
#   - Single TTS container using ${TTS_ACTIVE_MODEL} from .env
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

  stt-whisper:
    image: fedirz/faster-whisper-server:0.5-cpu
    environment:
      - WHISPER__MODEL=Systran/faster-whisper-large-v3
    ports:
      - "8001:8000"
    restart: unless-stopped

  stt-whisper-medium:
    image: fedirz/faster-whisper-server:0.5-cpu
    environment:
      - WHISPER__MODEL=Systran/faster-whisper-medium
    ports:
      - "8001:8000"
    profiles:
      - stt-whisper-medium
    restart: unless-stopped

  stt-qwen:
    image: lancelrq/qwen3-asr-service:latest-cpu
    command: --device cpu --model-size 0.6b --port 8000 --enable-openai-api
    ports:
      - "8001:8000"
    profiles:
      - stt-qwen
    restart: unless-stopped

  tts:
    image: vllm/vllm-omni:v0.24.0
    runtime: nvidia
    shm_size: "8g"
    environment:
      - "HF_TOKEN=$HF_TOKEN"
    command: >-
      vllm serve \${TTS_ACTIVE_MODEL}
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
      - HF_HUB_OFFLINE=1
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
      - llm
      - tts
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - LIVEKIT_URL=ws://$PRIVATE_IP:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
      - STT_BASE_URL=http://host.docker.internal:8001/v1
      - STT_MODEL=$DEFAULT_STT
      - LLM_BASE_URL=http://llm:8002/v1
      - LLM_MODEL=$DEFAULT_LLM
      - TTS_BASE_URL=http://tts:8003/v1
      - TTS_MODEL=$DEFAULT_TTS
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
# 9. Model manager — host-level API that swaps LLM and TTS containers
# -----------------------------------------------------------------------
cat > /opt/voice-pipeline/model-manager.py <<'MMEOF'
#!/usr/bin/env python3
"""Host-level HTTP API that swaps active STT, LLM, and TTS models.
LLM/TTS swap by restarting the same container with a different model env var.
STT swaps by stopping one container and starting another (different engines)."""

import http.server
import json
import os
import subprocess
import threading
import time
import urllib.request

COMPOSE_DIR = "/opt/voice-pipeline"

AVAILABLE_STT = [
    "Systran/faster-whisper-large-v3",
    "Systran/faster-whisper-medium",
    "Qwen/Qwen3-ASR-0.6B",
]
AVAILABLE_LLM = [
    "google/gemma-3-4b-it",
    "Qwen/Qwen3-0.6B",
    "mistralai/Mistral-7B-Instruct-v0.3",
]
AVAILABLE_TTS = [
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "mistralai/Voxtral-4B-TTS-2603",
]

STT_CONTAINERS = {
    "Systran/faster-whisper-large-v3": "stt-whisper",
    "Systran/faster-whisper-medium": "stt-whisper-medium",
    "Qwen/Qwen3-ASR-0.6B": "stt-qwen",
}

SERVICES = {
    "llm": {"env_key": "LLM_ACTIVE_MODEL", "port": 8002, "available": AVAILABLE_LLM, "service": "llm"},
    "tts": {"env_key": "TTS_ACTIVE_MODEL", "port": 8003, "available": AVAILABLE_TTS, "service": "tts"},
}

_locks = {"stt": threading.Lock(), "llm": threading.Lock(), "tts": threading.Lock()}
_switching = {"stt": None, "llm": None, "tts": None}

def read_env():
    vals = {}
    try:
        with open(os.path.join(COMPOSE_DIR, ".env")) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k] = v
    except FileNotFoundError:
        pass
    return vals

def write_env(vals):
    with open(os.path.join(COMPOSE_DIR, ".env"), "w") as f:
        for k, v in vals.items():
            f.write(f"{k}={v}\n")

def get_active(kind):
    if kind == "stt":
        vals = read_env()
        return vals.get("STT_ACTIVE_MODEL", AVAILABLE_STT[0])
    cfg = SERVICES[kind]
    vals = read_env()
    return vals.get(cfg["env_key"], cfg["available"][0])

STT_HEALTH_PATHS = {
    "Systran/faster-whisper-large-v3": "/v1/models",
    "Systran/faster-whisper-medium": "/v1/models",
    "Qwen/Qwen3-ASR-0.6B": "/compat/openai/v1/models",
}

def wait_for_stt(model, port=8001, timeout=120):
    path = STT_HEALTH_PATHS.get(model, "/v1/models")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False

def wait_for_model(model, port, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=2)
            data = json.loads(resp.read())
            if any(m["id"] == model for m in data.get("data", [])):
                return True
        except Exception:
            pass
        time.sleep(3)
    return False

def switch_stt(model):
    current = get_active("stt")
    old_container = STT_CONTAINERS[current]
    new_container = STT_CONTAINERS[model]

    vals = read_env()
    vals["STT_ACTIVE_MODEL"] = model
    write_env(vals)

    subprocess.run(
        ["docker", "compose", "stop", old_container],
        cwd=COMPOSE_DIR, check=True,
    )
    subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", new_container],
        cwd=COMPOSE_DIR, check=True,
    )

    return wait_for_stt(model)

def switch(kind, model):
    cfg = SERVICES[kind]
    vals = read_env()
    vals[cfg["env_key"]] = model
    write_env(vals)

    subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", cfg["service"]],
        cwd=COMPOSE_DIR, check=True,
    )

    return wait_for_model(model, cfg["port"])

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        model = body.get("model", "")

        if self.path == "/switch-stt":
            self._handle_switch("stt", model, AVAILABLE_STT, switch_stt)
        elif self.path == "/switch-llm":
            self._handle_switch("llm", model, AVAILABLE_LLM, lambda m: switch("llm", m))
        elif self.path == "/switch-tts":
            self._handle_switch("tts", model, AVAILABLE_TTS, lambda m: switch("tts", m))
        else:
            self._json(404, {"error": "not found"})

    def _handle_switch(self, kind, model, available, do_switch):
        if model not in available:
            self._json(400, {"error": f"unknown model: {model}", "available": available})
            return

        current = get_active(kind)
        if model == current:
            self._json(200, {"model": model, "status": "already_active"})
            return

        acquired = _locks[kind].acquire(blocking=False)
        if not acquired:
            if _switching[kind] == model:
                print(f"Switch {kind} to {model} already in progress, waiting...")
                if kind == "stt":
                    ok = wait_for_stt(model)
                else:
                    ok = wait_for_model(model, SERVICES[kind]["port"])
                if ok:
                    self._json(200, {"model": model, "status": "ready"})
                else:
                    self._json(504, {"model": model, "status": "timeout"})
                return
            else:
                self._json(409, {"error": f"{kind} switch in progress", "switching_to": _switching[kind]})
                return

        try:
            _switching[kind] = model
            print(f"Switching {kind.upper()}: {current} -> {model}")
            if do_switch(model):
                self._json(200, {"model": model, "status": "ready"})
            else:
                self._json(504, {"model": model, "status": "timeout"})
        finally:
            _switching[kind] = None
            _locks[kind].release()

    def do_GET(self):
        if self.path == "/stt-status":
            status = {"model": get_active("stt"), "available": AVAILABLE_STT}
            if _switching["stt"]:
                status["switching_to"] = _switching["stt"]
            self._json(200, status)
        elif self.path == "/llm-status":
            status = {"model": get_active("llm"), "available": AVAILABLE_LLM}
            if _switching["llm"]:
                status["switching_to"] = _switching["llm"]
            self._json(200, status)
        elif self.path == "/tts-status":
            status = {"model": get_active("tts"), "available": AVAILABLE_TTS}
            if _switching["tts"]:
                status["switching_to"] = _switching["tts"]
            self._json(200, status)
        else:
            self._json(404, {"error": "not found"})

    def _json(self, code, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            print(f"Client disconnected before response (code={code})")

    def log_message(self, fmt, *args):
        print(fmt % args)

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8006), Handler)
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
echo ">>> Waiting for Qwen3-ASR image pull..."
wait $QWEN_ASR_PULL_PID || echo "WARNING: Qwen3-ASR image pull failed"

echo ">>> Starting non-GPU services..."
docker compose up -d livekit stt-whisper

echo ">>> Starting TTS (GPU service 1/2)..."
docker compose up -d tts

echo ">>> Waiting for TTS model to load..."
for i in $(seq 1 180); do
  if curl -s http://localhost:8003/v1/models 2>/dev/null | grep -qi "qwen\|voxtral"; then
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

# -----------------------------------------------------------------------
# 11. Hot-patch Voxtral TTS feedback bug (vllm-omni PR #4954)
#     Fixed in v0.24.1 but no Docker image published yet.
#     Remove this block once vllm/vllm-omni image >= v0.24.1 is used.
# -----------------------------------------------------------------------
echo ">>> Patching Voxtral TTS feedback bug (PR #4954)..."
VOXTRAL_PY="/usr/local/lib/python3.12/dist-packages/vllm_omni/model_executor/models/voxtral_tts/voxtral_tts.py"
docker cp voice-pipeline-tts-1:$VOXTRAL_PY /tmp/voxtral_tts.py 2>/dev/null && \
python3 << 'PATCHEOF'
with open("/tmp/voxtral_tts.py") as f:
    content = f.read()
old = '        audio_tokens = info_dict.pop("audio", None)'
new = """        codes = info_dict.get("codes")
        audio_tokens = codes.get("audio") if isinstance(codes, Mapping) else None
        if audio_tokens is None:
            audio_tokens = info_dict.pop("audio", None)"""
if old in content:
    content = content.replace(old, new, 1)
    with open("/tmp/voxtral_tts.py", "w") as f:
        f.write(content)
    print("Voxtral TTS patched")
else:
    print("Patch target not found (may already be fixed)")
PATCHEOF
docker cp /tmp/voxtral_tts.py voice-pipeline-tts-1:$VOXTRAL_PY 2>/dev/null && \
docker compose restart tts && \
echo ">>> Waiting for TTS to reload after patch..." && \
for i in $(seq 1 60); do
  if curl -s http://localhost:8003/v1/models 2>/dev/null | grep -qi "qwen\|voxtral"; then
    echo ">>> TTS ready after patch (~$((i * 5))s)"
    break
  fi
  sleep 5
done || echo "WARNING: Voxtral patch skipped (container not running or file not found)"

echo ">>> Building and starting agent + frontend..."
docker compose up -d --build agent frontend

echo "========== voice-pipeline setup completed: $(date -u) =========="
echo ">>> Frontend: http://$PUBLIC_IP:3000"
echo ">>> LiveKit:  ws://$PUBLIC_IP:7880"
echo ""
echo ">>> NOTE: Browser mic access requires HTTPS or insecure origin flag."
echo ">>> Launch Chrome with: google-chrome --user-data-dir=/tmp/chrome-insecure --unsafely-treat-insecure-origin-as-secure=http://$PUBLIC_IP:3000"
