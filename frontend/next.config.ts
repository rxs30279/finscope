import type { NextConfig } from "next";
import path from "path";

const BACKEND_URL =
  process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  // Pin the tracing root to this directory so Next.js doesn't walk up to C:\Users\richa
  // and pick up an unrelated lockfile.
  outputFileTracingRoot: path.resolve(__dirname),
  // In production on Vercel the Python function handles /api/* directly via
  // vercel.json routing — no rewrite needed. In development, proxy to the
  // local FastAPI server.
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
