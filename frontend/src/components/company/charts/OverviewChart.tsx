"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  sym: string;
}

export default function OverviewChart({ data, sym }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
        <YAxis tick={{ fontSize: 11, fill: "#666", fontFamily: "monospace" }} />
        <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
        <Bar dataKey="revenue" fill="#f97316" radius={[2, 2, 0, 0]} name="Revenue" />
        <Bar dataKey="net_income" fill="#10b981" radius={[2, 2, 0, 0]} name="Net Income" />
      </BarChart>
    </ResponsiveContainer>
  );
}
