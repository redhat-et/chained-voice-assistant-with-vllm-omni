import { NextResponse } from "next/server";

export async function GET() {
  const managerUrl =
    process.env.MODEL_MANAGER_URL ?? "http://host.docker.internal:8006";

  try {
    const res = await fetch(`${managerUrl}/all-status`, {
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: "Failed to fetch model status" },
      { status: 502 },
    );
  }
}
