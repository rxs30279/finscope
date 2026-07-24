"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { useIsAdmin } from "@/hooks/useAdmin";
import { fmtPostDate, type ResearchPostSummary } from "@/lib/research";
import { coverFor, HERO_COVER, CTA_COVER } from "@/lib/researchCovers";

export default function ResearchListClient({
  initialPosts,
}: {
  initialPosts: ResearchPostSummary[] | null;
}) {
  const isAdmin = useIsAdmin();
  // Server-rendered when the page's server fetch succeeded; the client fetch
  // below is only the fallback for when it didn't.
  const [posts, setPosts] = useState<ResearchPostSummary[] | null>(initialPosts);
  const [error, setError] = useState(false);
  const [activeTag, setActiveTag] = useState<string | null>(null);

  useEffect(() => {
    if (initialPosts !== null) return;
    fetch(`${API}/research/posts`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setPosts(d.posts || []))
      .catch(() => setError(true));
  }, [initialPosts]);

  const list = useMemo(() => posts ?? [], [posts]);
  const featured = list[0] ?? null;

  // Cover art is assigned by a post's position in the full list, so every card
  // gets a distinct render (see researchCovers). Map slug -> index once.
  const coverIndex = useMemo(() => {
    const m = new Map<string, number>();
    list.forEach((p, i) => m.set(p.slug, i));
    return m;
  }, [list]);

  // Tabs + rail categories are derived from the tags that actually exist, most
  // used first — no hardcoded taxonomy to drift out of sync with the posts.
  const tagCounts = useMemo(() => {
    const m = new Map<string, number>();
    list.forEach((p) => p.tags?.forEach((t) => m.set(t, (m.get(t) ?? 0) + 1)));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [list]);

  const gridPosts = useMemo(() => {
    if (activeTag) {
      return list.filter((p) => p.id !== featured?.id && p.tags?.includes(activeTag));
    }
    return featured ? list.filter((p) => p.id !== featured.id) : list;
  }, [list, featured, activeTag]);

  const recent = useMemo(() => list.slice(1, 4), [list]);

  // The rail only shows the busiest categories so it doesn't run long; the
  // active tag is always kept visible even if it falls outside the top slice.
  const railTags = useMemo(() => {
    const top = tagCounts.slice(0, 8);
    if (activeTag && !top.some(([t]) => t === activeTag)) {
      const extra = tagCounts.find(([t]) => t === activeTag);
      if (extra) top.push(extra);
    }
    return top;
  }, [tagCounts, activeTag]);

  return (
    <div className="amr amr-bleed">
      {/* ── Hero ─────────────────────────────────────────────── */}
      <header className="amr-hero">
        <div
          className="amr-hero-img"
          style={{ backgroundImage: `url("${HERO_COVER.src}")`, backgroundPosition: HERO_COVER.position }}
        />
        <div className="amr-hero-scrim" />
        <div className="amr-hero-blur" />
        <div className="amr-hero-inner">
          {isAdmin && (
            <Link href="/research/admin" className="amr-admin">
              ✎ Manage posts
            </Link>
          )}
          <span className="amr-eyebrow">
            Analysis <span className="amr-dot">·</span> Data <span className="amr-dot">·</span> Signals
          </span>
          <h1>UK Equity Research &amp; Market Notes</h1>
          <p className="amr-sub">
            Data-driven analysis, methodology notes and market signals from the desk behind the
            Alpha Move screener.
          </p>
        </div>
      </header>

      {error && (
        <div className="amr-wrap amr-note amr-note--err">Couldn&apos;t load posts.</div>
      )}
      {!error && posts === null && <div className="amr-wrap amr-note">Loading…</div>}
      {!error && posts !== null && list.length === 0 && (
        <div className="amr-wrap amr-note">No articles published yet — check back soon.</div>
      )}

      {list.length > 0 && (
        <div className="amr-wrap">
          {/* ── Featured (latest) ──────────────────────────────── */}
          {featured && (
            <Link href={`/research/${featured.slug}`} className="amr-featured">
              <div
                className="amr-fimg"
                style={{
                  backgroundImage: `url("${coverFor(featured, coverIndex.get(featured.slug)).src}")`,
                  backgroundPosition: coverFor(featured, coverIndex.get(featured.slug)).position,
                }}
              />
              <div className="amr-fbody">
                <div className="amr-tagrow">
                  {featured.tags?.[0] && <span className="amr-tag">{featured.tags[0]}</span>}
                  <span className="amr-eyebrow">{fmtPostDate(featured.published_at)}</span>
                </div>
                <h2>{featured.title}</h2>
                {featured.summary && <p>{featured.summary}</p>}
                <span className="amr-readmore">
                  Read the analysis <span className="amr-arw">→</span>
                </span>
              </div>
            </Link>
          )}

          {/* ── Grid + rail ────────────────────────────────────── */}
          <div className="amr-layout">
            <div className="amr-cards">
              {gridPosts.map((p) => {
                const c = coverFor(p, coverIndex.get(p.slug));
                return (
                  <Link key={p.id} href={`/research/${p.slug}`} className="amr-card">
                    <div className="amr-thumb">
                      <i style={{ backgroundImage: `url("${c.src}")`, backgroundPosition: c.position }} />
                    </div>
                    <div className="amr-cbody">
                      {p.tags?.[0] && (
                        <div className="amr-tagrow">
                          <span className="amr-tag">{p.tags[0]}</span>
                        </div>
                      )}
                      <h3>{p.title}</h3>
                      {p.summary && <p>{p.summary}</p>}
                      <div className="amr-meta">
                        <span className="amr-date">{fmtPostDate(p.published_at)}</span>
                        {p.comment_count > 0 && (
                          <span className="amr-cc">
                            · {p.comment_count} comment{p.comment_count === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                    </div>
                  </Link>
                );
              })}
              {gridPosts.length === 0 && (
                <div className="amr-note" style={{ gridColumn: "1 / -1" }}>
                  No notes in this category yet.
                </div>
              )}
            </div>

            <aside className="amr-rail">
              {/* Screener CTA — the one place brand orange appears */}
              <div className="amr-cta">
                <i
                  className="amr-cta-bg"
                  style={{ backgroundImage: `url("${CTA_COVER.src}")`, backgroundPosition: CTA_COVER.position }}
                />
                <div className="amr-cta-veil" />
                <div className="amr-cta-content">
                  <span className="amr-eyebrow amr-eyebrow--orange">The tool</span>
                  <h4>Screen 750+ UK stocks</h4>
                  <p>
                    Every note here comes out of the same engine — momentum, quality, value and risk
                    across the whole FTSE + AIM universe.
                  </p>
                  <Link href="/screener" className="amr-btn-orange">
                    Open the screener →
                  </Link>
                </div>
              </div>

              {recent.length > 0 && (
                <div className="amr-panel">
                  <div className="amr-ph">
                    <h4>Recent</h4>
                  </div>
                  <div className="amr-pb">
                    <div className="amr-recent">
                      {recent.map((p) => {
                        const c = coverFor(p, coverIndex.get(p.slug));
                        return (
                          <Link key={p.id} href={`/research/${p.slug}`}>
                            <span
                              className="amr-rt"
                              style={{ backgroundImage: `url("${c.src}")`, backgroundPosition: c.position }}
                            />
                            <span>
                              <span className="amr-rtx">{p.title}</span>
                              <span className="amr-rd">{fmtPostDate(p.published_at)}</span>
                            </span>
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {tagCounts.length > 0 && (
                <div className="amr-panel amr-panel--cats">
                  <div className="amr-ph">
                    <h4>Categories</h4>
                  </div>
                  <div className="amr-pb">
                    <div className="amr-rlist">
                      <button
                        className={`amr-rlink${activeTag === null ? " on" : ""}`}
                        onClick={() => setActiveTag(null)}
                      >
                        All notes <span className="amr-n">{list.length}</span>
                      </button>
                      {railTags.map(([tag, n]) => (
                        <button
                          key={tag}
                          className={`amr-rlink${activeTag === tag ? " on" : ""}`}
                          onClick={() => setActiveTag(tag)}
                        >
                          {tag} <span className="amr-n">{n}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="amr-panel">
                <div className="amr-ph">
                  <h4>Daily RNS email</h4>
                </div>
                <div className="amr-pb">
                  <p className="amr-panel-p">
                    The highest-impact announcements, ranked and in your inbox before the open.
                  </p>
                  <Link href="/subscribe" className="amr-btn-ghost">
                    Get the daily email →
                  </Link>
                </div>
              </div>
            </aside>
          </div>
        </div>
      )}

      {/* ── Footer CTA ───────────────────────────────────────── */}
      {list.length > 0 && (
        <div className="amr-footer-cta">
          <div className="amr-wrap amr-footer-inner">
            <div>
              <h3>See the highest-impact RNS.</h3>
              <p>The day&apos;s most significant announcements, ranked — free, no signup, updated daily.</p>
            </div>
            <Link href="/high-impact-rns" className="amr-btn-orange">
              View high-impact RNS →
            </Link>
          </div>
        </div>
      )}

      <ResearchListStyles />
    </div>
  );
}

// Styles for the research index. Scoped by the `.amr` prefix so nothing leaks
// into the app's monospace chrome. Layout-only here — every background image is
// set inline on the element so this stays static.
function ResearchListStyles() {
  return (
    <style jsx global>{`
      .amr {
        --white: #f1f5f9;
        --text: #e5e5e5;
        --muted: #a0a0b8;
        --faint: #6b6b85;
        --dim: #55556b;
        --border: #342a52;
        --border-subtle: #271d40;
        --card: #1b1330;
        --alt: #140c26;
        --indigo: #a5aefc;
        --purple: #a855f7;
        --indigo-ghost: rgba(129, 140, 248, 0.12);
        --orange: #f97316;
        font-family: var(--font-inter), system-ui, sans-serif;
        color: var(--text);
        line-height: 1.6;
        position: relative;
        background:
          radial-gradient(1100px 620px at 80% -8%, rgba(147, 51, 234, 0.12), transparent 60%),
          radial-gradient(900px 700px at 4% 8%, rgba(109, 40, 217, 0.18), transparent 55%),
          radial-gradient(1200px 900px at 50% 118%, rgba(124, 58, 237, 0.20), transparent 60%),
          linear-gradient(180deg, #1b1136 0%, #150c29 48%, #100820 100%);
      }
      /* Break out of AppShell's main padding (16/24 desktop, 12/12 ≤943). */
      .amr-bleed { margin: -16px -24px 0; }
      @media (max-width: 943px) { .amr-bleed { margin: -12px -12px 0; } }

      .amr a { text-decoration: none; color: inherit; }
      .amr h1, .amr h2, .amr h3, .amr h4 {
        font-family: var(--font-mulish), var(--font-inter), sans-serif;
        text-wrap: balance;
      }
      .amr-wrap { max-width: 1180px; margin: 0 auto; padding: 0 22px; }
      .amr-eyebrow {
        font-family: var(--font-inter), sans-serif; text-transform: uppercase;
        letter-spacing: 0.2em; font-size: 10.5px; font-weight: 600; color: var(--faint);
        font-variant-numeric: tabular-nums;
      }
      .amr-eyebrow--orange { color: var(--orange); }
      .amr-dot { color: var(--purple); }

      .amr-note {
        text-align: center; padding: 44px 22px; color: var(--muted);
        font-family: var(--font-inter), sans-serif; font-size: 14px;
      }
      .amr-note--err { color: #ef4444; }

      /* Hero */
      .amr-hero { position: relative; overflow: hidden; }
      .amr-hero-img {
        position: absolute; inset: 0; background-size: cover; transform: scale(1.04);
      }
      .amr-hero-scrim {
        position: absolute; inset: 0;
        background:
          radial-gradient(120% 90% at 78% 30%, rgba(168, 85, 247, 0.26), transparent 60%),
          linear-gradient(180deg, rgba(27, 17, 54, 0.5) 0%, rgba(21, 12, 41, 0.32) 38%, rgba(24, 15, 47, 0.88) 82%, #1b1136 100%);
      }
      /* Frost the lower edge so the image dissolves into the page background.
         Sits below .amr-hero-inner in paint order, so the heading stays crisp. */
      .amr-hero-blur {
        position: absolute; left: 0; right: 0; bottom: 0; height: 45%;
        backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
        -webkit-mask-image: linear-gradient(180deg, transparent 0%, #000 72%);
        mask-image: linear-gradient(180deg, transparent 0%, #000 72%);
        pointer-events: none;
      }
      .amr-hero-inner {
        position: relative; max-width: 1180px; margin: 0 auto;
        padding: 74px 22px 66px; text-align: center;
      }
      .amr-hero h1 {
        font-size: clamp(32px, 4.8vw, 54px); font-weight: 800; letter-spacing: -0.03em;
        line-height: 1.03; margin: 15px auto 0; max-width: 15ch; color: var(--white);
      }
      .amr-sub { max-width: 560px; margin: 17px auto 0; color: var(--muted); font-size: 15.5px; }
      .amr-admin {
        position: absolute; top: 18px; right: 22px; font-size: 11px;
        color: var(--orange); border: 1px solid #3a2600; background: #1f1200;
        padding: 5px 11px; border-radius: 3px; font-family: var(--font-inter), sans-serif;
      }

      /* Featured */
      .amr-featured {
        display: grid; grid-template-columns: 1.15fr 1fr; margin: 40px 0 8px;
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
        background: var(--card); transition: border-color 0.18s ease;
      }
      .amr-featured:hover { border-color: #3a3550; }
      .amr-fimg { position: relative; min-height: 320px; background-size: cover; }
      .amr-fimg::after {
        content: ""; position: absolute; inset: 0;
        background: linear-gradient(90deg, transparent 55%, var(--card));
      }
      .amr-fbody { padding: 34px 36px; display: flex; flex-direction: column; justify-content: center; }
      .amr-tagrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 13px; }
      .amr-tag {
        font-family: var(--font-inter), sans-serif; font-size: 10px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.09em; color: var(--indigo);
        background: var(--indigo-ghost); border: 1px solid rgba(129, 140, 248, 0.22);
        padding: 3px 9px; border-radius: 3px;
      }
      .amr-featured h2 {
        font-size: clamp(25px, 3vw, 34px); font-weight: 800; letter-spacing: -0.02em;
        line-height: 1.13; color: var(--white); margin: 4px 0 13px;
      }
      .amr-featured p { color: var(--muted); font-size: 15px; margin: 0 0 22px; max-width: 46ch; }
      .amr-readmore { font-size: 12.5px; font-weight: 700; color: var(--indigo); }
      .amr-arw { display: inline-block; transition: transform 0.18s ease; }
      .amr-featured:hover .amr-arw { transform: translateX(4px); }

      /* Grid */
      .amr-layout { display: grid; grid-template-columns: 1fr 300px; gap: 40px; margin-top: 40px; padding-bottom: 56px; }
      .amr-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; align-content: start; }
      .amr-card {
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
        background: var(--card); display: flex; flex-direction: column;
        transition: box-shadow 0.18s ease, border-color 0.18s ease;
      }
      .amr-card:hover { border-color: #3a3550; box-shadow: 0 10px 28px rgba(0, 0, 0, 0.38); }
      .amr-thumb { position: relative; aspect-ratio: 16 / 10; overflow: hidden; }
      .amr-thumb i {
        position: absolute; inset: 0; background-size: cover;
        transition: transform 0.5s ease;
      }
      .amr-card:hover .amr-thumb i { transform: scale(1.07); }
      .amr-thumb::after {
        content: ""; position: absolute; inset: 0;
        background: linear-gradient(180deg, transparent 45%, rgba(27, 19, 48, 0.6));
      }
      .amr-cbody { padding: 18px 20px 22px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
      .amr-card h3 { font-size: 18px; font-weight: 800; letter-spacing: -0.015em; line-height: 1.24; color: var(--white); margin: 0; }
      .amr-card p { margin: 0; color: var(--muted); font-size: 13.5px; line-height: 1.55; }
      .amr-meta { margin-top: auto; display: flex; align-items: center; gap: 8px; }
      .amr-date { font-size: 10.5px; color: var(--faint); letter-spacing: 0.06em; text-transform: uppercase; font-variant-numeric: tabular-nums; }
      .amr-cc { font-size: 10.5px; color: var(--dim); }

      /* Rail */
      .amr-rail { display: flex; flex-direction: column; gap: 20px; align-content: start; }
      .amr-panel { border: 1px solid var(--border); border-radius: 10px; background: var(--card); overflow: hidden; }
      .amr-ph { padding: 13px 18px; border-bottom: 1px solid var(--border-subtle); }
      .amr-ph h4 { margin: 0; font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--indigo); }
      .amr-pb { padding: 8px 18px 14px; }
      .amr-panel-p { margin: 6px 0 12px; font-size: 12.5px; color: var(--muted); line-height: 1.5; }

      .amr-cta { position: relative; border: 1px solid #3a2600; border-radius: 10px; overflow: hidden; padding: 22px 20px; background: linear-gradient(155deg, #1c1204, #120c02); }
      .amr-cta-bg { position: absolute; inset: 0; background-size: cover; opacity: 0.34; }
      .amr-cta-veil {
        position: absolute; inset: 0;
        background:
          radial-gradient(90% 80% at 82% 6%, rgba(249, 115, 22, 0.22), transparent 60%),
          linear-gradient(155deg, rgba(28, 18, 4, 0.55) 0%, rgba(18, 12, 2, 0.92) 78%);
      }
      .amr-cta-content { position: relative; }
      .amr-cta h4 { margin: 8px 0 6px; font-size: 17px; font-weight: 800; color: var(--white); letter-spacing: -0.01em; }
      .amr-cta p { margin: 0 0 16px; font-size: 12.5px; color: var(--muted); }
      .amr-btn-orange {
        display: inline-flex; align-items: center; gap: 7px; font-family: var(--font-inter), sans-serif;
        font-size: 12px; font-weight: 700; letter-spacing: 0.03em; color: #0a0a0a;
        background: var(--orange); padding: 9px 16px; border-radius: 4px;
        box-shadow: 0 0 18px rgba(249, 115, 22, 0.28);
      }
      .amr-btn-ghost {
        display: inline-flex; font-family: var(--font-inter), sans-serif; font-size: 11.5px; font-weight: 700;
        color: var(--indigo); background: var(--indigo-ghost); border: 1px solid rgba(129, 140, 248, 0.3);
        padding: 8px 13px; border-radius: 4px;
      }

      .amr-rlist { display: flex; flex-direction: column; }
      .amr-rlink {
        display: flex; justify-content: space-between; align-items: center; padding: 9px 0;
        border-bottom: 1px solid var(--border-subtle); font-size: 13px; color: var(--text);
        background: none; border-left: none; border-right: none; border-top: none;
        font-family: var(--font-inter), sans-serif; text-align: left; cursor: pointer; width: 100%;
      }
      .amr-rlist .amr-rlink:last-child { border-bottom: none; }
      .amr-rlink .amr-n { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
      .amr-rlink:hover, .amr-rlink.on { color: var(--indigo); }

      .amr-recent { display: flex; flex-direction: column; }
      .amr-recent a { display: flex; gap: 12px; padding: 11px 0; border-bottom: 1px solid var(--border-subtle); }
      .amr-recent a:last-child { border-bottom: none; }
      .amr-rt { width: 54px; height: 44px; border-radius: 5px; flex-shrink: 0; background-size: cover; }
      .amr-rtx { font-size: 12.5px; font-weight: 600; color: var(--text); line-height: 1.32; display: block; }
      .amr-recent a:hover .amr-rtx { color: var(--white); }
      .amr-rd { font-size: 10px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.06em; margin-top: 3px; display: block; font-variant-numeric: tabular-nums; }

      /* Footer CTA */
      .amr-footer-cta { border-top: 1px solid var(--border-subtle); background: var(--alt); }
      .amr-footer-inner { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding-top: 32px; padding-bottom: 32px; flex-wrap: wrap; }
      .amr-footer-cta h3 { margin: 0 0 6px; font-size: 22px; font-weight: 800; color: var(--white); letter-spacing: -0.02em; }
      .amr-footer-cta p { margin: 0; color: var(--muted); font-size: 14px; }

      @media (max-width: 900px) {
        .amr-featured { grid-template-columns: 1fr; }
        .amr-fimg { min-height: 200px; }
        .amr-fimg::after { background: linear-gradient(180deg, transparent 40%, var(--card)); }
        .amr-layout { grid-template-columns: 1fr; }
        .amr-panel--cats { display: none; }
      }
      @media (max-width: 560px) { .amr-cards { grid-template-columns: 1fr; } }

      @media (prefers-reduced-motion: reduce) {
        .amr *, .amr *::before, .amr *::after { transition: none !important; animation: none !important; }
        .amr-card:hover { transform: none; }
      }
    `}</style>
  );
}
