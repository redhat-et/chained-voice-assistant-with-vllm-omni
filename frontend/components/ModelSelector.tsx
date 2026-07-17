"use client";

interface ModelOption {
  id: string;
  name: string;
  provenance: string;
  flag: string;
  voice?: string;
}

export interface ModelSelection {
  stt_model: string;
  llm_model: string;
  tts_model: string;
  tts_voice: string;
}

export interface AvailableModels {
  stt: string[];
  llm: string[];
  tts: string[];
}

const MODEL_CATALOG: Record<string, Omit<ModelOption, "id">> = {
  "Systran/faster-whisper-large-v3": { name: "Whisper Large v3", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  "Systran/faster-whisper-base": { name: "Whisper Base", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  "google/gemma-3-4b-it": { name: "Gemma 3 4B", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  "RedHatAI/gemma-3-4b-it-quantized.w4a16": { name: "Gemma 3 4B (INT4)", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  "Qwen/Qwen3-0.6B": { name: "Qwen3 0.6B", provenance: "China", flag: "\u{1F1E8}\u{1F1F3}" },
  "meta-llama/Llama-3.1-8B-Instruct": { name: "Llama 3.1 8B", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  "mistralai/Mistral-7B-Instruct-v0.3": { name: "Mistral 7B", provenance: "EU", flag: "\u{1F1EA}\u{1F1FA}" },
  "Qwen/Qwen3-ASR-0.6B": { name: "Qwen3 ASR 0.6B", provenance: "China", flag: "\u{1F1E8}\u{1F1F3}" },
  "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice": { name: "Qwen3 TTS 1.7B", provenance: "China", flag: "\u{1F1E8}\u{1F1F3}", voice: "vivian" },
  "mistralai/Voxtral-4B-TTS-2603": { name: "Voxtral 4B", provenance: "EU", flag: "\u{1F1EA}\u{1F1FA}", voice: "casual_male" },
};

function modelOptionFromId(id: string): ModelOption {
  const catalog = MODEL_CATALOG[id];
  if (catalog) return { id, ...catalog };
  const shortName = id.split("/").pop() ?? id;
  return { id, name: shortName, provenance: "", flag: "\u{1F4E6}" };
}

function buildModelList(availableIds: string[]): ModelOption[] {
  const catalogIds = new Set(Object.keys(MODEL_CATALOG));
  const inCatalog = availableIds.filter((id) => catalogIds.has(id));
  const notInCatalog = availableIds.filter((id) => !catalogIds.has(id));
  // When the backend lists many models (e.g. STT lists all it CAN load),
  // show only catalog matches + any loaded-but-uncataloged. When it lists
  // few (LLM/TTS return only loaded models), show everything.
  const toShow = availableIds.length > 20 ? inCatalog : [...inCatalog, ...notInCatalog];
  return toShow.map(modelOptionFromId);
}

export function defaultSelectionFromAvailable(available: AvailableModels, activeLlm?: string, activeTts?: string, activeStt?: string): ModelSelection {
  const sttModel = activeStt || available.stt[0] || "Systran/faster-whisper-large-v3";
  const llmModel = activeLlm || available.llm[0] || "google/gemma-3-4b-it";
  const ttsId = activeTts || available.tts[0] || "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice";
  const ttsEntry = MODEL_CATALOG[ttsId];
  return {
    stt_model: sttModel,
    llm_model: llmModel,
    tts_model: ttsId,
    tts_voice: ttsEntry?.voice ?? "vivian",
  };
}

function StageSelector({
  label,
  icon,
  models,
  value,
  onChange,
  disabled,
}: {
  label: string;
  icon: string;
  models: ModelOption[];
  value: string;
  onChange: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
        {icon} {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="rounded-lg border border-zinc-700 bg-zinc-800/80 px-3 py-2 text-sm text-zinc-200 backdrop-blur-sm transition-colors hover:border-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.flag} {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export default function ModelSelector({
  selection,
  onSelectionChange,
  disabled,
  available,
}: {
  selection: ModelSelection;
  onSelectionChange: (sel: ModelSelection) => void;
  disabled: boolean;
  available: AvailableModels | null;
}) {
  const sttModels = available?.stt.length ? buildModelList(available.stt) : [modelOptionFromId(selection.stt_model)];
  const llmModels = available?.llm.length ? buildModelList(available.llm) : [modelOptionFromId(selection.llm_model)];
  const ttsModels = available?.tts.length ? buildModelList(available.tts) : [modelOptionFromId(selection.tts_model)];

  const handleSttChange = (id: string) => {
    onSelectionChange({ ...selection, stt_model: id });
  };

  const handleLlmChange = (id: string) => {
    onSelectionChange({ ...selection, llm_model: id });
  };

  const handleTtsChange = (id: string) => {
    const entry = MODEL_CATALOG[id];
    onSelectionChange({
      ...selection,
      tts_model: id,
      tts_voice: entry?.voice ?? selection.tts_voice,
    });
  };

  return (
    <div className="grid grid-cols-1 gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm sm:grid-cols-3">
      <StageSelector
        label="Speech-to-Text"
        icon="🎤"
        models={sttModels}
        value={selection.stt_model}
        onChange={handleSttChange}
        disabled={disabled}
      />
      <StageSelector
        label="Language Model"
        icon="🧠"
        models={llmModels}
        value={selection.llm_model}
        onChange={handleLlmChange}
        disabled={disabled}
      />
      <StageSelector
        label="Text-to-Speech"
        icon="🔊"
        models={ttsModels}
        value={selection.tts_model}
        onChange={handleTtsChange}
        disabled={disabled}
      />
    </div>
  );
}
