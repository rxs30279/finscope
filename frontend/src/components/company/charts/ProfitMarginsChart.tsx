"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function ProfitMarginsChart({ data, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} unit="%" />
        <Tooltip formatter={(v: any) => `${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
        <ReferenceLine y={0} stroke="#334155" />
        <Line type="monotone" dataKey="gross_margin" stroke="#6366f1" strokeWidth={2} dot={singleDot("gross_margin", "#6366f1")} name="Gross Margin" />
        <Line type="monotone" dataKey="op_margin" stroke="#10b981" strokeWidth={2} dot={singleDot("op_margin", "#10b981")} name="Op. Margin" />
        <Line type="monotone" dataKey="net_margin" stroke="#f59e0b" strokeWidth={2} dot={singleDot("net_margin", "#f59e0b")} name="Net Margin" />
      </LineChart>
    </ResponsiveContainer>
  );
}
