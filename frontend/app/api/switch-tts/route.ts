import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const managerUrl = process.env.MODEL_MANAGER_URL ?? "http://host.docker.internal:8006";

  const body = await request.json();
  const { model } = body;

  if (!model) {
    return NextResponse.json({ error: "model is required" }, { status: 400 });
  }

  try {
    const res = await fetch(`${managerUrl}/switch-tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
      signal: AbortSignal.timeout(300_000),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { error: "TTS model switch timed out or failed" },
      { status: 504 },
    );
  }
}
