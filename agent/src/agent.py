import asyncio
import json
import logging
import os
from collections import defaultdict

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    cli,
)
from livekit.agents.voice.events import (
    UserStateChangedEvent,
    AgentStateChangedEvent,
    UserInputTranscribedEvent,
    MetricsCollectedEvent,
    ErrorEvent,
)
from livekit.plugins import openai, silero

load_dotenv(".env.local")
logger = logging.getLogger("voice-assistant")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s - %(message)s')

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

    stt_model, llm_model, tts_model, tts_voice = STT_MODEL, LLM_MODEL, TTS_MODEL, TTS_VOICE
    sources = {"stt": "env", "llm": "env", "tts": "env", "voice": "env"}

    raw_meta = getattr(ctx.job, "metadata", None) or ""
    if raw_meta.strip():
        try:
            meta = json.loads(raw_meta)
            if meta.get("stt_model"):
                stt_model = meta["stt_model"]
                sources["stt"] = "metadata"
            if meta.get("llm_model"):
                llm_model = meta["llm_model"]
                sources["llm"] = "metadata"
            if meta.get("tts_model"):
                tts_model = meta["tts_model"]
                sources["tts"] = "metadata"
            if meta.get("tts_voice"):
                tts_voice = meta["tts_voice"]
                sources["voice"] = "metadata"
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse job metadata, using env defaults: %s", e)

    logger.info("STT: model=%s url=%s (source=%s)", stt_model, STT_BASE_URL, sources["stt"])
    logger.info("LLM: model=%s url=%s (source=%s)", llm_model, LLM_BASE_URL, sources["llm"])
    logger.info("TTS: model=%s voice=%s url=%s (source=%s, voice=%s)",
                tts_model, tts_voice, TTS_BASE_URL, sources["tts"], sources["voice"])

    session = AgentSession(
        stt=openai.STT(
            model=stt_model,
            base_url=STT_BASE_URL,
            api_key="not-needed",
            language="en",
        ),
        llm=openai.LLM(
            model=llm_model,
            base_url=LLM_BASE_URL,
            api_key="not-needed",
        ),
        tts=openai.TTS(
            model=tts_model,
            voice=tts_voice,
            base_url=TTS_BASE_URL,
            api_key="not-needed",
            response_format="pcm",
        ),
        vad=silero.VAD.load(),
        turn_detection=None,
    )

    turn_metrics = defaultdict(dict)

    @session.on("user_state_changed")
    def on_user_state(ev: UserStateChangedEvent):
        logger.info(">>> USER STATE: %s -> %s", ev.old_state, ev.new_state)

    @session.on("agent_state_changed")
    def on_agent_state(ev: AgentStateChangedEvent):
        logger.info(">>> AGENT STATE: %s -> %s", ev.old_state, ev.new_state)

    @session.on("user_input_transcribed")
    def on_transcribed(ev: UserInputTranscribedEvent):
        logger.info(">>> TRANSCRIBED: '%s' (final=%s)", ev.transcript, ev.is_final)

    @session.on("error")
    def on_error(ev: ErrorEvent):
        logger.error(">>> ERROR: type=%s label=%s error=%r recoverable=%s",
                      ev.error.type, ev.error.label, ev.error.error, ev.error.recoverable)

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent):
        m = ev.metrics
        speech_id = getattr(m, "speech_id", None) or "unknown"

        if m.type == "stt_metrics":
            dur_ms = m.duration * 1000
            turn_metrics[speech_id]["stt_ms"] = dur_ms
            logger.info("[%s] STT complete: %.0fms (model=%s)", speech_id, dur_ms, stt_model)

        elif m.type == "llm_metrics":
            ttft_ms = m.ttft * 1000
            dur_ms = m.duration * 1000
            turn_metrics[speech_id]["llm_ttft_ms"] = ttft_ms
            turn_metrics[speech_id]["llm_total_ms"] = dur_ms
            logger.info("[%s] LLM complete: ttft=%.0fms total=%.0fms (model=%s)",
                         speech_id, ttft_ms, dur_ms, llm_model)

        elif m.type == "tts_metrics":
            ttfb_ms = m.ttfb * 1000
            dur_ms = m.duration * 1000
            turn_metrics[speech_id]["tts_ttfb_ms"] = ttfb_ms
            turn_metrics[speech_id]["tts_total_ms"] = dur_ms
            logger.info("[%s] TTS complete: ttfb=%.0fms total=%.0fms (model=%s)",
                         speech_id, ttfb_ms, dur_ms, tts_model)

            data = turn_metrics[speech_id]
            stt = data.get("stt_ms", 0)
            llm_ttft = data.get("llm_ttft_ms", 0)
            tts_ttfb = ttfb_ms
            total = stt + llm_ttft + tts_ttfb

            logger.info("[%s] === Pipeline total: %.0fms (STT=%.0f + LLM_TTFT=%.0f + TTS_TTFB=%.0f) ===",
                         speech_id, total, stt, llm_ttft, tts_ttfb)

            timing_payload = json.dumps({
                "speech_id": speech_id,
                "stt_ms": stt,
                "llm_ttft_ms": llm_ttft,
                "llm_total_ms": data.get("llm_total_ms", 0),
                "tts_ttfb_ms": tts_ttfb,
                "tts_total_ms": dur_ms,
                "total_ms": total,
            })
            asyncio.create_task(
                ctx.room.local_participant.publish_data(timing_payload, topic="timing")
            )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await session.start(agent=VoiceAssistant(), room=ctx.room)
    logger.info("Voice assistant started — disaggregated pipeline active")


if __name__ == "__main__":
    cli.run_app(server)
