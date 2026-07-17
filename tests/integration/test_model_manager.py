import pytest
import requests


@pytest.mark.timeout(10)
class TestModelManagerViaFrontend:
    """Tests model manager state through the frontend /api/models proxy."""

    def test_llm_available_models(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        data = r.json()
        expected = ["google/gemma-3-4b-it", "Qwen/Qwen3-0.6B", "mistralai/Mistral-7B-Instruct-v0.3"]
        for model in expected:
            assert model in data["llm"], f"{model} not in LLM list"

    def test_tts_available_models(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        data = r.json()
        expected = ["Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "mistralai/Voxtral-4B-TTS-2603"]
        for model in expected:
            assert model in data["tts"], f"{model} not in TTS list"

    def test_stt_available_models(self, urls):
        r = requests.get(f"{urls['frontend']}/api/models", timeout=5)
        data = r.json()
        expected = ["Systran/faster-whisper-large-v3", "Qwen/Qwen3-ASR-0.6B"]
        for model in expected:
            assert model in data["stt"], f"{model} not in STT list"

    def test_active_models_in_available(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        assert data["stt_active"] in data["stt"]
        assert data["llm_active"] in data["llm"]
        assert data["tts_active"] in data["tts"]


@pytest.mark.timeout(10)
class TestModelManagerDirect:
    """Direct model manager tests — only work locally or with port 8006 exposed."""

    def _skip_if_remote(self, is_local):
        if not is_local:
            pytest.skip("port 8006 not exposed remotely")

    def test_stt_status(self, urls, is_local):
        self._skip_if_remote(is_local)
        r = requests.get(f"{urls['model_manager']}/stt-status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "model" in data
        assert "available" in data

    def test_llm_status(self, urls, is_local):
        self._skip_if_remote(is_local)
        r = requests.get(f"{urls['model_manager']}/llm-status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "model" in data
        assert "available" in data

    def test_tts_status(self, urls, is_local):
        self._skip_if_remote(is_local)
        r = requests.get(f"{urls['model_manager']}/tts-status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "model" in data
        assert "available" in data


@pytest.mark.timeout(10)
class TestModelSwitchErrors:
    """Error handling for model switch — works via frontend API."""

    def test_switch_stt_missing_model(self, urls):
        r = requests.post(f"{urls['frontend']}/api/switch-stt", json={}, timeout=5)
        assert r.status_code == 400

    def test_switch_stt_already_active(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        current = data["stt_active"]
        r = requests.post(
            f"{urls['frontend']}/api/switch-stt",
            json={"model": current},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "already_active"

    def test_switch_llm_missing_model(self, urls):
        r = requests.post(f"{urls['frontend']}/api/switch-llm", json={}, timeout=5)
        assert r.status_code == 400

    def test_switch_llm_already_active(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        current = data["llm_active"]
        r = requests.post(
            f"{urls['frontend']}/api/switch-llm",
            json={"model": current},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "already_active"

    def test_switch_tts_already_active(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        current = data["tts_active"]
        r = requests.post(
            f"{urls['frontend']}/api/switch-tts",
            json={"model": current},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "already_active"


@pytest.mark.slow
@pytest.mark.timeout(300)
class TestModelSwitchRoundTrip:
    def test_switch_stt_round_trip(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        original = data["stt_active"]
        target = "Qwen/Qwen3-ASR-0.6B" if "whisper" in original.lower() else "Systran/faster-whisper-large-v3"

        r = requests.post(
            f"{urls['frontend']}/api/switch-stt",
            json={"model": target},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        assert data["stt_active"] == target

        r = requests.post(
            f"{urls['frontend']}/api/switch-stt",
            json={"model": original},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_switch_llm_round_trip(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        original = data["llm_active"]
        target = "Qwen/Qwen3-0.6B" if original != "Qwen/Qwen3-0.6B" else "google/gemma-3-4b-it"

        r = requests.post(
            f"{urls['frontend']}/api/switch-llm",
            json={"model": target},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        assert data["llm_active"] == target

        r = requests.post(
            f"{urls['frontend']}/api/switch-llm",
            json={"model": original},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_switch_tts_round_trip(self, urls):
        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        original = data["tts_active"]
        target = "mistralai/Voxtral-4B-TTS-2603" if "Qwen" in original else "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

        r = requests.post(
            f"{urls['frontend']}/api/switch-tts",
            json={"model": target},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

        data = requests.get(f"{urls['frontend']}/api/models", timeout=5).json()
        assert data["tts_active"] == target

        r = requests.post(
            f"{urls['frontend']}/api/switch-tts",
            json={"model": original},
            timeout=240,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ready"
