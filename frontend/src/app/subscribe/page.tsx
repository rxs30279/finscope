import type { Metadata } from "next";
import SubscribeTab from "@/components/SubscribeTab";

export const metadata: Metadata = {
  title: "Free UK Market Email — Your Market Before the Open",
  description:
    "A free weekday email at 07:30 GMT: AI-ranked UK movers and the RNS news that " +
    "actually matters, across FTSE 100, 250, SmallCap and AIM. One-click unsubscribe.",
  alternates: { canonical: "/subscribe" },
};

export default function SubscribePage() {
  return <SubscribeTab />;
}
