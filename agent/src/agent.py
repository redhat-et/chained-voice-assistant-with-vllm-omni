import asyncio
import contextlib
import json
import logging
import os
import struct
from collections import defaultdict
from collections.abc import AsyncIterable, AsyncGenerator

import httpx
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    cli,
    tokenize,
    tts,
)
from livekit.agents.llm import function_tool
from livekit.agents.voice import ModelSettings
from livekit.agents.voice.events import (
    UserStateChangedEvent,
    AgentStateChangedEvent,
    UserInputTranscribedEvent,
    MetricsCollectedEvent,
    ErrorEvent,
)
from livekit.plugins import openai, silero
from livekit.plugins.openai.tts import AUDIO_STREAM_MODELS

load_dotenv(".env.local")
logger = logging.getLogger("voice-assistant")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s - %(message)s')

STT_HOST = os.getenv("STT_BASE_URL", "http://localhost:8001/v1").rstrip("/").rsplit("/v1", 1)[0]
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-large-v3")

STT_PATHS = {
    "Qwen/Qwen3-ASR-0.6B": "/compat/openai/v1",
}

def stt_base_url(model: str) -> str:
    return STT_HOST + STT_PATHS.get(model, "/v1")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8002/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemma-3-4b-it")

TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://localhost:8003/v1")
TTS_MODEL = os.getenv("TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_VOICE = os.getenv("TTS_VOICE", "vivian")

AUDIO_STREAM_MODELS.update({
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "mistralai/Voxtral-4B-TTS-2603",
})

server = AgentServer()


def resolve_models(raw_meta, defaults):
    stt, llm, tts, voice = defaults["stt"], defaults["llm"], defaults["tts"], defaults["voice"]
    sources = {"stt": "env", "llm": "env", "tts": "env", "voice": "env"}

    if raw_meta and raw_meta.strip():
        try:
            meta = json.loads(raw_meta)
            if meta.get("stt_model"):
                stt = meta["stt_model"]
                sources["stt"] = "metadata"
            if meta.get("llm_model"):
                llm = meta["llm_model"]
                sources["llm"] = "metadata"
            if meta.get("tts_model"):
                tts = meta["tts_model"]
                sources["tts"] = "metadata"
            if meta.get("tts_voice"):
                voice = meta["tts_voice"]
                sources["voice"] = "metadata"
        except (json.JSONDecodeError, TypeError):
            pass

    return {"stt": stt, "llm": llm, "tts": tts, "voice": voice}, sources


async def strip_thinking_tags(stream):
    async for chunk in stream:
        cleaned = chunk.replace("<think>", "").replace("</think>", "")
        if cleaned:
            yield cleaned


def build_instructions(llm_model):
    instructions = "You are a helpful voice assistant. Respond naturally and concisely. You have access to tools — use them when appropriate."
    if "qwen" in llm_model.lower():
        instructions += " /no_think"
    return instructions


WMO_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
    77: "snow grains", 80: "slight rain showers", 81: "moderate rain showers",
    82: "violent rain showers", 85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


@function_tool()
async def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    async with httpx.AsyncClient(timeout=10) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
        )
        geo_data = geo.json()
        results = geo_data.get("results")
        if not results:
            return f"Sorry, I could not find a location called {location}."

        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name", location)
        country = place.get("country", "")

        weather = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            },
        )
        current = weather.json().get("current", {})
        temp = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        code = current.get("weather_code", -1)
        condition = WMO_WEATHER_CODES.get(code, "unknown conditions")

        return (
            f"{name}, {country}: {condition}, "
            f"{temp} degrees Celsius, "
            f"{humidity} percent humidity, "
            f"wind {wind} kilometers per hour."
        )


TARGET_RMS = 3000
MIN_RMS = 50
MAX_GAIN = 3.0
TTS_MIN_TOKEN_LEN = int(os.getenv("TTS_MIN_TOKEN_LEN", "150"))


def normalize_audio_frame(frame: rtc.AudioFrame, target_rms: float = TARGET_RMS) -> rtc.AudioFrame:
    data = bytes(frame.data)
    n_samples = len(data) // 2
    if n_samples == 0:
        return frame

    samples = struct.unpack(f"<{n_samples}h", data)
    sum_sq = sum(s * s for s in samples)
    rms = (sum_sq / n_samples) ** 0.5

    if rms < MIN_RMS:
        return frame

    gain = min(target_rms / rms, MAX_GAIN)
    if 0.95 <= gain <= 1.05:
        return frame

    normalized = struct.pack(
        f"<{n_samples}h",
        *(max(-32768, min(32767, int(s * gain))) for s in samples),
    )
    return rtc.AudioFrame(
        data=normalized,
        sample_rate=frame.sample_rate,
        num_channels=frame.num_channels,
        samples_per_channel=frame.samples_per_channel,
    )


class VoiceAssistant(Agent):
    def __init__(self, instructions: str = "You are a helpful voice assistant. Respond naturally and concisely.") -> None:
        super().__init__(instructions=instructions, tools=[get_weather])

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        activity = self._get_activity_or_raise()
        if activity.tts is None:
            raise RuntimeError("`tts_node` called but no TTS is available.")

        wrapped_tts = activity.tts
        if not activity.tts.capabilities.streaming:
            wrapped_tts = tts.StreamAdapter(
                tts=wrapped_tts,
                sentence_tokenizer=tokenize.blingfire.SentenceTokenizer(
                    min_sentence_len=TTS_MIN_TOKEN_LEN,
                    retain_format=True,
                ),
            )

        conn_options = activity.session.conn_options.tts_conn_options
        async with wrapped_tts.stream(conn_options=conn_options) as stream:

            async def _forward_input() -> None:
                async for chunk in text:
                    stream.push_text(chunk)
                stream.end_input()

            forward_task = asyncio.create_task(_forward_input())
            try:
                async for ev in stream:
                    yield normalize_audio_frame(ev.frame)
            finally:
                forward_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await forward_task


@server.rtc_session(agent_name="voice-assistant")
async def entrypoint(ctx: JobContext):
    logger.info("=== Disaggregated Voice Pipeline ===")

    defaults = {"stt": STT_MODEL, "llm": LLM_MODEL, "tts": TTS_MODEL, "voice": TTS_VOICE}
    raw_meta = getattr(ctx.job, "metadata", None) or ""
    models, sources = resolve_models(raw_meta, defaults)
    stt_model, llm_model, tts_model, tts_voice = models["stt"], models["llm"], models["tts"], models["voice"]

    stt_url = stt_base_url(stt_model)
    logger.info("STT: model=%s url=%s (source=%s)", stt_model, stt_url, sources["stt"])
    logger.info("LLM: model=%s url=%s (source=%s)", llm_model, LLM_BASE_URL, sources["llm"])
    logger.info("TTS: model=%s voice=%s url=%s (source=%s, voice=%s)",
                tts_model, tts_voice, TTS_BASE_URL, sources["tts"], sources["voice"])

    session = AgentSession(
        stt=openai.STT(
            model=stt_model,
            base_url=stt_url,
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
        tts_text_transforms=["filter_markdown", "filter_emoji", strip_thinking_tags],
    )

    turn_metrics = defaultdict(dict)
    last_stt_ms = 0.0

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

    def publish_timing(speech_id):
        data = turn_metrics[speech_id]
        if "has_tts" not in data:
            return

        stt = data.get("stt_ms", last_stt_ms)
        llm_ttft = data.get("llm_ttft_ms", 0)
        tts_ttfb = data["tts_ttfb_ms"]
        total = stt + llm_ttft + tts_ttfb

        logger.info("[%s] === Pipeline total: %.0fms (STT=%.0f + LLM_TTFT=%.0f + TTS_TTFB=%.0f) ===",
                     speech_id, total, stt, llm_ttft, tts_ttfb)

        timing_payload = json.dumps({
            "speech_id": speech_id,
            "stt_ms": stt,
            "stt_audio_duration_ms": data.get("stt_audio_duration_ms", 0),
            "llm_ttft_ms": llm_ttft,
            "llm_total_ms": data.get("llm_total_ms", 0),
            "llm_tokens_per_second": data.get("llm_tokens_per_second", 0),
            "llm_prompt_tokens": data.get("llm_prompt_tokens", 0),
            "llm_completion_tokens": data.get("llm_completion_tokens", 0),
            "tts_ttfb_ms": tts_ttfb,
            "tts_total_ms": data.get("tts_total_ms", 0),
            "tts_audio_duration_ms": data.get("tts_audio_duration_ms", 0),
            "tts_characters": data.get("tts_characters", 0),
            "total_ms": total,
        })
        asyncio.create_task(
            ctx.room.local_participant.publish_data(timing_payload, topic="timing")
        )

    @session.on("metrics_collected")
    def on_metrics(ev: MetricsCollectedEvent):
        nonlocal last_stt_ms
        m = ev.metrics
        speech_id = getattr(m, "speech_id", None) or "unknown"

        if m.type == "stt_metrics":
            dur_ms = m.duration * 1000
            last_stt_ms = dur_ms
            turn_metrics[speech_id]["stt_audio_duration_ms"] = m.audio_duration * 1000
            logger.info("[stt] STT complete: %.0fms (model=%s)", dur_ms, stt_model)

        elif m.type == "llm_metrics":
            ttft_ms = m.ttft * 1000
            dur_ms = m.duration * 1000
            turn_metrics[speech_id]["stt_ms"] = last_stt_ms
            turn_metrics[speech_id]["llm_ttft_ms"] = ttft_ms
            turn_metrics[speech_id]["llm_total_ms"] = dur_ms
            turn_metrics[speech_id]["llm_tokens_per_second"] = m.tokens_per_second
            turn_metrics[speech_id]["llm_prompt_tokens"] = m.prompt_tokens
            turn_metrics[speech_id]["llm_completion_tokens"] = m.completion_tokens
            logger.info("[%s] LLM complete: ttft=%.0fms total=%.0fms tok/s=%.1f prompt=%d completion=%d (model=%s)",
                         speech_id, ttft_ms, dur_ms, m.tokens_per_second,
                         m.prompt_tokens, m.completion_tokens, llm_model)
            publish_timing(speech_id)

        elif m.type == "tts_metrics":
            ttfb_ms = m.ttfb * 1000
            dur_ms = m.duration * 1000
            data = turn_metrics[speech_id]
            logger.info("[%s] TTS segment: ttfb=%.0fms total=%.0fms audio=%.1fs chars=%d (model=%s)",
                         speech_id, ttfb_ms, dur_ms, m.audio_duration,
                         m.characters_count, tts_model)

            if "has_tts" not in data:
                data["has_tts"] = True
                data["tts_ttfb_ms"] = ttfb_ms
                data["tts_total_ms"] = dur_ms
                data["tts_audio_duration_ms"] = m.audio_duration * 1000
                data["tts_characters"] = m.characters_count
                publish_timing(speech_id)

    instructions = build_instructions(llm_model)

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await session.start(agent=VoiceAssistant(instructions=instructions), room=ctx.room)
    logger.info("Voice assistant started — disaggregated pipeline active")


if __name__ == "__main__":
    cli.run_app(server)
