"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  sym: string;
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function EpsChart({ data, sym, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v: any) => sym + v?.toFixed(2)} contentStyle={S.tooltip} />
        <ReferenceLine y={0} stroke="#334155" />
        <Line type="monotone" dataKey="eps" stroke="#6366f1" strokeWidth={2.5} dot={singleDot("eps", "#6366f1")} name="EPS" />
      </LineChart>
    </ResponsiveContainer>
  );
}
