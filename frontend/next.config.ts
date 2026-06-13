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
  // The company page is dynamically rendered (it awaits searchParams), so by
  // default every request — including each distinct ?symbol= URL and every
  // search-engine recrawl — invokes the function and re-runs SSR. The upstream
  // data is already cached (getCompanyData uses next.revalidate=3600), but the
  // render still costs CPU on each hit. These headers let Vercel's Edge Network
  // cache the rendered HTML per-URL: repeat hits within s-maxage are served from
  // the CDN with no function invocation; stale-while-revalidate refreshes it in
  // the background after that. The page carries no personalised state (the live
  // dashboard hydrates client-side), so a shared edge cache is safe.
  async headers() {
    return [
      {
        source: "/company",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=3600, stale-while-revalidate=86400",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
