"use client";

import { useState } from "react";
import { S } from "@/lib/theme";

interface Props {
  selectMode: string;
  onSelectChange: (mode: string) => void;
  onCustomCommit: (v: number) => void;
  children: React.ReactNode;
  placeholder?: string;
  inputWidth?: number;
  active?: boolean;
}

export default function HybridSelect({
  selectMode,
  onSelectChange,
  onCustomCommit,
  children,
  placeholder,
  inputWidth = 80,
  active = false,
}: Props) {
  const [draft, setDraft] = useState("");
  const isCustom = selectMode === "custom";

  const commit = () => {
    const n = parseFloat(draft);
    if (!isNaN(n)) onCustomCommit(n);
  };

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <select
        style={{ ...S.select, ...(active ? S.selectActive : {}) }}
        value={selectMode}
        onChange={(e) => {
          setDraft("");
          onSelectChange(e.target.value);
        }}
      >
        {children}
        <option value="custom">Custom…</option>
      </select>
      {isCustom && (
        <input
          type="number"
          placeholder={placeholder}
          value={draft}
          style={{ ...S.select, width: inputWidth, padding: "8px 8px" }}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
          autoFocus
        />
      )}
    </div>
  );
}
