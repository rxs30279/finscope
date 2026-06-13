import type { Metadata } from "next";
import FeedbackTab from "@/components/FeedbackTab";

export const metadata: Metadata = {
  title: "Feedback",
  description: "Tell us what you'd like to see next in Alpha Move AI's UK stock screener.",
  alternates: { canonical: "/feedback" },
};

export default function FeedbackPage() {
  return <FeedbackTab />;
}
