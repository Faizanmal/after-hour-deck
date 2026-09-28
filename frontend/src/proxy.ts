import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const WINDOW_MS = 60_000;
const PER_IP_LIMIT = 1200;
const buckets = new Map<string, { window: number; count: number }>();

function allow(ip: string): boolean {
  const slot = Math.floor(Date.now() / WINDOW_MS);
  const bucket = buckets.get(ip);
  if (!bucket || bucket.window !== slot) {
    buckets.set(ip, { window: slot, count: 1 });
    if (buckets.size > 5000) {
      for (const [key, value] of buckets) {
        if (value.window !== slot) buckets.delete(key);
      }
    }
    return true;
  }
  if (bucket.count >= PER_IP_LIMIT) return false;
  bucket.count += 1;
  return true;
}

function clientIp(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    const parts = forwarded
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    const last = parts[parts.length - 1];
    if (last) return last;
  }
  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

export function proxy(request: NextRequest) {
  const ip = clientIp(request);
  if (!allow(ip)) {
    return new NextResponse("The desk is busy. Wait a moment and try again.", {
      status: 429,
      headers: { "Retry-After": "1" },
    });
  }
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-client-ip", ip);
  return NextResponse.next({
    request: { headers: requestHeaders },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|pcm-processor.js).*)"],
};
