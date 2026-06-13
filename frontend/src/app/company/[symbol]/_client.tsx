"use client";

import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";

const CompanyDetail = dynamic(() => import("@/components/company/CompanyDetail"), { ssr: false });

interface Props {
  symbol: string;
  initialTab?: string;
}

export default function CompanyClient({ symbol, initialTab }: Props) {
  const router = useRouter();
  return (
    <CompanyDetail
      symbol={symbol}
      onBack={() => router.back()}
      initialTab={initialTab}
    />
  );
}
