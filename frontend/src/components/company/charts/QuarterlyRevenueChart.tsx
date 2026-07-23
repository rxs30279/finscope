"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  sym: string;
}

export default function QuarterlyRevenueChart({ data, sym }: Props) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="q" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
        <Bar dataKey="revenue" fill="#6366f1" radius={[4, 4, 0, 0]} name="Revenue" />
      </BarChart>
    </ResponsiveContainer>
  );
}
