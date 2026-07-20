#!/usr/bin/env python3
"""K8s-native HTTP API that swaps active STT, LLM, and TTS models.

Updates the model-config ConfigMap, patches deployments with model-specific
args, and waits for the correct model to appear on the service endpoint.
"""

import http.server
import json
import os
import threading
import time
import urllib.request

from kubernetes import client, config

NAMESPACE = os.environ.get("NAMESPACE", "voice-pipeline")
CONFIGMAP_NAME = "model-config"

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

# --- STT model configs (different images/envs per engine) ---

STT_IMAGE_MAP = {
    "Systran/faster-whisper-large-v3": "fedirz/faster-whisper-server:0.5-cpu",
    "Systran/faster-whisper-medium": "fedirz/faster-whisper-server:0.5-cpu",
    "Qwen/Qwen3-ASR-0.6B": "lancelrq/qwen3-asr-service:latest-cpu",
}

STT_ENV_CONFIG = {
    "Systran/faster-whisper-large-v3": [
        {"name": "WHISPER__MODEL", "value": "Systran/faster-whisper-large-v3"},
    ],
    "Systran/faster-whisper-medium": [
        {"name": "WHISPER__MODEL", "value": "Systran/faster-whisper-medium"},
    ],
    "Qwen/Qwen3-ASR-0.6B": [
        {"name": "MODEL_ID", "value": "Qwen/Qwen3-ASR-0.6B"},
    ],
}

STT_HEALTH_PATHS = {
    "Systran/faster-whisper-large-v3": "/v1/models",
    "Systran/faster-whisper-medium": "/v1/models",
    "Qwen/Qwen3-ASR-0.6B": "/compat/openai/v1/models",
}

# --- LLM model configs (different vLLM args per model) ---

LLM_ARGS_MAP = {
    "google/gemma-3-4b-it": [
        "$(LLM_ACTIVE_MODEL)",
        "--host", "0.0.0.0",
        "--port", "8002",
        "--gpu-memory-utilization", "$(LLM_GPU_UTIL)",
        "--max-model-len", "2048",
        "--enforce-eager",
        "--chat-template", "/etc/chat-template/gemma-chat-template.jinja",
    ],
    "Qwen/Qwen3-0.6B": [
        "$(LLM_ACTIVE_MODEL)",
        "--host", "0.0.0.0",
        "--port", "8002",
        "--gpu-memory-utilization", "$(LLM_GPU_UTIL)",
        "--max-model-len", "2048",
    ],
    "mistralai/Mistral-7B-Instruct-v0.3": [
        "$(LLM_ACTIVE_MODEL)",
        "--host", "0.0.0.0",
        "--port", "8002",
        "--gpu-memory-utilization", "$(LLM_GPU_UTIL)",
        "--max-model-len", "2048",
        "--enforce-eager",
    ],
}

# --- TTS model configs (all use --omni on vLLM-Omni image) ---

TTS_ARGS_MAP = {
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice": [
        "$(TTS_ACTIVE_MODEL)",
        "--omni",
        "--host", "0.0.0.0",
        "--port", "8003",
        "--trust-remote-code",
        "--gpu-memory-utilization", "$(TTS_GPU_UTIL)",
    ],
    "mistralai/Voxtral-4B-TTS-2603": [
        "$(TTS_ACTIVE_MODEL)",
        "--omni",
        "--host", "0.0.0.0",
        "--port", "8003",
        "--trust-remote-code",
        "--gpu-memory-utilization", "$(TTS_GPU_UTIL)",
    ],
}

# --- Service endpoint map for health checks ---

SERVICE_ENDPOINTS = {
    "stt": "http://stt-server:8001",
    "llm": "http://llm-server:8002",
    "tts": "http://tts-server:8003",
}

DEPLOYMENT_MAP = {"stt": "stt", "llm": "llm", "tts": "tts"}

_locks = {"stt": threading.Lock(), "llm": threading.Lock(), "tts": threading.Lock()}
_switching = {"stt": None, "llm": None, "tts": None}
_switch_error = {"stt": None, "llm": None, "tts": None}

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()


# --- ConfigMap helpers ---

def get_configmap_data():
    cm = core_v1.read_namespaced_config_map(CONFIGMAP_NAME, NAMESPACE)
    return cm.data or {}


def patch_configmap(updates: dict):
    core_v1.patch_namespaced_config_map(
        CONFIGMAP_NAME, NAMESPACE, {"data": updates}
    )


def get_active(kind):
    data = get_configmap_data()
    key_map = {"stt": "STT_ACTIVE_MODEL", "llm": "LLM_ACTIVE_MODEL", "tts": "TTS_ACTIVE_MODEL"}
    defaults = {"stt": AVAILABLE_STT[0], "llm": AVAILABLE_LLM[0], "tts": AVAILABLE_TTS[0]}
    return data.get(key_map[kind], defaults[kind])


# --- Model endpoint verification (the core fix) ---

def check_model_endpoint(kind, model):
    """Single-shot check: is the expected model serving on the service endpoint?"""
    base_url = SERVICE_ENDPOINTS[kind]
    if kind == "stt":
        path = STT_HEALTH_PATHS.get(model, "/v1/models")
    else:
        path = "/v1/models"
    try:
        resp = urllib.request.urlopen(f"{base_url}{path}", timeout=3)
        data = json.loads(resp.read())
        return any(m["id"] == model for m in data.get("data", []))
    except Exception:
        return False


def wait_for_model(kind, model, timeout=300):
    """Poll the service endpoint until the correct model is serving."""
    base_url = SERVICE_ENDPOINTS[kind]
    if kind == "stt":
        path = STT_HEALTH_PATHS.get(model, "/v1/models")
    else:
        path = "/v1/models"
    url = f"{base_url}{path}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=3)
            data = json.loads(resp.read())
            serving = [m["id"] for m in data.get("data", [])]
            if model in serving:
                print(f"  [{kind}] model {model} is serving")
                return True
            print(f"  [{kind}] waiting for {model}, currently serving: {serving}")
        except Exception as e:
            print(f"  [{kind}] endpoint not ready: {e}")
        time.sleep(5)
    return False


# --- Deployment patching ---

def restart_deployment(name):
    """Patch the restart annotation to trigger a rollout."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    apps_v1.patch_namespaced_deployment(
        name, NAMESPACE,
        {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        },
    )


def patch_stt_deployment(model):
    """STT uses different container images and env vars per model."""
    image = STT_IMAGE_MAP[model]
    env_list = [client.V1EnvVar(**e) for e in STT_ENV_CONFIG[model]]

    deployment = apps_v1.read_namespaced_deployment("stt", NAMESPACE)
    container = deployment.spec.template.spec.containers[0]
    container.image = image
    container.env = env_list

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not deployment.spec.template.metadata.annotations:
        deployment.spec.template.metadata.annotations = {}
    deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = now

    apps_v1.replace_namespaced_deployment("stt", NAMESPACE, deployment)


def patch_gpu_deployment(kind, model):
    """Patch LLM or TTS deployment with model-specific container args."""
    args_map = LLM_ARGS_MAP if kind == "llm" else TTS_ARGS_MAP
    new_args = args_map.get(model)
    if not new_args:
        print(f"  [{kind}] no args config for {model}, using restart only")
        restart_deployment(DEPLOYMENT_MAP[kind])
        return

    dep_name = DEPLOYMENT_MAP[kind]
    deployment = apps_v1.read_namespaced_deployment(dep_name, NAMESPACE)
    container = deployment.spec.template.spec.containers[0]
    container.args = new_args

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not deployment.spec.template.metadata.annotations:
        deployment.spec.template.metadata.annotations = {}
    deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = now

    apps_v1.replace_namespaced_deployment(dep_name, NAMESPACE, deployment)


# --- Switch orchestration ---

def switch_stt(model):
    patch_configmap({"STT_ACTIVE_MODEL": model})
    patch_stt_deployment(model)
    return wait_for_model("stt", model)


def switch_llm(model):
    patch_configmap({"LLM_ACTIVE_MODEL": model})
    patch_gpu_deployment("llm", model)
    return wait_for_model("llm", model)


def switch_tts(model):
    patch_configmap({"TTS_ACTIVE_MODEL": model})
    patch_gpu_deployment("tts", model)
    return wait_for_model("tts", model)


SERVICES = {
    "stt": {"available": AVAILABLE_STT, "switch": switch_stt},
    "llm": {"available": AVAILABLE_LLM, "switch": switch_llm},
    "tts": {"available": AVAILABLE_TTS, "switch": switch_tts},
}


def _do_switch_background(kind, model, switch_fn):
    """Run a model switch in a background thread."""
    try:
        current = get_active(kind)
        if model == current:
            print(f"  [{kind}] ConfigMap already set, waiting for model to serve...")
            success = wait_for_model(kind, model)
        else:
            success = switch_fn(model)

        if success:
            print(f"  [{kind}] switch to {model} complete")
            _switch_error[kind] = None
        else:
            print(f"  [{kind}] switch to {model} timed out")
            _switch_error[kind] = "timeout"
    except Exception as e:
        print(f"ERROR switching {kind}: {e}")
        _switch_error[kind] = str(e)
    finally:
        _switching[kind] = None
        _locks[kind].release()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        model = body.get("model", "")

        kind_map = {"/switch-stt": "stt", "/switch-llm": "llm", "/switch-tts": "tts"}
        kind = kind_map.get(self.path)
        if not kind:
            self._json(404, {"error": "not found"})
            return

        cfg = SERVICES[kind]
        if model not in cfg["available"]:
            self._json(400, {"error": f"unknown model: {model}", "available": cfg["available"]})
            return

        current = get_active(kind)
        if model == current and check_model_endpoint(kind, model):
            self._json(200, {"model": model, "status": "already_active"})
            return

        acquired = _locks[kind].acquire(blocking=False)
        if not acquired:
            if _switching[kind] == model:
                self._json(202, {"model": model, "status": "switching"})
            else:
                self._json(409, {"error": f"{kind} switch in progress", "switching_to": _switching[kind]})
            return

        _switching[kind] = model
        _switch_error[kind] = None
        print(f"Switching {kind.upper()}: {current} -> {model}")
        thread = threading.Thread(
            target=_do_switch_background, args=(kind, model, cfg["switch"]),
            daemon=True,
        )
        thread.start()
        self._json(202, {"model": model, "status": "switching"})

    def do_GET(self):
        kind_map = {"/stt-status": "stt", "/llm-status": "llm", "/tts-status": "tts"}
        kind = kind_map.get(self.path)

        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
            return

        if self.path == "/all-status":
            result = {}
            for k in ["stt", "llm", "tts"]:
                result[k] = self._build_status(k)
            self._json(200, result)
            return

        if not kind:
            self._json(404, {"error": "not found"})
            return

        self._json(200, self._build_status(kind))

    def _build_status(self, kind):
        active = get_active(kind)
        status = {
            "model": active,
            "available": SERVICES[kind]["available"],
            "ready": check_model_endpoint(kind, active),
        }
        if _switching[kind]:
            status["switching_to"] = _switching[kind]
        if _switch_error[kind]:
            status["error"] = _switch_error[kind]
        return status

    def _json(self, code, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            print(f"Client disconnected before response (code={code})")

    def log_message(self, fmt, *args):
        print(fmt % args)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8006), Handler)
    print(f"Model manager (k8s) listening on :8006 (namespace={NAMESPACE})")
    server.serve_forever()
