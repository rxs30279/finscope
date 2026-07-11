import type { Metadata, Viewport } from "next";
import { Inter, Mulish } from "next/font/google";
import Script from "next/script";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";
import { WatchlistProvider, RefreshProvider } from "./providers";
import { PostHogProvider } from "./posthog-provider";
import AppShell from "@/components/layout/AppShell";
import { SITE_URL, SITE_NAME } from "@/lib/seo";

// Self-hosted at build time (no runtime Google Fonts fetch, no FOUT). Both are
// variable fonts, so the full weight range is available — globals.css wires
// these CSS variables to the inline `monospace` (Inter) and `DM Serif Display`
// (Mulish) keyword placeholders used throughout the app.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});
const mulish = Mulish({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mulish",
});

export const viewport: Viewport = {
  themeColor: "#0d1117",
};

const DEFAULT_TITLE = "Alpha Move AI — UK Stock Screener";
const DEFAULT_DESCRIPTION =
  "Free UK stock screener for FTSE 100, 250, SmallCap and AIM — fundamentals, " +
  "composite scores, analyst consensus, RNS news and market signals.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: DEFAULT_TITLE,
    template: "%s | Alpha Move AI",
  },
  description: DEFAULT_DESCRIPTION,
  applicationName: SITE_NAME,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    url: SITE_URL,
    // og:image is supplied by the app/opengraph-image.tsx file convention.
  },
  twitter: {
    card: "summary_large_image",
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    // twitter:image falls back to the opengraph-image convention.
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon-16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-48.png", sizes: "48x48", type: "image/png" },
    ],
    apple: { url: "/apple-touch-icon.png", sizes: "180x180" },
  },
  // NOTE: the manifest <link> is rendered directly in <head> below rather than
  // here. Next's Metadata API streams it into the body and lets React hoist it
  // to <head> after hydration, which Chrome's installability/DevTools check
  // does not reliably pick up ("No manifest detected"). A static head link is
  // present at HTML-parse time, so the PWA is detected and installable.
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${mulish.variable}`}>
      <head>
        {/* PWA manifest — kept as a literal head link (not via the Metadata
            API) so it is present at HTML-parse time and reliably detected as
            installable. See the metadata note above. */}
        <link rel="manifest" href="/site.webmanifest" />
        {/* Google Analytics 4 */}
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-4D7NSXL95B"
          strategy="lazyOnload"
        />
        <Script id="ga4-init" strategy="lazyOnload">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-4D7NSXL95B');
          `}
        </Script>
      </head>
      <body style={{ margin: 0 }} suppressHydrationWarning>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify([
              {
                "@context": "https://schema.org",
                "@type": "WebSite",
                name: SITE_NAME,
                url: SITE_URL,
                description: DEFAULT_DESCRIPTION,
              },
              {
                "@context": "https://schema.org",
                "@type": "Organization",
                name: SITE_NAME,
                url: SITE_URL,
                logo: `${SITE_URL}/android-chrome-512.png`,
              },
            ]),
          }}
        />
        <PostHogProvider>
          <WatchlistProvider>
            <RefreshProvider>
              <AppShell>{children}</AppShell>
            </RefreshProvider>
          </WatchlistProvider>
        </PostHogProvider>
        <Analytics />
        {/* Sampled to conserve the Speed Insights data-point quota — still enough
            volume per page to see trends (e.g. ~35+/period on high-impact-rns). */}
        <SpeedInsights sampleRate={0.25} />
      </body>
    </html>
  );
}
