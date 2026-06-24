"use client";

import { useState, useCallback, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useIsMobile, useIsNarrowDesktop } from "@/hooks/useMediaQuery";
import { useIsAdmin } from "@/hooks/useAdmin";
import { useRefresh } from "@/app/providers";
import { API, adminHeaders } from "@/lib/api";
import { S } from "@/lib/theme";
import Sidebar from "@/components/Sidebar";

const NAV_GROUPS = [
  { href: "/screener", label: "Screener" },
  { href: "/trending", label: "Trending" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/analysts", label: "Analysts" },
  { href: "/rns", label: "RNS News" },
  { href: "/subscribe", label: "RNS Email" },
  { href: "/markets", label: "Markets" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isMobile = useIsMobile();
  const isNarrow = useIsNarrowDesktop();
  const isAdmin = useIsAdmin();
  const { refreshKey, refresh, setHighlightSymbol, screenMatches } = useRefresh();

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(isNarrow);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [priceToast, setPriceToast] = useState<{ ok: boolean; msg: string } | null>(null);

  const isCompanyPage = pathname.startsWith("/company");
  const showSidebar = !isCompanyPage;

  const doSearch = useCallback((q: string) => {
    setSearchQ(q);
    if (q.length < 1) { setSearchResults([]); return; }
    fetch(`${API}/search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then(setSearchResults)
      .catch(() => {});
  }, []);

  const handleRefresh = () => {
    refresh();
    setLastUpdated(
      new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
    );
  };

  const handlePriceRefresh = async () => {
    setPriceRefreshing(true);
    setPriceToast(null);
    try {
      const res = await fetch(`${API}/prices/refresh`, { method: "POST", headers: adminHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPriceToast({ ok: true, msg: `+${data.rows_added} rows (${data.duration_seconds}s)` });
    } catch {
      setPriceToast({ ok: false, msg: "Price refresh failed" });
    } finally {
      setPriceRefreshing(false);
      setTimeout(() => setPriceToast(null), 4000);
    }
  };

  const onNavigate = useCallback(
    (page: string) => {
      setMobileMenuOpen(false);
      router.push(`/${page}`);
    },
    [router],
  );

  const highlightInScreener = useCallback(
    (sym: string) => {
      setHighlightSymbol(sym);
      setShowSearch(false);
      setSearchQ("");
      setSearchResults([]);
      router.push("/screener");
    },
    [router, setHighlightSymbol],
  );

  // The marketing landing at "/" is a full-bleed page with its own nav and
  // footer — it opts out of the app chrome (top nav, sidebar, search).
  if (pathname === "/") return <>{children}</>;

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0a", fontFamily: "monospace" }}>
      {/* Nav */}
      <nav
        style={{
          background: "#0a0a0a",
          borderBottom: "1px solid #2a2a2a",
          padding: isMobile ? "0 12px" : "0 32px",
          display: "flex",
          alignItems: "center",
          height: 52,
          position: "sticky",
          top: 0,
          zIndex: 100,
        }}
      >
        {/* Hamburger (mobile) / Sidebar toggle (desktop) */}
        {isMobile ? (
          <button
            onClick={() => setMobileMenuOpen((v) => !v)}
            title="Menu"
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "4px 8px", marginRight: 8,
              display: "flex", alignItems: "center", color: "#f1f5f9",
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        ) : (
          <button
            onClick={() => setSidebarCollapsed((v) => !v)}
            title="Toggle sidebar"
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "4px 8px 4px 0", marginRight: 8, marginLeft: -20,
              display: "flex", alignItems: "center",
              opacity: sidebarCollapsed ? 0.35 : 0.75, transition: "opacity 0.2s",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="2" y="2" width="20" height="20" rx="3" stroke="#f1f5f9" strokeWidth="1.5" />
              <line x1="8" y1="2" x2="8" y2="22" stroke="#f1f5f9" strokeWidth="1.5" />
              <line x1="11" y1="7" x2="19" y2="7" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="11" y1="12" x2="19" y2="12" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="11" y1="17" x2="16" y2="17" stroke="#f1f5f9" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        )}

        {/* Logo */}
        <Link
          href="/"
          style={{
            fontFamily: "var(--font-inter), sans-serif",
            fontSize: isMobile ? 10 : 12,
            fontWeight: 700,
            color: "#f97316",
            letterSpacing: 2,
            textTransform: "uppercase",
            marginRight: isMobile ? 8 : isNarrow ? 12 : 32,
            cursor: "pointer",
            padding: "4px 10px",
            borderRadius: 4,
            background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
            boxShadow: "0 0 12px rgba(249, 115, 22, 0.15)",
            whiteSpace: "nowrap",
            textDecoration: "none",
          }}
        >
          {isMobile ? "AMA" : "Alpha Move AI"}
        </Link>

        {/* Desktop nav links */}
        {!isMobile && (
          <div
            className="no-scrollbar"
            style={{ display: "flex", gap: 2, flexShrink: 1, minWidth: 0, overflowX: "auto" }}
          >
            {NAV_GROUPS.map((g) => {
              const isActive = pathname === g.href || (g.href !== "/screener" && pathname.startsWith(g.href));
              return (
                <Link
                  key={g.href}
                  href={g.href}
                  style={{
                    ...S.navBtn,
                    ...(isNarrow ? { padding: "6px 8px", fontSize: 11 } : {}),
                    flexShrink: 0,
                    whiteSpace: "nowrap",
                    textDecoration: "none",
                    ...(isActive ? S.navBtnActive : {}),
                  }}
                >
                  {g.label}
                </Link>
              );
            })}
          </div>
        )}

        {/* Right side */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: isMobile ? 6 : isNarrow ? 8 : 12, minWidth: 0, flexShrink: 0 }}>
          {/* Tools dropdown (desktop only) */}
          {!isMobile && (
            <div style={{ position: "relative", flexShrink: 0 }}>
              <button
                onClick={() => setToolsOpen((v) => !v)}
                title="Tools & refresh"
                style={{
                  background: "#1a1a1a",
                  color: priceRefreshing ? "#f97316" : "#999",
                  border: "1px solid #2a2a2a",
                  padding: "4px 10px",
                  borderRadius: 2,
                  fontFamily: "monospace",
                  fontSize: 10,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span className={priceRefreshing ? "spinning" : ""}>⚙</span>
                Tools ▾
              </button>
              {toolsOpen && (
                <>
                  <div onClick={() => setToolsOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 200 }} />
                  <div style={{
                    position: "absolute", top: "100%", right: 0, marginTop: 6,
                    minWidth: 200, background: "#141414", border: "1px solid #2a2a2a",
                    borderRadius: 4, boxShadow: "0 8px 24px rgba(0,0,0,0.8)",
                    zIndex: 201, overflow: "hidden",
                  }}>
                    <a
                      href={`${API}/help-doc`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={() => setToolsOpen(false)}
                      style={{ display: "block", padding: "10px 14px", color: "#e5e5e5", fontFamily: "monospace", fontSize: 11, textDecoration: "none", borderBottom: "1px solid #1f1f1f" }}
                    >
                      📖 Tool Manual Download
                    </a>
                    {isAdmin && (
                      <button
                        onClick={() => { handleRefresh(); setToolsOpen(false); }}
                        style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", borderBottom: "1px solid #1f1f1f", padding: "10px 14px", color: "#999", fontFamily: "monospace", fontSize: 11, cursor: "pointer" }}
                      >
                        ↻ Refresh Market
                      </button>
                    )}
                    {isAdmin && (
                      <button
                        onClick={handlePriceRefresh}
                        disabled={priceRefreshing}
                        style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", padding: "10px 14px", color: priceRefreshing ? "#f97316" : "#999", fontFamily: "monospace", fontSize: 11, cursor: priceRefreshing ? "not-allowed" : "pointer" }}
                      >
                        <span className={priceRefreshing ? "spinning" : ""}>↻</span>
                        {priceRefreshing ? " Refreshing prices…" : " Refresh Prices"}
                      </button>
                    )}
                    {isAdmin && (lastUpdated || priceToast) && (
                      <div style={{ padding: "8px 14px", borderTop: "1px solid #1f1f1f", background: "#0f0f0f", fontFamily: "monospace", fontSize: 9, lineHeight: 1.5 }}>
                        {lastUpdated && <div style={{ color: "#555" }}>Updated {lastUpdated}</div>}
                        {priceToast && <div style={{ color: priceToast.ok ? "#10b981" : "#ef4444" }}>{priceToast.msg}</div>}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Search */}
          <div style={{ position: "relative", minWidth: 0 }}>
            <input
              placeholder={isMobile || isNarrow ? "Search…" : "Search ticker or company…"}
              value={searchQ}
              onChange={(e) => { doSearch(e.target.value); setShowSearch(true); }}
              onFocus={() => setShowSearch(true)}
              onBlur={() => setTimeout(() => setShowSearch(false), 200)}
              style={{ ...S.searchInput, width: isMobile ? 120 : isNarrow ? 160 : 260, maxWidth: "100%", fontSize: isMobile ? 11 : 13 }}
            />
            {showSearch && searchResults.length > 0 && (
              <div style={{ ...S.dropdown, width: isMobile ? 280 : 420, right: isMobile ? -60 : 0 }}>
                {searchResults.map((r: any) => {
                  // Screened-out = the screener has a known passing set and this
                  // symbol isn't in it. Dim the row and label it so the user knows
                  // clicking won't land on a row (their filters hide it).
                  const screenedOut = screenMatches != null && !screenMatches.has(r.symbol);
                  return (
                    <div
                      key={r.symbol}
                      onClick={() => highlightInScreener(r.symbol)}
                      title={screenedOut ? "Hidden by your current screener filters" : undefined}
                      style={{ ...S.dropdownItem, opacity: screenedOut ? 0.5 : 1 }}
                    >
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: screenedOut ? "#64748b" : "#818cf8", minWidth: 70 }}>
                        {r.symbol.replace(".L", "")}
                      </span>
                      <span style={{ color: "#94a3b8", fontSize: 13 }}>{r.name}</span>
                      {screenedOut ? (
                        <span style={{ marginLeft: "auto", fontSize: 9, fontFamily: "monospace", textTransform: "uppercase", letterSpacing: 0.5, color: "#f59e0b", border: "1px solid #4a3a1a", background: "#1a1400", padding: "1px 6px", borderRadius: 2, whiteSpace: "nowrap" }}>
                          Filtered out
                        </span>
                      ) : (
                        <span style={{ marginLeft: "auto", fontSize: 11, color: "#64748b" }}>{r.exchange}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Mobile drawer */}
      {isMobile && mobileMenuOpen && (
        <>
          <div onClick={() => setMobileMenuOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 99 }} />
          <div style={{ position: "fixed", top: 52, left: 0, bottom: 0, width: 260, background: "#0d0d0d", borderRight: "1px solid #2a2a2a", zIndex: 100, overflowY: "auto", padding: "8px 0" }}>
            {NAV_GROUPS.map((g) => {
              const isActive = pathname === g.href;
              return (
                <Link
                  key={g.href}
                  href={g.href}
                  onClick={() => setMobileMenuOpen(false)}
                  style={{
                    display: "block", padding: "12px 20px",
                    background: isActive ? "#1f1200" : "none",
                    color: isActive ? "#f97316" : "#999",
                    fontSize: 13, fontFamily: "monospace",
                    fontWeight: isActive ? 700 : 400,
                    textDecoration: "none",
                  }}
                >
                  {g.label}
                </Link>
              );
            })}
            <Link
              href="/benchmarks"
              onClick={() => setMobileMenuOpen(false)}
              style={{
                display: "block", padding: "12px 20px",
                background: pathname === "/benchmarks" ? "#1f1200" : "none",
                color: pathname === "/benchmarks" ? "#f97316" : "#999",
                fontSize: 13, fontFamily: "monospace",
                fontWeight: pathname === "/benchmarks" ? 700 : 400,
                textDecoration: "none",
              }}
            >
              Benchmarks
            </Link>
            <a
              href={`${API}/help-doc`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setMobileMenuOpen(false)}
              style={{ display: "block", padding: "12px 20px", color: "#999", fontSize: 13, fontFamily: "monospace", textDecoration: "none" }}
            >
              Tool Manual Download
            </a>
            <div style={{ borderTop: "1px solid #1f1f1f", marginTop: 12, paddingTop: 12 }}>
              <Link
                href="/donate"
                onClick={() => setMobileMenuOpen(false)}
                style={{
                  display: "block", padding: "10px 20px",
                  background: pathname === "/donate" ? "#1f1200" : "none",
                  color: pathname === "/donate" ? "#f97316" : "#999",
                  fontSize: 13, fontFamily: "monospace",
                  fontWeight: pathname === "/donate" ? 700 : 400,
                  textDecoration: "none",
                }}
              >
                ♥ Support
              </Link>
              {isAdmin && (
                <button
                  onClick={() => { handleRefresh(); setMobileMenuOpen(false); }}
                  style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", padding: "10px 20px", color: "#666", cursor: "pointer", fontSize: 12, fontFamily: "monospace" }}
                >
                  ↻ Refresh Market Data
                </button>
              )}
              {isAdmin && (
                <button
                  onClick={handlePriceRefresh}
                  disabled={priceRefreshing}
                  style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", padding: "10px 20px", color: priceRefreshing ? "#f97316" : "#666", cursor: "pointer", fontSize: 12, fontFamily: "monospace" }}
                >
                  ↻ {priceRefreshing ? "Refreshing…" : "Refresh Stock Prices"}
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {/* Body: sidebar + main */}
      <div style={{ display: "flex", maxWidth: 1600, margin: "0 auto" }}>
        <div style={{ flexShrink: 0, display: showSidebar && !sidebarCollapsed && !isMobile ? "block" : "none" }}>
          <Sidebar refreshKey={refreshKey} onNavigate={onNavigate} />
        </div>
        <main style={{ flex: 1, padding: isMobile ? "12px 12px" : "16px 24px", minWidth: 0 }}>
          {children}
        </main>
      </div>
    </div>
  );
}
