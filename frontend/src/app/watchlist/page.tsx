import type { Metadata } from "next";
import WatchlistPageClient from "./_client";

// User-specific state stored in the browser — no shared content to index.
export const metadata: Metadata = {
  title: "My Watchlist",
  description: "Your saved UK shares and watchlists on Alpha Move AI.",
  robots: { index: false, follow: true },
  alternates: { canonical: "/watchlist" },
};

export default function WatchlistPage() {
  return <WatchlistPageClient />;
}
