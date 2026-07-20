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

COMPOSE_DIR = os.environ.get(
    "COMPOSE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
)

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

def wait_for_model(model, port, timeout=600):
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
    print(f"Model manager listening on :8006 (compose_dir={COMPOSE_DIR})")
    server.serve_forever()
