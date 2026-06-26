"use client";

import { useRefresh } from "@/app/providers";
import PageHeader from "@/components/layout/PageHeader";
import CrossAssetTab from "@/components/CrossAssetTab";
import FearGreedTab from "@/components/FearGreedTab";
import BreadthTab from "@/components/BreadthTab";
import RotationTab from "@/components/RotationTab";

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
      <BreadthTab refreshKey={refreshKey} />
      <RotationTab refreshKey={refreshKey} />
      <CrossAssetTab refreshKey={refreshKey} />
    </div>
  );
}
