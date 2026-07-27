import { NextResponse } from "next/server";

async function ensureModel(managerUrl: string, kind: string, model: string, timeoutMs = 300_000): Promise<void> {
  const statusRes = await fetch(`${managerUrl}/${kind}-status`, { signal: AbortSignal.timeout(5000) });
  if (statusRes.ok) {
    const status = await statusRes.json();
    if (status.model === model && status.ready) return;
  }

  const switchRes = await fetch(`${managerUrl}/switch-${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
    signal: AbortSignal.timeout(10_000),
  });
  if (switchRes.status === 200) return;

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 5000));
    const poll = await fetch(`${managerUrl}/${kind}-status`, { signal: AbortSignal.timeout(5000) });
    if (!poll.ok) continue;
    const s = await poll.json();
    if (s.error) throw new Error(`${kind} switch failed: ${s.error}`);
    if (s.ready && s.model === model) return;
  }
  throw new Error(`${kind} switch to ${model} timed out`);
}

export async function POST(request: Request) {
  const managerUrl = process.env.MODEL_MANAGER_URL ?? "http://model-manager:8006";
  const llmBase = process.env.LLM_BASE_URL ?? "http://llm-server:8002";
  const ttsBase = process.env.TTS_BASE_URL ?? "http://tts-server:8003";

  const formData = await request.formData();
  const file = formData.get("audio") as File | null;
  const llmModel = (formData.get("llm_model") as string) || "Qwen/Qwen2-Audio-7B-Instruct";
  const ttsModel = (formData.get("tts_model") as string) || "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice";
  const ttsVoice = (formData.get("tts_voice") as string) || "vivian";

  if (!file) {
    return NextResponse.json({ error: "audio file is required" }, { status: 400 });
  }

  try {
    await Promise.all([
      ensureModel(managerUrl, "llm", llmModel),
      ensureModel(managerUrl, "tts", ttsModel),
    ]);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Model switch failed";
    return NextResponse.json({ error: msg }, { status: 503 });
  }

  const arrayBuf = await file.arrayBuffer();
  const b64 = Buffer.from(arrayBuf).toString("base64");
  const mimeType = file.type || "audio/wav";
  const audioUri = `data:${mimeType};base64,${b64}`;

  try {
    const llmRes = await fetch(`${llmBase}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: llmModel,
        messages: [
          {
            role: "user",
            content: [
              { type: "audio_url", audio_url: { url: audioUri } },
              { type: "text", text: "Respond to this audio message." },
            ],
          },
        ],
        max_tokens: 512,
      }),
      signal: AbortSignal.timeout(120_000),
    });

    if (!llmRes.ok) {
      const err = await llmRes.text();
      return NextResponse.json({ error: `Audio LLM error: ${err}` }, { status: 502 });
    }

    const llmData = await llmRes.json();
    const text = llmData.choices?.[0]?.message?.content ?? "";

    if (!text) {
      return NextResponse.json({ error: "Audio LLM returned empty response" }, { status: 502 });
    }

    const ttsRes = await fetch(`${ttsBase}/v1/audio/speech`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: ttsModel,
        voice: ttsVoice,
        input: text,
        response_format: "wav",
      }),
      signal: AbortSignal.timeout(120_000),
    });

    if (!ttsRes.ok) {
      return NextResponse.json({ text, audio: null, error: "TTS failed but text is available" });
    }

    const audioBuf = await ttsRes.arrayBuffer();
    const audioB64 = Buffer.from(audioBuf).toString("base64");

    return NextResponse.json({ text, audio: audioB64 });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: `Pipeline error: ${msg}` }, { status: 504 });
  }
}
