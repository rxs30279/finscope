// Always use /api — Next.js rewrites handle the proxy in dev;
// in production Vercel routes /api/* to the Python function directly.
export const API = "/api";

// Sent on the guarded refresh/summary POST endpoints (backend/admin_auth.py).
// Baked in at build time, so it's recoverable from the bundle — it gates
// drive-by cost abuse, not determined attackers.
export const ADMIN_HEADERS: Record<string, string> = {
  "X-Admin-Token": process.env.NEXT_PUBLIC_ADMIN_TOKEN || "",
};
