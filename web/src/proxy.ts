import { NextRequest, NextResponse } from "next/server";

const SHARE_HEADERS = {
  "Cache-Control": "private, no-store",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};

/** Public sharing is open to visitors and remains read-only. */
export function proxy(request: NextRequest) {
  if (process.env.HARNESS_SHARE_MODE !== "1") return NextResponse.next();
  if (!["GET", "HEAD"].includes(request.method))
    return new NextResponse("Read-only share.", {
      status: 405,
      headers: { ...SHARE_HEADERS, Allow: "GET, HEAD" },
    });
  const response = NextResponse.next();
  for (const [key, value] of Object.entries(SHARE_HEADERS))
    response.headers.set(key, value);
  return response;
}

export const config = { matcher: "/:path*" };
