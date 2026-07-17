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

interface ServiceStatus {
  model: string;
  available: string[];
}

async function fetchServiceStatus(managerUrl: string, endpoint: string, fallbackUrl: string): Promise<ServiceStatus> {
  try {
    const res = await fetch(`${managerUrl}/${endpoint}`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error("manager unavailable");
    return await res.json();
  } catch {
    const loaded = await fetchModels(fallbackUrl);
    return { model: loaded[0] ?? "", available: loaded };
  }
}

export async function GET() {
  const managerUrl = process.env.MODEL_MANAGER_URL ?? "http://host.docker.internal:8006";
  const sttFallback = process.env.STT_BASE_URL ?? "http://stt:8000";
  const llmFallback = process.env.LLM_BASE_URL ?? "http://llm:8002";
  const ttsFallback = process.env.TTS_BASE_URL ?? "http://tts:8003";

  const [sttStatus, llmStatus, ttsStatus] = await Promise.all([
    fetchServiceStatus(managerUrl, "stt-status", sttFallback),
    fetchServiceStatus(managerUrl, "llm-status", llmFallback),
    fetchServiceStatus(managerUrl, "tts-status", ttsFallback),
  ]);

  return NextResponse.json({
    stt: sttStatus.available,
    llm: llmStatus.available,
    tts: ttsStatus.available,
    stt_active: sttStatus.model,
    llm_active: llmStatus.model,
    tts_active: ttsStatus.model,
  });
}
