"use client";

import dynamic from "next/dynamic";

// The loading placeholder matches CompanyDetail's own loading-state minHeight:
// with ssr:false the server HTML is empty here, so without it the server-rendered
// enrichment below would sit high on the page and then be shoved down when the
// dashboard chunk mounts (CLS on every company-page view).
const CompanyDetail = dynamic(() => import("@/components/company/CompanyDetail"), {
  ssr: false,
  loading: () => <div style={{ minHeight: 400 }} />,
});

interface Props {
  symbol: string;
  initialTab?: string;
}

export default function CompanyClient({ symbol, initialTab }: Props) {
  return (
    <CompanyDetail
      symbol={symbol}
      initialTab={initialTab}
    />
  );
}
