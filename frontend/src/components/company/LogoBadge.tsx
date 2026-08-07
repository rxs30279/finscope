"use client";

import { useState } from "react";

// logo.dev's ticker index maps a few LSE tickers to the wrong brand — e.g. RR.L
// (Rolls-Royce Holdings plc, aerospace/defence) resolves to the "Rolls-Royce
// Motor Cars Limited" wordmark, a separate BMW-owned company. For those we pull
// by the correct company domain, which logo.dev serves accurately.
const LOGO_DOMAIN_OVERRIDES: Record<string, string> = {
  "RR.L": "rollsroyce.com", // interlocked RR monogram, not Motor Cars Ltd
};

// Company logo badge. Pulls the logo from logo.dev keyed by ticker (LSE tickers
// keep the ".L" suffix, which is exactly the format logo.dev expects), unless
// the ticker is in LOGO_DOMAIN_OVERRIDES, in which case we key by domain. We
// pass fallback=404 so a miss fires the img onError and we drop back to the
// original purple ticker-initials badge. Needs NEXT_PUBLIC_LOGODEV_TOKEN (a
// publishable pk_ key); with no token set we skip the fetch and show initials.
//
// This is a client component (it needs the img onError fallback), but its initial
// HTML — including the <img> or initials — is still server-rendered, so crawlers
// see the badge. Extracted from CompanyDetail so the server-rendered header can
// use it too.
export default function LogoBadge({
  symbol,
  size = 64,
  // logo.dev sometimes serves a wide wordmark rather than a square icon, and at
  // the small tile size the results calendar uses, "cover" crops the ends off it
  // ("...erizo..."). Callers that want the original edge-to-edge avatar keep the
  // default.
  fit = "cover",
  background = "transparent",
}: {
  symbol: string;
  size?: number;
  fit?: "cover" | "contain";
  background?: string;
}) {
  const [failed, setFailed] = useState(false);
  const label = symbol.replace(".L", "").slice(0, 4);
  const token = process.env.NEXT_PUBLIC_LOGODEV_TOKEN;
  const override = LOGO_DOMAIN_OVERRIDES[symbol];
  const logoPath = override
    ? encodeURIComponent(override)
    : `ticker/${encodeURIComponent(symbol)}`;
  const logoUrl = token
    ? `https://img.logo.dev/${logoPath}?token=${token}&size=120&format=png&retina=true&fallback=404`
    : null;
  const showLogo = !!logoUrl && !failed;

  const base = {
    width: size, height: size, borderRadius: 12, flexShrink: 0,
    display: "flex", alignItems: "center", justifyContent: "center",
    overflow: "hidden", textDecoration: "none",
  } as const;
  const wrapStyle = showLogo
    ? { ...base, background }
    : { ...base, background: "#6366f1", color: "#fff", fontFamily: "DM Serif Display,serif", fontSize: Math.max(11, size * 0.2), fontWeight: 700 };

  const inner = showLogo ? (
    <img
      src={logoUrl as string}
      alt={label}
      onError={() => setFailed(true)}
      style={{ width: "100%", height: "100%", objectFit: fit }}
    />
  ) : (
    label
  );

  return <div style={wrapStyle as React.CSSProperties}>{inner}</div>;
}
