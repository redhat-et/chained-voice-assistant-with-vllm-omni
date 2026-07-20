#!/usr/bin/env python3
"""K8s-native HTTP API that swaps active STT, LLM, and TTS models.

Replaces the docker-compose model-manager with Kubernetes API calls:
- Updates the model-config ConfigMap
- Patches deployments to trigger rollout restarts
- Waits for new pods to become ready
"""

import http.server
import json
import os
import threading
import time

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

_locks = {"stt": threading.Lock(), "llm": threading.Lock(), "tts": threading.Lock()}
_switching = {"stt": None, "llm": None, "tts": None}

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()


def get_configmap_data():
    cm = core_v1.read_namespaced_config_map(CONFIGMAP_NAME, NAMESPACE)
    return cm.data or {}


def patch_configmap(updates: dict):
    core_v1.patch_namespaced_config_map(
        CONFIGMAP_NAME, NAMESPACE, {"data": updates}
    )


def restart_deployment(name):
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


def wait_for_ready(deployment_name, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dep = apps_v1.read_namespaced_deployment(deployment_name, NAMESPACE)
        ready = dep.status.ready_replicas or 0
        updated = dep.status.updated_replicas or 0
        desired = dep.spec.replicas or 1
        if ready >= desired and updated >= desired:
            return True
        time.sleep(5)
    return False


def get_active(kind):
    data = get_configmap_data()
    key_map = {"stt": "STT_ACTIVE_MODEL", "llm": "LLM_ACTIVE_MODEL", "tts": "TTS_ACTIVE_MODEL"}
    defaults = {"stt": AVAILABLE_STT[0], "llm": AVAILABLE_LLM[0], "tts": AVAILABLE_TTS[0]}
    return data.get(key_map[kind], defaults[kind])


def switch_stt(model):
    patch_configmap({"STT_ACTIVE_MODEL": model})
    patch_stt_deployment(model)
    return wait_for_ready("stt")


def switch_llm(model):
    patch_configmap({"LLM_ACTIVE_MODEL": model})
    restart_deployment("llm")
    return wait_for_ready("llm")


def switch_tts(model):
    patch_configmap({"TTS_ACTIVE_MODEL": model})
    restart_deployment("tts")
    return wait_for_ready("tts")


SERVICES = {
    "stt": {"available": AVAILABLE_STT, "switch": switch_stt},
    "llm": {"available": AVAILABLE_LLM, "switch": switch_llm},
    "tts": {"available": AVAILABLE_TTS, "switch": switch_tts},
}


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
        if model == current:
            self._json(200, {"model": model, "status": "already_active"})
            return

        acquired = _locks[kind].acquire(blocking=False)
        if not acquired:
            if _switching[kind] == model:
                print(f"Switch {kind} to {model} already in progress, waiting...")
                ok = wait_for_ready({"stt": "stt", "llm": "llm", "tts": "tts"}[kind])
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
            if cfg["switch"](model):
                self._json(200, {"model": model, "status": "ready"})
            else:
                self._json(504, {"model": model, "status": "timeout"})
        finally:
            _switching[kind] = None
            _locks[kind].release()

    def do_GET(self):
        kind_map = {"/stt-status": "stt", "/llm-status": "llm", "/tts-status": "tts"}
        kind = kind_map.get(self.path)
        if not kind:
            if self.path == "/healthz":
                self._json(200, {"status": "ok"})
                return
            self._json(404, {"error": "not found"})
            return

        status = {"model": get_active(kind), "available": SERVICES[kind]["available"]}
        if _switching[kind]:
            status["switching_to"] = _switching[kind]
        self._json(200, status)

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
