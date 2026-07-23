"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function ReturnOnCapitalChart({ data, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} unit="%" />
        <Tooltip formatter={(v: any) => `${v?.toFixed(1)}%`} contentStyle={S.tooltip} />
        <ReferenceLine y={0} stroke="#334155" />
        <Line type="monotone" dataKey="roe" stroke="#6366f1" strokeWidth={2} dot={singleDot("roe", "#6366f1")} name="ROE" />
        <Line type="monotone" dataKey="roic" stroke="#10b981" strokeWidth={2} dot={singleDot("roic", "#10b981")} name="ROIC" />
        <Line type="monotone" dataKey="roa" stroke="#f59e0b" strokeWidth={2} dot={singleDot("roa", "#f59e0b")} name="ROA" />
      </LineChart>
    </ResponsiveContainer>
  );
}
