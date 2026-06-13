"use client";

import { useRefresh } from "@/app/providers";
import CrossAssetTab from "@/components/CrossAssetTab";
import FearGreedTab from "@/components/FearGreedTab";
import BreadthTab from "@/components/BreadthTab";
import RotationTab from "@/components/RotationTab";

export default function MarketsPageClient() {
  const { refreshKey } = useRefresh();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
      <CrossAssetTab refreshKey={refreshKey} />
      <FearGreedTab refreshKey={refreshKey} />
      <BreadthTab refreshKey={refreshKey} />
      <RotationTab refreshKey={refreshKey} />
    </div>
  );
}
