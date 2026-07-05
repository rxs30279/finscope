import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // /watchlist: user-specific, no shared content. /high-impact-rns: hidden
      // preproduction route, admin-gated until public release.
      disallow: ["/watchlist", "/high-impact-rns"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
