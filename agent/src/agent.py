import asyncio
import json
import logging
import os
import time
from collections import defaultdict

from vllm_realtime import VLLMRealtimeModel

import yaml
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    MetricsCollectedEvent,
    cli,
    metrics,
)
from livekit.agents.metrics import LLMMetrics, STTMetrics, TTSMetrics
from livekit.plugins import openai, silero

load_dotenv(".env.local")
logger = logging.getLogger("voice-assistant")
logging.basicConfig(level=logging.INFO)

CONFIG_MAP = {
    "stt-llm-tts": "stt-llm-tts-config.yaml",
    "llm-tts": "llm-tts-config.yaml",
    "omni": "omni-config.yaml"
}

def load_config_for_session(session_type):
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_MAP[session_type], 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("Config file not found for session of type %s", session_type)
        return {}

server = AgentServer()

class VoiceAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice assistant. Respond naturally and concisely.",
        )

def build_agent_session(session_type: str):
    config = load_config_for_session(session_type)
    if session_type == "stt-llm-tts":
        stt_base_url = config.get("stt_base_url", "http://localhost:8001/v1")
        stt_model = config.get("stt_model", "Systran/faster-whisper-large-v3")

        llm_base_url = config.get("llm_base_url", "http://localhost:8002/v1")
        llm_model = config.get("llm_model", "google/gemma-3-4b-it")

        tts_base_url = config.get("tts_base_url", "http://localhost:8003/v1")
        tts_model = config.get("tts_model", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        tts_voice = config.get("tts_voice", "vivian")

        logger.info("STT: model=%s url=%s", stt_model, stt_base_url)
        logger.info("LLM: model=%s url=%s", llm_model, llm_base_url)
        logger.info("TTS: model=%s voice=%s url=%s", tts_model, tts_voice, tts_base_url)

        session = AgentSession(
            stt=openai.STT(
                model=stt_model,
                base_url=stt_base_url,
                api_key="not-needed",
                language="en",
            ),
            llm=openai.LLM(
                model=llm_model,
                base_url=llm_base_url,
                api_key="not-needed",
            ),
            tts=openai.TTS(
                model=tts_model,
                voice=tts_voice,
                base_url=tts_base_url,
                api_key="not-needed",
            ),
            vad=silero.VAD.load(),
        )
        return session, {"stt_model": stt_model, "llm_model": llm_model, "tts_model": tts_model}
    elif session_type == "llm-tts":
        return AgentSession(), {}
    elif session_type == "omni":
        base_url = config["base_url"]
        model = config["model"]
        model = VLLMRealtimeModel(
            base_url=base_url,
            model=model,
        )

        session = AgentSession(
            llm=model,
            vad=silero.VAD.load(),
            turn_detection="vad",
        )
        return session, {"omni_model": model}

@server.rtc_session(agent_name="voice-assistant")
async def entrypoint(ctx: JobContext):
    session_type = os.getenv("SESSION_TYPE", "stt-llm-tts")
    logger.info("=== Disaggregated Voice Pipeline ===")
    logger.info("Session type: %s", session_type)

    session, model_info = build_agent_session(session_type)

    turn_metrics: dict[str, dict[str, float]] = defaultdict(dict)

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent):
        m = ev.metrics
        metrics.log_metrics(m)

        speech_id = getattr(m, "speech_id", None)
        if speech_id is None:
            return

        if isinstance(m, STTMetrics):
            duration_ms = m.duration * 1000
            turn_metrics[speech_id]["stt_ms"] = duration_ms
            logger.info(
                "[%s] STT complete: %.0fms (model=%s)", speech_id, duration_ms, model_info.get("stt_model", "unknown")
            )

        elif isinstance(m, LLMMetrics):
            ttft_ms = m.ttft * 1000
            total_ms = m.duration * 1000
            turn_metrics[speech_id]["llm_ttft_ms"] = ttft_ms
            turn_metrics[speech_id]["llm_total_ms"] = total_ms
            logger.info(
                "[%s] LLM complete: ttft=%.0fms total=%.0fms (model=%s)",
                speech_id,
                ttft_ms,
                total_ms,
                model_info.get("llm_model", "unknown"),
            )

        elif isinstance(m, TTSMetrics):
            ttfb_ms = m.ttfb * 1000
            total_ms = m.duration * 1000
            turn_metrics[speech_id]["tts_ttfb_ms"] = ttfb_ms
            turn_metrics[speech_id]["tts_total_ms"] = total_ms
            logger.info(
                "[%s] TTS complete: ttfb=%.0fms total=%.0fms (model=%s)",
                speech_id,
                ttfb_ms,
                total_ms,
                model_info.get("tts_model", "unknown"),
            )

        record = turn_metrics[speech_id]
        if all(k in record for k in ("stt_ms", "llm_ttft_ms", "tts_ttfb_ms")):
            record["speech_id"] = speech_id
            record["total_ms"] = record["stt_ms"] + record["llm_ttft_ms"] + record["tts_ttfb_ms"]
            logger.info(
                "[%s] === Pipeline total: %.0fms (STT=%.0f + LLM_TTFT=%.0f + TTS_TTFB=%.0f) ===",
                speech_id,
                record["total_ms"],
                record["stt_ms"],
                record["llm_ttft_ms"],
                record["tts_ttfb_ms"],
            )
            asyncio.create_task(
                ctx.room.local_participant.publish_data(
                    json.dumps(record),
                    topic="timing",
                    reliable=True,
                )
            )
            del turn_metrics[speech_id]

    await session.start(
        agent=VoiceAssistant(),
        room=ctx.room,
    )
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info("Voice assistant started — disaggregated pipeline active")


if __name__ == "__main__":
    cli.run_app(server)
