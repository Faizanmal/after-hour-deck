import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: ["127.0.0.1", "localhost", "172.29.160.1"],
  async rewrites() {
    // Production calls Cloud Run directly via NEXT_PUBLIC_API_URL.
    if (process.env.NEXT_PUBLIC_API_URL) return [];
    const api = process.env.API_PROXY_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${api}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
