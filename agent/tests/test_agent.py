import json
import sys
import types
from unittest import mock

for mod_name in [
    "dotenv", "livekit", "livekit.agents", "livekit.agents.voice",
    "livekit.agents.voice.events", "livekit.plugins", "livekit.plugins.openai",
    "livekit.plugins.silero",
]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

lk_agents = sys.modules["livekit.agents"]
for attr in ["Agent", "AgentServer", "AgentSession", "AutoSubscribe", "JobContext", "cli"]:
    setattr(lk_agents, attr, mock.MagicMock())

lk_events = sys.modules["livekit.agents.voice.events"]
for attr in ["UserStateChangedEvent", "AgentStateChangedEvent",
             "UserInputTranscribedEvent", "MetricsCollectedEvent", "ErrorEvent"]:
    setattr(lk_events, attr, mock.MagicMock())

lk_openai = sys.modules["livekit.plugins.openai"]
for attr in ["STT", "LLM", "TTS"]:
    setattr(lk_openai, attr, mock.MagicMock())

lk_silero = sys.modules["livekit.plugins.silero"]
lk_silero.VAD = mock.MagicMock()

dotenv = sys.modules["dotenv"]
dotenv.load_dotenv = mock.MagicMock()

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent import resolve_models, build_instructions

DEFAULTS = {
    "stt": "Systran/faster-whisper-large-v3",
    "llm": "google/gemma-3-4b-it",
    "tts": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "voice": "vivian",
}


class TestResolveModels:
    def test_empty_metadata_uses_defaults(self):
        models, sources = resolve_models("", DEFAULTS)
        assert models == DEFAULTS
        assert all(v == "env" for v in sources.values())

    def test_none_metadata_falls_back(self):
        models, sources = resolve_models(None, DEFAULTS)
        assert models == DEFAULTS

    def test_valid_json_overrides_all(self):
        meta = json.dumps({
            "stt_model": "custom/stt",
            "llm_model": "custom/llm",
            "tts_model": "custom/tts",
            "tts_voice": "alloy",
        })
        models, sources = resolve_models(meta, DEFAULTS)
        assert models["stt"] == "custom/stt"
        assert models["llm"] == "custom/llm"
        assert models["tts"] == "custom/tts"
        assert models["voice"] == "alloy"
        assert all(v == "metadata" for v in sources.values())

    def test_partial_json_overrides_specified_only(self):
        meta = json.dumps({"llm_model": "custom/llm"})
        models, sources = resolve_models(meta, DEFAULTS)
        assert models["llm"] == "custom/llm"
        assert sources["llm"] == "metadata"
        assert models["stt"] == DEFAULTS["stt"]
        assert sources["stt"] == "env"

    def test_invalid_json_falls_back(self):
        models, sources = resolve_models("{bad json", DEFAULTS)
        assert models == DEFAULTS
        assert all(v == "env" for v in sources.values())


class TestBuildInstructions:
    def test_non_qwen_no_think_absent(self):
        result = build_instructions("google/gemma-3-4b-it")
        assert "/no_think" not in result

    def test_qwen_gets_no_think(self):
        result = build_instructions("Qwen/Qwen3-0.6B")
        assert "/no_think" in result

    def test_qwen_case_insensitive(self):
        result = build_instructions("QWEN/some-model")
        assert "/no_think" in result
