import { NextRequest } from "next/server";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { platform } from "@/lib/platform";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  const source = request.nextUrl.searchParams.get("source") || "live";
  if (source === "harnesslens" || source === "example") {
    const file = source === "harnesslens" ? "harnesslens-history.example.json" : "component-history.example.json";
    return new Response(await readFile(path.join(process.cwd(), "examples", file)), { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  }
  let id = request.nextUrl.searchParams.get("run");
  if (!id) {
    const response = await platform("/v1/runs");
    if (!response.ok) return response;
    const runs = await response.json();
    id = runs.find((run: {selected_version?: string; state: string}) => run.selected_version || run.state === "running")?.id || runs.find((run: {state: string}) => run.state !== "draft")?.id || runs[0]?.id;
  }
  if (!id) return Response.json({ error: "暂无真实实验，请先在实验管理页创建" }, { status: 404 });
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(id)) return Response.json({ error: "无效实验编号" }, { status: 400 });
  if (request.nextUrl.searchParams.get("version")) return Response.json({ missing: true, text: "完整 trace 与答案请在实验管理页的记录列表中查看。" });
  return platform(`/v1/runs/${id}/history`);
}
