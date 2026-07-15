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

interface LlmStatus {
  model: string;
  available: string[];
}

async function fetchLlmStatus(managerUrl: string): Promise<LlmStatus> {
  try {
    const res = await fetch(`${managerUrl}/llm-status`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error("manager unavailable");
    return await res.json();
  } catch {
    const llmUrl = process.env.LLM_BASE_URL ?? "http://llm:8002";
    const loaded = await fetchModels(llmUrl);
    return { model: loaded[0] ?? "", available: loaded };
  }
}

export async function GET() {
  const sttUrl = process.env.STT_BASE_URL ?? "http://stt:8000";
  const ttsUrl = process.env.TTS_BASE_URL ?? "http://tts:8003";
  const managerUrl = process.env.MODEL_MANAGER_URL ?? "http://host.docker.internal:8006";

  const [stt, llmStatus, tts] = await Promise.all([
    fetchModels(sttUrl),
    fetchLlmStatus(managerUrl),
    fetchModels(ttsUrl),
  ]);

  return NextResponse.json({
    stt,
    llm: llmStatus.available,
    tts,
    llm_active: llmStatus.model,
  });
}
