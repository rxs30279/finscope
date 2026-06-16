// Always use /api — Next.js rewrites handle the proxy in dev;
// in production Vercel routes /api/* to the Python function directly.
export const API = "/api";

// Admin gate — see frontend/src/hooks/useAdmin.ts.
// The expensive refresh / AI-summary controls are admin-only. Rather than
// baking a token into the public bundle (where any visitor could read it out
// and replay the guarded endpoints), the token lives per-browser in
// localStorage and is only set by visiting `/?admin=<token>`. A normal visitor
// has no token, so those controls are hidden and their endpoints stay out of
// reach.
export const ADMIN_TOKEN_KEY = "ama_admin_token";

// The admin token this browser has stored (empty string if none).
export function getAdminToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

// Headers for the guarded POST endpoints (backend/admin_auth.py). Call this at
// request time so it always reflects the currently stored token.
export function adminHeaders(): Record<string, string> {
  return { "X-Admin-Token": getAdminToken() };
}
