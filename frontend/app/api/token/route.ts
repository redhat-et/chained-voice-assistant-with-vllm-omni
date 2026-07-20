import { AccessToken, RoomAgentDispatch, RoomConfiguration } from "livekit-server-sdk";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const serverUrl = process.env.LIVEKIT_URL;

  if (!apiKey || !apiSecret || !serverUrl) {
    return NextResponse.json(
      { error: "LiveKit credentials not configured" },
      { status: 500 }
    );
  }

  let modelMetadata = "{}";
  try {
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.includes("json")) {
      const body = await request.json();
      const { stt_model, llm_model, tts_model, tts_voice } = body;
      if (stt_model || llm_model || tts_model) {
        modelMetadata = JSON.stringify({ stt_model, llm_model, tts_model, tts_voice });
      }
    }
  } catch {
    // No body or invalid JSON — use defaults
  }

  const roomName = `voice-room-${Math.random().toString(36).slice(2, 9)}`;
  const participantName = `user-${Math.random().toString(36).slice(2, 7)}`;

  const at = new AccessToken(apiKey, apiSecret, {
    identity: participantName,
    name: participantName,
  });

  at.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
  });

  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: "voice-assistant", metadata: modelMetadata })],
  });

  const token = await at.toJwt();

  return NextResponse.json({
    serverUrl,
    roomName,
    participantName,
    participantToken: token,
  });
}
