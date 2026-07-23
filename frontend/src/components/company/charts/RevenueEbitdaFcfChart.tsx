"use client";

import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  sym: string;
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function RevenueEbitdaFcfChart({ data, sym, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <defs>
          <linearGradient id="gR" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} /><stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gE" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip formatter={(v: any) => sym + v?.toFixed(2) + "B"} contentStyle={S.tooltip} />
        <Area type="monotone" dataKey="revenue" stroke="#6366f1" fill="url(#gR)" strokeWidth={2} dot={singleDot("revenue", "#6366f1")} name="Revenue" />
        <Area type="monotone" dataKey="ebitda" stroke="#10b981" fill="url(#gE)" strokeWidth={2} dot={singleDot("ebitda", "#10b981")} name="EBITDA" />
        <Line type="monotone" dataKey="fcf" stroke="#f59e0b" strokeWidth={2} dot={singleDot("fcf", "#f59e0b")} name="FCF" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
