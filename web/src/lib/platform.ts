export async function platform(path: string, init?: RequestInit) {
  const base = process.env.HARNESSLENS_API_URL || "http://127.0.0.1:8765";
  const token = process.env.HAI_SERVICE_TOKEN;
  if (!token) return Response.json({ error: "请配置平台连接与服务令牌" }, { status: 503 });
  try {
    const response = await fetch(base + path, {
      ...init, cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    });
    return new Response(response.body, { status: response.status, headers: {
      "Content-Type": response.headers.get("Content-Type") || "application/json", "Cache-Control": "no-store",
    } });
  } catch {
    return Response.json({ error: "实验管理服务不可用" }, { status: 503 });
  }
}
