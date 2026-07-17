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

REPO_URL="${repo_url}"
REPO_BRANCH="${repo_branch}"
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
# 4. Clone the repo
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
# 6. Write .env for docker-compose (all runtime configuration)
# -----------------------------------------------------------------------
cat > .env <<ENVEOF
HF_TOKEN=$HF_TOKEN
PRIVATE_IP=$PRIVATE_IP
PUBLIC_IP=$PUBLIC_IP
LLM_GPU_UTIL=$LLM_GPU_UTIL
TTS_GPU_UTIL=$TTS_GPU_UTIL
STT_ACTIVE_MODEL=$DEFAULT_STT
LLM_ACTIVE_MODEL=$DEFAULT_LLM
TTS_ACTIVE_MODEL=$DEFAULT_TTS
TTS_VOICE=vivian
HF_CACHE_DIR=/opt/hf-cache
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
ENVEOF

# -----------------------------------------------------------------------
# 7. Model manager systemd service
#    The model-manager.py script lives in the repo at scripts/model-manager.py.
#    It runs on the host (not in Docker) because it executes docker compose commands.
# -----------------------------------------------------------------------
cat > /etc/systemd/system/model-manager.service <<'SVCEOF'
[Unit]
Description=Voice Pipeline Model Manager
After=docker.service

[Service]
ExecStart=/usr/bin/python3 /opt/voice-pipeline/scripts/model-manager.py
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
# 8. Sequential GPU startup
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
# 9. Hot-patch Voxtral TTS feedback bug (vllm-omni PR #4954)
#    Fixed in v0.24.1 but no Docker image published yet.
#    Remove this block once vllm/vllm-omni image >= v0.24.1 is used.
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
