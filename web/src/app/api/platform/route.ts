import { NextRequest } from "next/server";
import { platform } from "@/lib/platform";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams;
  const id = query.get("run");
  if (id && !/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(id)) return Response.json({ error: "Invalid run ID" }, { status: 400 });
  if (query.get("options") === "1") return platform("/v1/options");
  if (query.get("profiles") === "1") return platform("/v1/profiles" + (query.get("name") ? "?" + new URLSearchParams({ name: query.get("name")! }) : ""));
  if (id && query.get("events") === "1") return platform(`/v1/runs/${id}/events?after=${Number(query.get("after") || 0)}`);
  if (id && query.has("path")) return platform(`/v1/runs/${id}/artifact?${new URLSearchParams({root: query.get("root") || "0", path: query.get("path") || ""})}`);
  if (id && query.get("artifacts") === "1") return platform(`/v1/runs/${id}/artifacts`);
  return platform(id ? `/v1/runs/${id}` : "/v1/runs");
}
export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  try {
    if (!origin || new URL(origin).host !== request.headers.get("host")) return Response.json({ error: "Invalid origin" }, { status: 403 });
  } catch { return Response.json({ error: "Invalid origin" }, { status: 403 }); }
  let body;
  try { body = await request.json(); } catch { return Response.json({ error: "Invalid request" }, { status: 400 }); }
  if (!body || typeof body !== "object") return Response.json({ error: "Invalid request" }, { status: 400 });
  const action = body.action;
  if (action === "create") return platform("/v1/runs", { method: "POST", body: JSON.stringify({ profile: body.profile, run_id: body.run_id || undefined, settings: body.settings }) });
  if (!["start", "stop", "resume", "delete", "restore"].includes(action) || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(body.run_id || "")) return Response.json({ error: "Invalid action" }, { status: 400 });
  return platform(`/v1/runs/${body.run_id}/${action}`, { method: "POST", body: "{}" });
}
