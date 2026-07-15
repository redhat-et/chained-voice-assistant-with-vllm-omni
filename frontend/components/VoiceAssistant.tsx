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
  const [activeLlm, setActiveLlm] = useState("");
  const [modelSelection, setModelSelection] = useState<ModelSelection | null>(null);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: AvailableModels & { llm_active?: string }) => {
        setAvailable(data);
        setActiveLlm(data.llm_active ?? data.llm[0] ?? "");
        setModelSelection(defaultSelectionFromAvailable(data));
      })
      .catch(() => {
        setModelSelection(defaultSelectionFromAvailable({ stt: [], llm: [], tts: [] }));
      });
  }, []);

  const handleConnect = useCallback(async () => {
    if (!modelSelection) return;
    setConnecting(true);
    try {
      if (modelSelection.llm_model !== activeLlm) {
        const shortName = modelSelection.llm_model.split("/").pop() ?? modelSelection.llm_model;
        setStatusMsg(`Loading ${shortName}...`);
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
  }, [modelSelection, activeLlm]);

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
