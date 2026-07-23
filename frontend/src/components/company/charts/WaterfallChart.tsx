"use client";

import {
  BarChart, Bar, Cell, LabelList, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer,
} from "recharts";
import { fmt } from "@/lib/format";
import { S } from "@/lib/theme";

// The waterfall's category labels ("Cost of Revenue", "Other Expenses", …) are
// too wide to sit horizontally on mobile without overlapping. Rather than rotate
// them, wrap multi-word labels onto two lines (split at the midpoint word) so
// they stay horizontal. A custom tick is needed because Recharts ticks are
// single-line by default.
const WrapTick = ({ x, y, payload }: any) => {
  const words = String(payload?.value ?? "").split(" ");
  const mid = Math.ceil(words.length / 2);
  const lines = words.length <= 1 ? words : [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
  return (
    <text x={x} y={y} textAnchor="middle" fill="#cbd5e1" fontSize={11} fontFamily="monospace">
      {lines.map((ln, i) => (
        <tspan key={i} x={x} dy={12}>{ln}</tspan>
      ))}
    </text>
  );
};

interface WaterfallItem {
  name: string;
  range: number[];
  amount: number;
  fill: string;
}

interface Props {
  data: WaterfallItem[];
  domain?: [number, number];
  fcur: string;
  isMobile: boolean;
}

export default function WaterfallChart({ data, domain, fcur, isMobile }: Props) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 24, right: 10, bottom: 5, left: 4 }} barCategoryGap="12%">
        <XAxis dataKey="name" tick={isMobile ? <WrapTick /> : { fontSize: 12, fill: "#cbd5e1" }} interval={0} tickLine={false} axisLine={{ stroke: "#334155" }} {...(isMobile ? { height: 48 } : {})} />
        <YAxis hide domain={domain} />
        <Tooltip
          cursor={{ fill: "#ffffff08" }}
          contentStyle={S.tooltip}
          itemStyle={{ color: "#e5e7eb" }}
          formatter={(_v: any, _n: any, p: any) => [fmt(p?.payload?.amount, "currency", fcur), p?.payload?.name]}
          labelFormatter={() => ""}
        />
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
        <Bar dataKey="range" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
          <LabelList
            dataKey="amount"
            content={(props: any) => {
              const { x, y, width, height, value } = props;
              // A loss bar hangs below zero and recharts reports it with
              // a negative height (y is the bottom edge), so derive the
              // top edge explicitly and always sit the label just above
              // it — on top of the bar, never inside. Colour the loss red.
              const neg = value < 0;
              const top = Math.min(y, y + height);
              return (
                <text x={x + width / 2} y={top - 6} textAnchor="middle" fill={neg ? "#f87171" : "#e5e7eb"} fontSize={12} fontFamily="monospace">
                  {fmt(value, "currency", fcur)}
                </text>
              );
            }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
