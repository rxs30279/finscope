"use client";

import dynamic from "next/dynamic";

const CompanyDetail = dynamic(() => import("@/components/company/CompanyDetail"), { ssr: false });

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
