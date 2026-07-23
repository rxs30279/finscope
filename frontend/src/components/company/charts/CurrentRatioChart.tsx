"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function CurrentRatioChart({ data, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={210}>
      <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
        <Tooltip contentStyle={S.tooltip} />
        <ReferenceLine y={1} stroke="#f59e0b" strokeDasharray="4 4" />
        <Line type="monotone" dataKey="curr_ratio" stroke="#10b981" strokeWidth={2.5} dot={singleDot("curr_ratio", "#10b981")} name="Current Ratio" />
      </LineChart>
    </ResponsiveContainer>
  );
}
