#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/voice-pipeline-setup.log) 2>&1
echo "========== voice-pipeline setup started: $(date -u) =========="

HF_TOKEN="${hf_token}"
LLM_MODEL="${llm_model}"
LLM_GPU_UTIL="${llm_gpu_util}"
TTS_GPU_UTIL="${tts_gpu_util}"

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
# 5. LiveKit config — WebRTC needs UDP port range + external IP discovery
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
# 6. docker-compose.yml — all fixes from manual deployment baked in
#
# Key fixes vs naive compose:
#   - LiveKit uses host networking for proper ICE candidate advertisement
#   - STT maps 8001:8000 (image listens on 8000, not 8001)
#   - vLLM commands omit "vllm serve" (entrypoint already includes it)
#   - Agent connects to LiveKit via private IP (host networking)
#   - Agent STT_BASE_URL uses internal port 8000
#   - GPU services start sequentially to avoid memory contention
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
      Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
      --omni
      --host 0.0.0.0
      --port 8003
      --gpu-memory-utilization $TTS_GPU_UTIL
    ports:
      - "8003:8003"
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
      $LLM_MODEL
      --host 0.0.0.0
      --port 8002
      --gpu-memory-utilization $LLM_GPU_UTIL
      --max-model-len 2048
      --enforce-eager
    ports:
      - "8002:8002"
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
      - LLM_MODEL=$LLM_MODEL
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
    environment:
      - LIVEKIT_URL=ws://$PUBLIC_IP:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
    ports:
      - "3000:3000"
    restart: unless-stopped
DCEOF

echo ">>> docker-compose.yml generated"

# -----------------------------------------------------------------------
# 7. Sequential GPU startup — TTS first, wait for ready, then LLM
#    Prevents OOM when both try to allocate GPU memory simultaneously
# -----------------------------------------------------------------------
echo ">>> Starting non-GPU services..."
docker compose up -d livekit stt

echo ">>> Starting TTS (first GPU service)..."
docker compose up -d tts

echo ">>> Waiting for TTS model to load..."
for i in $(seq 1 180); do
  if curl -s http://localhost:8003/v1/models 2>/dev/null | grep -q "Qwen"; then
    echo ">>> TTS ready after ~$((i * 10))s"
    break
  fi
  if [ "$i" -eq 180 ]; then
    echo "WARNING: TTS did not become ready after 30 minutes, starting LLM anyway"
  fi
  sleep 10
done

echo ">>> Starting LLM (second GPU service)..."
docker compose up -d llm

echo ">>> Waiting for LLM model to load..."
for i in $(seq 1 180); do
  if curl -s http://localhost:8002/v1/models 2>/dev/null | grep -qi "gemma\|redhat"; then
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
