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
          setHistory((prev) => [...prev, data]);
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
  const [activeStt, setActiveStt] = useState("");
  const [activeLlm, setActiveLlm] = useState("");
  const [activeTts, setActiveTts] = useState("");
  const [modelSelection, setModelSelection] = useState<ModelSelection | null>(null);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: AvailableModels & { stt_active?: string; llm_active?: string; tts_active?: string }) => {
        setAvailable(data);
        const sttActive = data.stt_active ?? data.stt[0] ?? "";
        const llmActive = data.llm_active ?? data.llm[0] ?? "";
        const ttsActive = data.tts_active ?? data.tts[0] ?? "";
        setActiveStt(sttActive);
        setActiveLlm(llmActive);
        setActiveTts(ttsActive);
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
      if (modelSelection.stt_model !== activeStt) {
        const shortName = modelSelection.stt_model.split("/").pop() ?? modelSelection.stt_model;
        setStatusMsg(`Loading STT ${shortName}...`);
        const switchRes = await fetch("/api/switch-stt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.stt_model }),
        });
        if (!switchRes.ok) {
          const err = await switchRes.json();
          throw new Error(err.error || "Failed to switch STT model");
        }
        setActiveStt(modelSelection.stt_model);
      }

      if (modelSelection.tts_model !== activeTts) {
        const shortName = modelSelection.tts_model.split("/").pop() ?? modelSelection.tts_model;
        setStatusMsg(`Loading TTS ${shortName}...`);
        const switchRes = await fetch("/api/switch-tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.tts_model }),
        });
        if (!switchRes.ok) {
          const err = await switchRes.json();
          throw new Error(err.error || "Failed to switch TTS model");
        }
        setActiveTts(modelSelection.tts_model);
      }

      if (modelSelection.llm_model !== activeLlm) {
        const shortName = modelSelection.llm_model.split("/").pop() ?? modelSelection.llm_model;
        setStatusMsg(`Loading LLM ${shortName}...`);
        const switchRes = await fetch("/api/switch-llm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: modelSelection.llm_model }),
        });
        if (!switchRes.ok) {
          const err = await switchRes.json();
          throw new Error(err.error || "Failed to switch LLM model");
        }
        setActiveLlm(modelSelection.llm_model);
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
  }, [modelSelection, activeStt, activeLlm, activeTts]);

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
