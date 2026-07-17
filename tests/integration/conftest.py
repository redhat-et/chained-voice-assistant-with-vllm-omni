import os
import time

import pytest
import requests

PORTS = {
    "stt": 8001,
    "llm": 8002,
    "tts": 8003,
    "model_manager": 8006,
    "frontend": 3000,
    "livekit": 7880,
}


@pytest.fixture(scope="session")
def host():
    return os.environ.get("VOICE_PIPELINE_HOST", "localhost")


@pytest.fixture(scope="session")
def urls(host):
    return {name: f"http://{host}:{port}" for name, port in PORTS.items()}


@pytest.fixture(scope="session")
def is_local(host):
    return host in ("localhost", "127.0.0.1")


def wait_for_model(host, port, model_substr, timeout=180):
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/v1/models"
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, timeout=3)
            if r.ok:
                models = [m["id"] for m in r.json().get("data", [])]
                if any(model_substr in m for m in models):
                    return True
        except requests.RequestException:
            pass
        time.sleep(3)
    return False


def port_reachable(host, port, timeout=3):
    try:
        r = requests.get(f"http://{host}:{port}/", timeout=timeout)
        return True
    except requests.RequestException:
        return False
