import { describe, it, expect } from "vitest";
import {
  defaultSelectionFromAvailable,
  type AvailableModels,
} from "../components/ModelSelector";

const FULL_AVAILABLE: AvailableModels = {
  stt: ["Systran/faster-whisper-large-v3"],
  llm: ["google/gemma-3-4b-it", "Qwen/Qwen3-0.6B", "mistralai/Mistral-7B-Instruct-v0.3"],
  tts: ["Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "mistralai/Voxtral-4B-TTS-2603"],
};

const EMPTY_AVAILABLE: AvailableModels = { stt: [], llm: [], tts: [] };

describe("defaultSelectionFromAvailable", () => {
  it("uses first available STT", () => {
    const sel = defaultSelectionFromAvailable(FULL_AVAILABLE);
    expect(sel.stt_model).toBe("Systran/faster-whisper-large-v3");
  });

  it("falls back to hardcoded STT when list is empty", () => {
    const sel = defaultSelectionFromAvailable(EMPTY_AVAILABLE);
    expect(sel.stt_model).toBe("Systran/faster-whisper-large-v3");
  });

  it("prefers activeLlm over first in list", () => {
    const sel = defaultSelectionFromAvailable(FULL_AVAILABLE, "Qwen/Qwen3-0.6B");
    expect(sel.llm_model).toBe("Qwen/Qwen3-0.6B");
  });

  it("prefers activeTts over first in list", () => {
    const sel = defaultSelectionFromAvailable(
      FULL_AVAILABLE,
      undefined,
      "mistralai/Voxtral-4B-TTS-2603"
    );
    expect(sel.tts_model).toBe("mistralai/Voxtral-4B-TTS-2603");
  });

  it("maps Qwen TTS to voice vivian", () => {
    const sel = defaultSelectionFromAvailable(
      FULL_AVAILABLE,
      undefined,
      "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    );
    expect(sel.tts_voice).toBe("vivian");
  });

  it("maps Voxtral to voice casual_male", () => {
    const sel = defaultSelectionFromAvailable(
      FULL_AVAILABLE,
      undefined,
      "mistralai/Voxtral-4B-TTS-2603"
    );
    expect(sel.tts_voice).toBe("casual_male");
  });

  it("falls back to vivian for unknown TTS model", () => {
    const available: AvailableModels = {
      stt: [],
      llm: [],
      tts: ["unknown/tts-model"],
    };
    const sel = defaultSelectionFromAvailable(available, undefined, "unknown/tts-model");
    expect(sel.tts_voice).toBe("vivian");
  });

  it("uses all hardcoded defaults when empty and no actives", () => {
    const sel = defaultSelectionFromAvailable(EMPTY_AVAILABLE);
    expect(sel.stt_model).toBe("Systran/faster-whisper-large-v3");
    expect(sel.llm_model).toBe("google/gemma-3-4b-it");
    expect(sel.tts_model).toBe("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice");
    expect(sel.tts_voice).toBe("vivian");
  });
});
