import type { Metadata } from "next";
import Link from "next/link";
import { SITE_URL, SITE_NAME } from "@/lib/seo";
import { getResearchPosts } from "@/lib/research";
import { getLandingStory } from "@/lib/landingStory";
import { companyHref } from "@/lib/company";
import LandingEffects from "@/components/landing/LandingEffects";
import InstallButton from "@/components/landing/InstallButton";
import LandingSignup from "@/components/landing/LandingSignup";
import StoryPhone from "@/components/landing/StoryPhone";
import "./landing.css";

export const metadata: Metadata = {
  title: {
    absolute: "Alpha Move AI — Free UK Stock Screener (FTSE 100, 250, SmallCap, AIM)",
  },
  description:
    "Free UK stock screener for the entire London market — FTSE 100, 250, SmallCap and " +
    "AIM. Screen on fundamentals and composite scores, track analyst consensus, read " +
    "AI-scored RNS news and gauge the market with breadth and sector rotation.",
  alternates: { canonical: "/" },
};

// Featured mega-caps for the landing page's crawlable company links. Hardcoded —
// mega-caps churn rarely; swap manually if a constituent delists.
const FEATURED_COMPANIES: { symbol: string; name: string }[] = [
  { symbol: "SHEL.L", name: "Shell" },
  { symbol: "AZN.L", name: "AstraZeneca" },
  { symbol: "HSBA.L", name: "HSBC" },
  { symbol: "ULVR.L", name: "Unilever" },
  { symbol: "BP.L", name: "BP" },
  { symbol: "GSK.L", name: "GSK" },
  { symbol: "RIO.L", name: "Rio Tinto" },
  { symbol: "LSEG.L", name: "London Stock Exchange" },
  { symbol: "REL.L", name: "RELX" },
  { symbol: "DGE.L", name: "Diageo" },
  { symbol: "BARC.L", name: "Barclays" },
  { symbol: "NG.L", name: "National Grid" },
];

const CAPS: { href: string; title: string; body: string; icon: React.ReactNode }[] = [
  {
    href: "/screener",
    title: "Stock Screener",
    body: "Filter 600+ UK shares by valuation, quality, growth, momentum and risk, with composite scores computed daily.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
      </svg>
    ),
  },
  {
    href: "/markets",
    title: "Market Signals",
    body: "Read the room with the UK Fear & Greed index, market breadth, sector rotation and cross-asset signals.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3a9 9 0 109 9" /><path d="M12 12l5-3" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    href: "/trending",
    title: "Trending Movers",
    body: "Today's biggest risers and fallers, plus momentum streaks across every London index.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 17l6-6 4 4 8-8" /><path d="M21 7v5M21 7h-5" />
      </svg>
    ),
  },
  {
    href: "/analysts",
    title: "Analyst Consensus",
    body: "Broker ratings, price-target upside and the latest upgrades and downgrades for UK shares.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z" />
      </svg>
    ),
  },
  {
    href: "/rns",
    title: "RNS News, Scored",
    body: "London Stock Exchange regulatory announcements filtered and ranked by significance.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 4h11l3 3v13H5z" /><path d="M8 9h8M8 13h8M8 17h5" />
      </svg>
    ),
  },
  {
    href: "#subscribe",
    title: "Free Email Digest",
    body: "Your UK market before the open — notable movers and the RNS news that matters, every weekday at 07:30.",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 6h16v12H4z" /><path d="M4 7l8 6 8-6" />
      </svg>
    ),
  },
];

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: SITE_NAME,
  url: SITE_URL,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Web",
  offers: { "@type": "Offer", price: "0", priceCurrency: "GBP" },
  description:
    "Free UK stock screener for the FTSE 100, 250, SmallCap and AIM — fundamentals, " +
    "composite scores, analyst consensus, AI-scored RNS news and market signals.",
  featureList: [
    "UK stock screener (FTSE 100, 250, SmallCap, AIM)",
    "Composite quality, value, growth, momentum and risk scores",
    "UK Fear & Greed index, market breadth and sector rotation",
    "Analyst consensus, ratings and price-target upside",
    "AI-scored RNS regulatory news",
    "Free weekday email digest",
  ],
};

export default async function Home() {
  // Latest posts get first-class links from the homepage — the most-crawled
  // URL — so search engines discover new articles without waiting on a
  // /research index re-crawl. Degrades to the generic card if the API is down.
  // The story of the week now appears only as the phone player inside the
  // signup card, so the page fetches it and hands it straight to LandingSignup.
  const [allPosts, story] = await Promise.all([getResearchPosts(), getLandingStory()]);
  const posts = allPosts?.slice(0, 3) ?? [];
  const latest = posts[0];
  return (
    <div className="am-landing">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      {/* Reveal copy stays visible when JS is off / before hydration for crawlers. */}
      <noscript>
        {/* eslint-disable-next-line react/no-danger */}
        <style dangerouslySetInnerHTML={{ __html: ".am-landing .am-reveal{opacity:1;transform:none}" }} />
      </noscript>

      <canvas id="am-chart" aria-hidden="true" />
      <div className="am-bg-fade" aria-hidden="true" />

      <nav>
        <Link href="/" className="am-brand">
          <span className="am-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 17 L9 9 L13 13 L20 5" /><path d="M20 5 L20 10 M20 5 L15 5" />
            </svg>
          </span>
          Alpha&nbsp;Move&nbsp;AI
        </Link>
        <div className="am-nav-links">
          <Link href="/screener">Screener</Link>
          <Link href="/rns">RNS News</Link>
          <Link href="/markets">Markets</Link>
          <Link href="/screener" className="am-nav-cta">Open app</Link>
        </div>
      </nav>

      <header className="am-hero">
        <span className="am-eyebrow am-reveal"><span className="am-dot" />Free UK equity research</span>
        <h1 className="am-reveal">
          The free UK stock screener for <span className="am-accent">asymmetric opportunities.</span>
        </h1>
        <p className="am-sub am-reveal">
          Research the entire London market — FTSE 100, 250, SmallCap and AIM — in one place.
          Screen on fundamentals and composite scores, track analyst consensus, read AI-scored
          RNS news, and gauge the market with breadth and sector rotation.
        </p>
        <div className="am-actions am-reveal">
          <Link href="/screener" className="am-btn am-btn-primary">
            Open the screener
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Link>
          <Link href="/markets" className="am-btn am-btn-ghost">See market signals</Link>
          <InstallButton />
        </div>
        <Link
          href={latest ? `/research/${latest.slug}` : "/research"}
          className="am-research-cta am-reveal"
        >
          <span className="am-research-label">Latest research</span>
          <span className="am-research-title">
            {latest ? latest.title : "Analysis & market notes on UK equities"}
          </span>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </Link>
      </header>

      {/* Proof that the RNS scoring works — the story of the week, picked weekly
          by a backend cron, replayed as the phone player beside the signup copy.
          Omitted entirely if the API is down or nothing has been picked yet. */}
      <LandingSignup phone={story?.wire ? <StoryPhone story={story} /> : null} />

      <section className="am-caps" id="caps">
        <h2 className="am-caps-title am-reveal">What&apos;s inside</h2>
        <div className="am-caps-grid">
          {CAPS.map((c) => (
            <Link key={c.href} href={c.href} className="am-cap am-reveal">
              <div className="am-ic" aria-hidden="true">{c.icon}</div>
              <h3>{c.title}</h3>
              <p>{c.body}</p>
            </Link>
          ))}
        </div>
      </section>

      {/* Featured large caps — real crawlable links from the site's highest-authority
          page into the company pages, to seed discovery + pass PageRank. Hardcoded
          mega-caps (churn rarely; swap manually if one delists, like the sector
          proxy baskets in market.py). */}
      <section className="am-featured">
        <div className="am-featured-inner">
          <h2>Popular UK shares</h2>
          <div className="am-featured-links">
            {FEATURED_COMPANIES.map((c) => (
              <Link key={c.symbol} href={companyHref(c.symbol)}>{c.name}</Link>
            ))}
            <Link href="/companies" className="am-featured-all">All companies A–Z →</Link>
          </div>
        </div>
      </section>

      <footer>
        <div className="am-foot-inner">
          <div className="am-foot-brand">
            <Link href="/" className="am-brand">
              <span className="am-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 17 L9 9 L13 13 L20 5" /><path d="M20 5 L20 10 M20 5 L15 5" />
                </svg>
              </span>
              Alpha&nbsp;Move&nbsp;AI
            </Link>
            <p>Free research for the entire UK equity market — FTSE 100, 250, SmallCap and AIM.</p>
          </div>
          <div className="am-foot-cols">
            <div className="am-foot-col">
              <h4>Research</h4>
              <Link href="/screener">Stock Screener</Link>
              <Link href="/companies">All Companies A–Z</Link>
              <Link href="/trending">Trending Movers</Link>
              <Link href="/analysts">Analyst Consensus</Link>
              <Link href="/rns">RNS News</Link>
            </div>
            <div className="am-foot-col">
              <h4>Markets</h4>
              <Link href="/markets">Market Signals</Link>
              <Link href="/benchmarks">Benchmarks</Link>
              <Link href="/heatmap">Heatmap</Link>
              <Link href="/subscribe">Email Digest</Link>
            </div>
            {posts.length > 0 && (
              <div className="am-foot-col am-foot-col-posts">
                <h4>Latest Research</h4>
                {posts.map((p) => (
                  <Link key={p.slug} href={`/research/${p.slug}`} title={p.title}>
                    {p.title}
                  </Link>
                ))}
                <Link href="/research">All research →</Link>
              </div>
            )}
            <div className="am-foot-col">
              <h4>About</h4>
              <Link href="/feedback">Feedback</Link>
              <Link href="/donate">Support</Link>
            </div>
          </div>
        </div>
        <p className="am-foot-legal">
          Alpha Move AI is a free research tool for UK equities and does not provide financial
          advice. Always do your own research before investing. © {new Date().getFullYear()}{" "}
          {SITE_NAME}.
        </p>
      </footer>

      <LandingEffects />
    </div>
  );
}
