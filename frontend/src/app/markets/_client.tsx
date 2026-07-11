"use client";

import dynamic from "next/dynamic";
import { useRefresh } from "@/app/providers";
import PageHeader from "@/components/layout/PageHeader";
import LazySection from "@/components/LazySection";
import FearGreedTab from "@/components/FearGreedTab";

// Below-the-fold tabs: each pulls in recharts and fires its own API calls on
// mount, so they're code-split out of the initial bundle and, via
// LazySection, not even mounted until scrolled near — keeps the /markets
// first load to one chart (FearGreedTab) instead of four.
const BreadthTab = dynamic(() => import("@/components/BreadthTab"), { ssr: false });
const RotationTab = dynamic(() => import("@/components/RotationTab"), { ssr: false });
const CrossAssetTab = dynamic(() => import("@/components/CrossAssetTab"), { ssr: false });

export default function MarketsPageClient() {
  const { refreshKey } = useRefresh();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
      <PageHeader
        title="Market Signals"
        subtitle="The UK Fear & Greed index, market breadth, sector rotation and cross-asset signals for the London market."
        marginBottom={0}
      />
      <FearGreedTab refreshKey={refreshKey} />
      <LazySection minHeight={420}>
        <BreadthTab refreshKey={refreshKey} />
      </LazySection>
      <LazySection minHeight={420}>
        <RotationTab refreshKey={refreshKey} />
      </LazySection>
      <LazySection minHeight={420}>
        <CrossAssetTab refreshKey={refreshKey} />
      </LazySection>
    </div>
  );
}
