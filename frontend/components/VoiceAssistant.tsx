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
import { useCallback, useEffect, useState } from "react";
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
      setStatusMsg("Requesting model switches...");
      const switchResults = await Promise.all([
        fetch("/api/switch-stt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.stt_model }),
        }),
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
      ]);

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
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 3000));
          const statusRes = await fetch("/api/switch-status");
          if (!statusRes.ok) continue;
          const status = await statusRes.json();

          for (const kind of ["stt", "llm", "tts"] as const) {
            if (status[kind]?.error) {
              throw new Error(
                `${kind.toUpperCase()} switch failed: ${status[kind].error}`,
              );
            }
          }

          const loading: string[] = [];
          if (!status.stt?.ready) loading.push("STT");
          if (!status.llm?.ready) loading.push("LLM");
          if (!status.tts?.ready) loading.push("TTS");

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
    return (
      <div className="flex flex-col items-center gap-6 w-full max-w-2xl">
        <ModelSelector
          selection={modelSelection}
          onSelectionChange={setModelSelection}
          disabled={false}
          available={available}
        />
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
