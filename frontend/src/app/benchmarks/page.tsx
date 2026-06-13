import type { Metadata } from "next";
import BenchmarksPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK Index Benchmarks",
  description:
    "Benchmark performance across the FTSE 100, 250, SmallCap and AIM, plus key " +
    "market gauges for UK equities.",
  alternates: { canonical: "/benchmarks" },
};

export default function BenchmarksPage() {
  return <BenchmarksPageClient />;
}
