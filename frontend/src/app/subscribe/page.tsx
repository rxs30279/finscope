import type { Metadata } from "next";
import SubscribeTab from "@/components/SubscribeTab";

export const metadata: Metadata = {
  title: "Subscribe — Free UK Market Email Digest",
  description:
    "Get a free weekday email digest of UK market signals, notable movers and the " +
    "most significant RNS news from Alpha Move AI.",
  alternates: { canonical: "/subscribe" },
};

export default function SubscribePage() {
  return <SubscribeTab />;
}
