"use client";

import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { S } from "@/lib/theme";

interface Props {
  data: any[];
  singleDot: (key: string, fill: string) => { r: number; fill: string } | false;
}

export default function DebtEquityChart({ data, singleDot }: Props) {
  return (
    <ResponsiveContainer width="100%" height={210}>
      <AreaChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <defs>
          <linearGradient id="gD" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="year" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
        <Tooltip contentStyle={S.tooltip} />
        <Area type="monotone" dataKey="debt_eq" stroke="#ef4444" fill="url(#gD)" strokeWidth={2} dot={singleDot("debt_eq", "#ef4444")} name="D/E" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
