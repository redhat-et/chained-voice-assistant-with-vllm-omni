"use client";

export interface TimingData {
  speech_id: string;
  stt_ms: number;
  llm_ttft_ms: number;
  llm_total_ms: number;
  tts_ttfb_ms: number;
  tts_total_ms: number;
  total_ms: number;
}

function formatMs(ms: number): string {
  if (ms < 0) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function TurnRow({ timing, index }: { timing: TimingData; index: number }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg bg-zinc-900/80 px-4 py-2 text-xs font-mono backdrop-blur-sm border border-zinc-800">
      <span className="text-zinc-500 w-4 text-right">{index}</span>
      <span className="text-blue-400">
        STT <span className="text-zinc-300">{formatMs(timing.stt_ms)}</span>
      </span>
      <span className="text-zinc-600">&rarr;</span>
      <span className="text-green-400">
        LLM <span className="text-zinc-300">{formatMs(timing.llm_ttft_ms)}</span>
      </span>
      <span className="text-zinc-600">&rarr;</span>
      <span className="text-purple-400">
        TTS <span className="text-zinc-300">{formatMs(timing.tts_ttfb_ms)}</span>
      </span>
      <span className="text-zinc-600">|</span>
      <span className="text-yellow-400">
        Total <span className="text-zinc-300">{formatMs(timing.total_ms)}</span>
      </span>
    </div>
  );
}

export default function TimingOverlay({ history }: { history: TimingData[] }) {
  if (history.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 w-full max-h-60 overflow-y-auto">
      {history.map((t, i) => (
        <TurnRow key={t.speech_id} timing={t} index={i + 1} />
      ))}
    </div>
  );
}
