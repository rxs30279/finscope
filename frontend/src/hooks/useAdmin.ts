"use client";

import { useEffect, useState } from "react";
import { ADMIN_TOKEN_KEY, getAdminToken } from "@/lib/api";

// Whether this browser has unlocked the admin controls (the expensive refresh
// and AI-summary buttons). Unlock by visiting `/?admin=<token>`; clear it again
// with `/?admin=` or `/?admin=clear`. The token is kept in localStorage and
// sent as X-Admin-Token on the guarded endpoints — see frontend/src/lib/api.ts.
//
// Returns false during SSR and on the first client render, flipping to true
// after mount if a token is present. Buttons gated on this therefore never flash
// for anonymous visitors.
export function useIsAdmin(): boolean {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.has("admin")) {
        const token = params.get("admin") || "";
        if (!token || token === "clear" || token === "off") {
          window.localStorage.removeItem(ADMIN_TOKEN_KEY);
        } else {
          window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
        }
        // Strip ?admin= from the URL so the token isn't left in the address bar
        // or copied into a shared link.
        params.delete("admin");
        const qs = params.toString();
        window.history.replaceState(
          {},
          "",
          window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
        );
      }
    } catch {
      /* localStorage / history unavailable — stay anonymous */
    }
    setIsAdmin(getAdminToken().length > 0);
  }, []);

  return isAdmin;
}
