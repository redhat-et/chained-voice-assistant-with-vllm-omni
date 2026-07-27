"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  BarVisualizer,
  DisconnectButton,
  useVoiceAssistant,
  useRoomContext,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { RoomEvent } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";
import TimingOverlay, { type TimingData } from "./TimingOverlay";
import ModelSelector, {
  defaultSelectionFromAvailable,
  type AvailableModels,
  type ModelSelection,
} from "./ModelSelector";

interface ConnectionDetails {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
}

function AgentVisualizer() {
  const { state, audioTrack } = useVoiceAssistant();
  const room = useRoomContext();
  const [history, setHistory] = useState<TimingData[]>([]);

  useEffect(() => {
    const handleData = (
      payload: Uint8Array,
      participant: any,
      kind: any,
      topic?: string
    ) => {
      if (topic === "timing") {
        try {
          const data: TimingData = JSON.parse(
            new TextDecoder().decode(payload)
          );
          setHistory((prev) => {
            const idx = prev.findIndex((t) => t.speech_id === data.speech_id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = { ...updated[idx], ...data };
              return updated;
            }
            return [...prev, data];
          });
        } catch {
          // ignore malformed timing data
        }
      }
    };

    room.on(RoomEvent.DataReceived, handleData);
    return () => {
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room]);

  return (
    <div className="flex flex-col items-center gap-4 w-full">
      <div className="h-48 w-full max-w-md">
        <BarVisualizer state={state} barCount={5} trackRef={audioTrack} />
      </div>
      <p className="text-sm text-zinc-400 capitalize">{state}</p>
      <TimingOverlay history={history} />
    </div>
  );
}

export default function VoiceAssistant() {
  const [connectionDetails, setConnectionDetails] =
    useState<ConnectionDetails | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [available, setAvailable] = useState<AvailableModels | null>(null);
  const [modelSelection, setModelSelection] = useState<ModelSelection | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ text: string; audio: string | null } | null>(null);
  const [uploadError, setUploadError] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: AvailableModels & { stt_active?: string; llm_active?: string; tts_active?: string }) => {
        setAvailable(data);
        const sttActive = data.stt_active ?? data.stt[0] ?? "";
        const llmActive = data.llm_active ?? data.llm[0] ?? "";
        const ttsActive = data.tts_active ?? data.tts[0] ?? "";
        setModelSelection(defaultSelectionFromAvailable(data, llmActive, ttsActive, sttActive));
      })
      .catch(() => {
        setModelSelection(defaultSelectionFromAvailable({ stt: [], llm: [], tts: [] }));
      });
  }, []);

  const handleConnect = useCallback(async () => {
    if (!modelSelection) return;
    setConnecting(true);
    try {
      const is2Stage = modelSelection.pipeline_mode === "2-stage";
      setStatusMsg("Requesting model switches...");

      const switchCalls = [
        fetch("/api/switch-llm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.llm_model }),
        }),
        fetch("/api/switch-tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.tts_model }),
        }),
      ];
      if (!is2Stage) {
        switchCalls.unshift(
          fetch("/api/switch-stt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: modelSelection.stt_model }),
          }),
        );
      }
      const switchResults = await Promise.all(switchCalls);

      for (const res of switchResults) {
        if (!res.ok && res.status !== 202) {
          const err = await res.json();
          throw new Error(err.error || "Failed to switch model");
        }
      }

      const hadRealSwitch = switchResults.some((r) => r.status === 202);
      const allReady = switchResults.every((r) => r.status === 200);
      if (!allReady) {
        setStatusMsg("Loading models...");
        const deadline = Date.now() + 300_000;
        const stagesToCheck = is2Stage ? (["llm", "tts"] as const) : (["stt", "llm", "tts"] as const);
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 3000));
          const statusRes = await fetch("/api/switch-status");
          if (!statusRes.ok) continue;
          const status = await statusRes.json();

          for (const kind of stagesToCheck) {
            if (status[kind]?.error) {
              throw new Error(
                `${kind.toUpperCase()} switch failed: ${status[kind].error}`,
              );
            }
          }

          const loading: string[] = [];
          for (const kind of stagesToCheck) {
            if (!status[kind]?.ready) loading.push(kind.toUpperCase());
          }

          if (loading.length === 0) break;
          setStatusMsg(`Loading ${loading.join(", ")}...`);
        }
      }

      if (hadRealSwitch) {
        sessionStorage.setItem("autoconnect", "true");
        window.location.reload();
        return;
      }

      setStatusMsg("Connecting...");
      const response = await fetch("/api/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelSelection),
      });
      if (!response.ok) throw new Error("Failed to get token");
      const details: ConnectionDetails = await response.json();
      setConnectionDetails(details);
      setStatusMsg("");
    } catch (err) {
      console.error("Connection failed:", err);
      setConnecting(false);
      setStatusMsg("");
    }
  }, [modelSelection]);

  useEffect(() => {
    if (modelSelection && sessionStorage.getItem("autoconnect")) {
      sessionStorage.removeItem("autoconnect");
      handleConnect();
    }
  }, [modelSelection, handleConnect]);

  const handleFileUpload = useCallback(async (file: File) => {
    if (!modelSelection) return;
    setUploadBusy(true);
    setUploadError("");
    setUploadResult(null);
    try {
      const form = new FormData();
      form.append("audio", file);
      form.append("llm_model", modelSelection.llm_model);
      form.append("tts_model", modelSelection.tts_model);
      form.append("tts_voice", modelSelection.tts_voice);

      const res = await fetch("/api/audio-query", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setUploadError(data.error || "Request failed");
        return;
      }
      setUploadResult({ text: data.text, audio: data.audio });
      if (data.audio && audioRef.current) {
        audioRef.current.src = `data:audio/mp3;base64,${data.audio}`;
        audioRef.current.play().catch(() => {});
      }
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploadBusy(false);
    }
  }, [modelSelection]);

  const handleDisconnected = useCallback(() => {
    setConnectionDetails(null);
    setConnecting(false);
  }, []);

  if (!modelSelection) {
    return (
      <div className="flex flex-col items-center gap-6 w-full max-w-2xl">
        <p className="text-sm text-zinc-400">Loading available models...</p>
      </div>
    );
  }

  if (!connectionDetails) {
    const is2Stage = modelSelection.pipeline_mode === "2-stage";
    return (
      <div className="flex flex-col items-center gap-6 w-full max-w-2xl">
        <ModelSelector
          selection={modelSelection}
          onSelectionChange={setModelSelection}
          disabled={false}
          available={available}
        />
        {is2Stage && (
          <div className="flex flex-col gap-4 w-full">
            <label
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("border-purple-500"); }}
              onDragLeave={(e) => { e.currentTarget.classList.remove("border-purple-500"); }}
              onDrop={(e) => {
                e.preventDefault();
                e.currentTarget.classList.remove("border-purple-500");
                const file = e.dataTransfer.files[0];
                if (file) handleFileUpload(file);
              }}
              className="flex flex-col items-center gap-2 rounded-xl border-2 border-dashed border-zinc-700 bg-zinc-900/60 p-8 cursor-pointer transition-colors hover:border-zinc-500"
            >
              <input
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file);
                  e.target.value = "";
                }}
              />
              <span className="text-2xl">🎵</span>
              <span className="text-sm text-zinc-400">
                {uploadBusy ? "Processing..." : "Drop an audio file here or click to upload"}
              </span>
            </label>
            {uploadError && (
              <p className="text-sm text-red-400 text-center">{uploadError}</p>
            )}
            {uploadResult && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 space-y-3">
                <p className="text-sm text-zinc-200">{uploadResult.text}</p>
                <audio ref={audioRef} controls className="w-full" />
              </div>
            )}
          </div>
        )}
        <button
          onClick={handleConnect}
          disabled={connecting}
          className="rounded-full bg-white px-8 py-4 text-lg font-medium text-black transition-opacity hover:opacity-80 disabled:opacity-50"
        >
          {connecting ? (statusMsg || "Connecting...") : "Start Conversation"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-2xl">
      <ModelSelector
        selection={modelSelection}
        onSelectionChange={setModelSelection}
        disabled={true}
        available={available}
      />
      <LiveKitRoom
        token={connectionDetails.participantToken}
        serverUrl={connectionDetails.serverUrl}
        connect={true}
        audio={true}
        onDisconnected={handleDisconnected}
        className="flex flex-col items-center gap-8"
      >
        <AgentVisualizer />
        <RoomAudioRenderer />
        <DisconnectButton className="rounded-full border border-zinc-700 px-6 py-3 text-sm text-zinc-300 transition-colors hover:border-red-500 hover:text-red-400">
          End Conversation
        </DisconnectButton>
      </LiveKitRoom>
    </div>
  );
}
