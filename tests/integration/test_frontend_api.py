import pytest
import requests


@pytest.mark.timeout(10)
class TestFrontendModelsAPI:
    def test_api_models_structure(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        assert r.status_code == 200
        data = r.json()
        for key in ("stt", "llm", "tts", "llm_active", "tts_active"):
            assert key in data, f"missing key: {key}"

    def test_api_models_llm_list(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        llm = r.json()["llm"]
        assert len(llm) >= 3, f"expected >=3 LLMs, got {len(llm)}"

    def test_api_models_tts_list(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        tts = r.json()["tts"]
        assert len(tts) >= 2, f"expected >=2 TTS models, got {len(tts)}"


@pytest.mark.timeout(10)
class TestFrontendTokenAPI:
    def test_api_token_returns_connection_details(self, urls):
        r = requests.post(
            f"{urls['frontend']}/api/token",
            json={
                "stt_model": "Systran/faster-whisper-large-v3",
                "llm_model": "google/gemma-3-4b-it",
                "tts_model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "tts_voice": "vivian",
            },
            timeout=5,
        )
        assert r.status_code == 200
        data = r.json()
        for key in ("serverUrl", "roomName", "participantName", "participantToken"):
            assert key in data, f"missing key: {key}"
