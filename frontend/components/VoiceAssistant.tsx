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
import ModelSelector, { DEFAULT_SELECTION, type ModelSelection } from "./ModelSelector";

interface ConnectionDetails {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
}

function AgentVisualizer() {
  const { state, audioTrack } = useVoiceAssistant();
  const room = useRoomContext();
  const [timing, setTiming] = useState<TimingData | null>(null);

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
          setTiming(data);
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
    <div className="flex flex-col items-center gap-4">
      <div className="h-48 w-full max-w-md">
        <BarVisualizer state={state} barCount={5} trackRef={audioTrack} />
      </div>
      <p className="text-sm text-zinc-400 capitalize">{state}</p>
      {timing && <TimingOverlay timing={timing} />}
    </div>
  );
}

export default function VoiceAssistant() {
  const [connectionDetails, setConnectionDetails] =
    useState<ConnectionDetails | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [modelSelection, setModelSelection] =
    useState<ModelSelection>(DEFAULT_SELECTION);

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    try {
      const response = await fetch("/api/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelSelection),
      });
      if (!response.ok) throw new Error("Failed to get token");
      const details: ConnectionDetails = await response.json();
      setConnectionDetails(details);
    } catch (err) {
      console.error("Connection failed:", err);
      setConnecting(false);
    }
  }, [modelSelection]);

  const handleDisconnected = useCallback(() => {
    setConnectionDetails(null);
    setConnecting(false);
  }, []);

  if (!connectionDetails) {
    return (
      <div className="flex flex-col items-center gap-6 w-full max-w-2xl">
        <ModelSelector
          selection={modelSelection}
          onSelectionChange={setModelSelection}
          disabled={false}
        />
        <button
          onClick={handleConnect}
          disabled={connecting}
          className="rounded-full bg-white px-8 py-4 text-lg font-medium text-black transition-opacity hover:opacity-80 disabled:opacity-50"
        >
          {connecting ? "Connecting..." : "Start Conversation"}
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
