"use client";

export interface TimingData {
  speech_id: string;
  pipeline_mode?: string;
  stt_ms: number;
  stt_audio_duration_ms?: number;
  llm_ttft_ms: number;
  llm_total_ms: number;
  llm_tokens_per_second?: number;
  llm_prompt_tokens?: number;
  llm_completion_tokens?: number;
  tts_ttfb_ms: number;
  tts_total_ms: number;
  tts_audio_duration_ms?: number;
  tts_characters?: number;
  total_ms: number;
}

function formatMs(ms: number): string {
  if (ms < 0) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function MetricLabel({ children }: { children: React.ReactNode }) {
  return <span className="text-zinc-500">{children}:</span>;
}

function TurnRow({ timing, index }: { timing: TimingData; index: number }) {
  const is2Stage = timing.pipeline_mode === "2-stage";
  return (
    <div className="rounded-lg bg-zinc-900/80 px-4 py-2 text-xs font-mono backdrop-blur-sm border border-zinc-800 space-y-1">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-zinc-500 w-4 text-right">{index}</span>
        {!is2Stage && (
          <>
            <span className="text-blue-400">
              STT <span className="text-zinc-300">{formatMs(timing.stt_ms)}</span>
            </span>
            <span className="text-zinc-600">&rarr;</span>
          </>
        )}
        <span className="text-green-400">
          {is2Stage ? "Audio LLM" : "LLM"} <span className="text-zinc-300">{formatMs(timing.llm_ttft_ms)}</span>
          <span className="text-zinc-500">/{formatMs(timing.llm_total_ms)}</span>
        </span>
        <span className="text-zinc-600">&rarr;</span>
        <span className="text-purple-400">
          TTS <span className="text-zinc-300">{formatMs(timing.tts_ttfb_ms)}</span>
          <span className="text-zinc-500">/{formatMs(timing.tts_total_ms)}</span>
        </span>
        <span className="text-zinc-600">|</span>
        <span className="text-yellow-400">
          Total <span className="text-zinc-300">{formatMs(timing.total_ms)}</span>
        </span>
      </div>
      {!is2Stage && (
        <div className="flex flex-wrap items-center gap-3 pl-7 text-blue-400">
          <span className="font-semibold">STT</span>
          <span><MetricLabel>Audio Duration</MetricLabel> {formatMs(timing.stt_audio_duration_ms ?? 0)}</span>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 pl-7 text-green-400">
        <span className="font-semibold">LLM</span>
        <span><MetricLabel>Tokens/s</MetricLabel> {Math.round(timing.llm_tokens_per_second ?? 0)}</span>
        <span><MetricLabel>Prompt Tokens</MetricLabel> {timing.llm_prompt_tokens ?? 0}</span>
        <span><MetricLabel>Completion Tokens</MetricLabel> {timing.llm_completion_tokens ?? 0}</span>
      </div>
      <div className="flex flex-wrap items-center gap-3 pl-7 text-purple-400">
        <span className="font-semibold">TTS</span>
        <span><MetricLabel>Audio Duration</MetricLabel> {formatMs(timing.tts_audio_duration_ms ?? 0)}</span>
        <span><MetricLabel>Characters</MetricLabel> {timing.tts_characters ?? 0}</span>
        {(timing.tts_audio_duration_ms ?? 0) > 0 && (timing.tts_total_ms ?? 0) > 0 && (
          <span><MetricLabel>Realtime Factor</MetricLabel> {((timing.tts_audio_duration_ms!) / timing.tts_total_ms).toFixed(2)}x</span>
        )}
      </div>
    </div>
  );
}

function avg(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function AveragesRow({ history }: { history: TimingData[] }) {
  const is2Stage = history[0]?.pipeline_mode === "2-stage";
  const avgStt = avg(history.map((t) => t.stt_ms));
  const avgLlmTtft = avg(history.map((t) => t.llm_ttft_ms));
  const avgTtsTtfb = avg(history.map((t) => t.tts_ttfb_ms));
  const avgTotal = avg(history.map((t) => t.total_ms));
  const avgTokS = avg(history.filter((t) => (t.llm_tokens_per_second ?? 0) > 0).map((t) => t.llm_tokens_per_second!));
  const rtfValues = history.filter((t) => (t.tts_audio_duration_ms ?? 0) > 0 && (t.tts_total_ms ?? 0) > 0);
  const avgRtf = avg(rtfValues.map((t) => t.tts_audio_duration_ms! / t.tts_total_ms));

  return (
    <div className="rounded-lg bg-zinc-800/80 px-4 py-2 text-xs font-mono backdrop-blur-sm border border-zinc-700 space-y-1">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-zinc-400 font-semibold">AVG</span>
        {!is2Stage && (
          <>
            <span className="text-blue-400">
              STT <span className="text-zinc-300">{formatMs(avgStt)}</span>
            </span>
            <span className="text-zinc-600">&rarr;</span>
          </>
        )}
        <span className="text-green-400">
          {is2Stage ? "Audio LLM" : "LLM"} TTFT <span className="text-zinc-300">{formatMs(avgLlmTtft)}</span>
        </span>
        <span className="text-zinc-600">&rarr;</span>
        <span className="text-purple-400">
          TTS TTFB <span className="text-zinc-300">{formatMs(avgTtsTtfb)}</span>
        </span>
        <span className="text-zinc-600">|</span>
        <span className="text-yellow-400">
          Total <span className="text-zinc-300">{formatMs(avgTotal)}</span>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 pl-12 text-zinc-400">
        {avgTokS > 0 && <span className="text-green-400"><MetricLabel>Tokens/s</MetricLabel> {Math.round(avgTokS)}</span>}
        {avgRtf > 0 && <span className="text-purple-400"><MetricLabel>Realtime Factor</MetricLabel> {avgRtf.toFixed(2)}x</span>}
        <span className="text-zinc-500">{history.length} turn{history.length !== 1 ? "s" : ""}</span>
      </div>
    </div>
  );
}

export default function TimingOverlay({ history }: { history: TimingData[] }) {
  if (history.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 w-full max-h-80 overflow-y-auto">
      {history.map((t, i) => (
        <TurnRow key={t.speech_id} timing={t} index={i + 1} />
      ))}
      {history.length >= 2 && <AveragesRow history={history} />}
    </div>
  );
}
