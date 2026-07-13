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

const STT_MODELS: ModelOption[] = [
  { id: "Systran/faster-whisper-large-v3", name: "Whisper Large v3", provenance: "France", flag: "\u{1F1EB}\u{1F1F7}" },
  { id: "Systran/faster-whisper-base", name: "Whisper Base", provenance: "France", flag: "\u{1F1EB}\u{1F1F7}" },
];

const LLM_MODELS: ModelOption[] = [
  { id: "google/gemma-3-4b-it", name: "Gemma 3 4B", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  { id: "Qwen/Qwen3-0.6B", name: "Qwen3 0.6B", provenance: "China", flag: "\u{1F1E8}\u{1F1F3}" },
  { id: "meta-llama/Llama-3.1-8B-Instruct", name: "Llama 3.1 8B", provenance: "US", flag: "\u{1F1FA}\u{1F1F8}" },
  { id: "mistralai/Mistral-7B-Instruct-v0.3", name: "Mistral 7B", provenance: "EU", flag: "\u{1F1EA}\u{1F1FA}" },
];

const TTS_MODELS: ModelOption[] = [
  { id: "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", name: "Qwen3 TTS 1.7B", provenance: "China", flag: "\u{1F1E8}\u{1F1F3}", voice: "vivian" },
  { id: "mistralai/Voxtral-4B-TTS-2603", name: "Voxtral 4B", provenance: "EU", flag: "\u{1F1EA}\u{1F1FA}", voice: "casual_male" },
];

export const DEFAULT_SELECTION: ModelSelection = {
  stt_model: STT_MODELS[0].id,
  llm_model: LLM_MODELS[0].id,
  tts_model: TTS_MODELS[0].id,
  tts_voice: TTS_MODELS[0].voice!,
};

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
}: {
  selection: ModelSelection;
  onSelectionChange: (sel: ModelSelection) => void;
  disabled: boolean;
}) {
  const handleSttChange = (id: string) => {
    onSelectionChange({ ...selection, stt_model: id });
  };

  const handleLlmChange = (id: string) => {
    onSelectionChange({ ...selection, llm_model: id });
  };

  const handleTtsChange = (id: string) => {
    const model = TTS_MODELS.find((m) => m.id === id);
    onSelectionChange({
      ...selection,
      tts_model: id,
      tts_voice: model?.voice ?? selection.tts_voice,
    });
  };

  return (
    <div className="grid grid-cols-1 gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm sm:grid-cols-3">
      <StageSelector
        label="Speech-to-Text"
        icon="🎤"
        models={STT_MODELS}
        value={selection.stt_model}
        onChange={handleSttChange}
        disabled={disabled}
      />
      <StageSelector
        label="Language Model"
        icon="🧠"
        models={LLM_MODELS}
        value={selection.llm_model}
        onChange={handleLlmChange}
        disabled={disabled}
      />
      <StageSelector
        label="Text-to-Speech"
        icon="🔊"
        models={TTS_MODELS}
        value={selection.tts_model}
        onChange={handleTtsChange}
        disabled={disabled}
      />
    </div>
  );
}
