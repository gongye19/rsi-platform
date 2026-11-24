import { test } from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { proxy } from "./proxy";

test("public sharing needs no credentials on any resource but remains read-only", () => {
  const saved = process.env.HARNESS_SHARE_MODE;
  try {
    delete process.env.HARNESS_SHARE_MODE;
    assert.equal(proxy(new NextRequest("http://localhost/")).status, 200);
    process.env.HARNESS_SHARE_MODE = "1";
    for (const path of ["/", "/api/evolution", "/api/experiment", "/_next/static/app.js", "/favicon.ico"]) {
      const response = proxy(new NextRequest(`http://localhost${path}`));
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("WWW-Authenticate"), null);
      assert.equal(response.headers.get("Cache-Control"), "private, no-store");
    }
    for (const method of ["POST", "PUT", "PATCH", "DELETE"])
      assert.equal(proxy(new NextRequest("http://localhost/api/evolution", { method })).status, 405);
    assert.equal(proxy(new NextRequest("http://localhost/", { method: "HEAD" })).status, 200);
  } finally {
    if (saved == null) delete process.env.HARNESS_SHARE_MODE;
    else process.env.HARNESS_SHARE_MODE = saved;
  }
});
