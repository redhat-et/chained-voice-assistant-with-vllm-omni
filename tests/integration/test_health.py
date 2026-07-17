import pytest
import requests


@pytest.mark.timeout(10)
class TestServiceHealth:
    """Health checks via the frontend API (works remotely — ports 8001-8003 are internal)."""

    def test_frontend_reachable(self, urls):
        r = requests.get(urls["frontend"], timeout=5)
        assert r.status_code == 200

    def test_livekit_reachable(self, urls):
        r = requests.get(urls["livekit"], timeout=5)
        assert r.status_code in (200, 404)

    def test_all_services_via_models_api(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert len(data["stt"]) > 0, "STT returned no models"
        assert len(data["llm"]) > 0, "LLM returned no models"
        assert len(data["tts"]) > 0, "TTS returned no models"


@pytest.mark.timeout(10)
class TestDirectServiceHealth:
    """Direct health checks — only work locally or with all ports exposed."""

    def test_stt_responding(self, urls, is_local):
        if not is_local:
            pytest.skip("ports 8001-8003 not exposed remotely")
        r = requests.get(f"{urls['stt']}/v1/models", timeout=5)
        assert r.status_code == 200
        assert len(r.json().get("data", [])) > 0

    def test_llm_responding(self, urls, is_local):
        if not is_local:
            pytest.skip("ports 8001-8003 not exposed remotely")
        r = requests.get(f"{urls['llm']}/v1/models", timeout=5)
        assert r.status_code == 200

    def test_tts_responding(self, urls, is_local):
        if not is_local:
            pytest.skip("ports 8001-8003 not exposed remotely")
        r = requests.get(f"{urls['tts']}/v1/models", timeout=5)
        assert r.status_code == 200
