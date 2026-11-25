import { NextRequest } from "next/server";
import { platform } from "@/lib/platform";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  let id = request.nextUrl.searchParams.get("run");
  if (!id) {
    const response = await platform("/v1/runs");
    if (!response.ok) return response;
    const runs = await response.json();
    id = runs.find((run: {selected_version?: string; state: string}) => run.selected_version || run.state === "running")?.id || runs.find((run: {state: string}) => run.state !== "draft")?.id || runs[0]?.id;
  }
  if (!id) return Response.json({ error: "No experiment is available. Create a run in the console." }, { status: 404 });
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(id)) return Response.json({ error: "Invalid run ID" }, { status: 400 });
  if (request.nextUrl.searchParams.get("version")) return Response.json({ missing: true, text: "Open Artifacts in the experiment console to inspect traces and answers." });
  return platform(`/v1/runs/${id}/history`);
}
