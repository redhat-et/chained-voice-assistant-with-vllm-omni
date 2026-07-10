import asyncio
import json
import logging
import os
import time
from collections import defaultdict

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

STT_BASE_URL = os.getenv("STT_BASE_URL", "http://localhost:8001/v1")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-large-v3")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8002/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemma-3-4b-it")

TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://localhost:8003/v1")
TTS_MODEL = os.getenv("TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_VOICE = os.getenv("TTS_VOICE", "vivian")

server = AgentServer()


class VoiceAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful voice assistant. Respond naturally and concisely.",
        )


@server.rtc_session(agent_name="voice-assistant")
async def entrypoint(ctx: JobContext):
    logger.info("=== Disaggregated Voice Pipeline ===")
    logger.info("STT: model=%s url=%s", STT_MODEL, STT_BASE_URL)
    logger.info("LLM: model=%s url=%s", LLM_MODEL, LLM_BASE_URL)
    logger.info("TTS: model=%s voice=%s url=%s", TTS_MODEL, TTS_VOICE, TTS_BASE_URL)

    session = AgentSession(
        stt=openai.STT(
            model=STT_MODEL,
            base_url=STT_BASE_URL,
            api_key="not-needed",
            language="en",
        ),
        llm=openai.LLM(
            model=LLM_MODEL,
            base_url=LLM_BASE_URL,
            api_key="not-needed",
        ),
        tts=openai.TTS(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            base_url=TTS_BASE_URL,
            api_key="not-needed",
        ),
        vad=silero.VAD.load(),
    )

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
                "[%s] STT complete: %.0fms (model=%s)", speech_id, duration_ms, STT_MODEL
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
                LLM_MODEL,
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
                TTS_MODEL,
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
