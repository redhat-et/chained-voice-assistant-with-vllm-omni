import { NextResponse } from "next/server";

interface VllmModel {
  id: string;
}

async function fetchModels(baseUrl: string): Promise<string[]> {
  try {
    const res = await fetch(`${baseUrl}/v1/models`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) return [];
    const data = await res.json();
    return (data.data ?? []).map((m: VllmModel) => m.id);
  } catch {
    return [];
  }
}

export async function GET() {
  const sttUrl = process.env.STT_BASE_URL ?? "http://stt:8000";
  const llmUrl = process.env.LLM_BASE_URL ?? "http://llm:8002";
  const ttsUrl = process.env.TTS_BASE_URL ?? "http://tts:8003";

  const [stt, llm, tts] = await Promise.all([
    fetchModels(sttUrl),
    fetchModels(llmUrl),
    fetchModels(ttsUrl),
  ]);

  return NextResponse.json({ stt, llm, tts });
}
