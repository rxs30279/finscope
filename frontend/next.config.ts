import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the tracing root to this directory so Next.js doesn't walk up to C:\Users\richa
  // and pick up an unrelated lockfile.
  outputFileTracingRoot: path.resolve(__dirname),
  // The Python API is a separate Vercel project (finscope-api). The browser always
  // calls same-origin /api and /sitemap.xml; these rewrites proxy them server-side
  // to that backend, so there's no CORS and the X-Admin-Token header / POST bodies
  // pass straight through. In production the backend origin comes from BACKEND_ORIGIN
  // (set on the frontend Vercel project); in dev it's the local FastAPI server.
  async rewrites() {
    const backend =
      process.env.NODE_ENV === "production"
        ? process.env.BACKEND_ORIGIN
        : process.env.BACKEND_URL || "http://localhost:8000";
    if (!backend) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
      {
        source: "/sitemap.xml",
        destination: `${backend}/sitemap.xml`,
      },
    ];
  },
};

export default nextConfig;
