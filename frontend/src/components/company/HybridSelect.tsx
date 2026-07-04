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
  // Human label for a committed custom value (e.g. "FCF Mgn > 12%"). When
  // provided, a committed custom value shows as this labelled option instead of
  // the bare "Custom…", and the number input collapses. Omit to keep the legacy
  // behaviour (input stays visible, option reads "Custom…") — used by callers
  // like the market-cap filter that don't supply a label.
  customLabel?: string;
}

// Sentinel select value for "a custom value is committed and shown as a label".
// Distinct from "custom" (which means "the input is open") so that re-selecting
// the current committed option still fires onChange and reopens the input.
const COMMITTED = "__custom_committed__";

export default function HybridSelect({
  selectMode,
  onSelectChange,
  onCustomCommit,
  children,
  placeholder,
  inputWidth = 80,
  active = false,
  customLabel,
}: Props) {
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const isCustom = selectMode === "custom";
  // Show the committed label (instead of an open input) once a value is in and
  // we're not actively editing it.
  const showCommitted = isCustom && !editing && !!customLabel;
  const showInput = isCustom && !showCommitted;

  const commit = () => {
    const n = parseFloat(draft);
    if (!isNaN(n)) {
      onCustomCommit(n);
      setEditing(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
      <select
        style={{ ...S.select, ...(active ? S.selectActive : {}) }}
        value={showCommitted ? COMMITTED : selectMode}
        onChange={(e) => {
          const v = e.target.value;
          if (v === COMMITTED) return; // already the current value; no-op
          if (v === "custom") {
            setDraft("");
            setEditing(true);
          } else {
            setEditing(false);
          }
          onSelectChange(v);
        }}
      >
        {children}
        <option value="custom">Custom…</option>
        {showCommitted && <option value={COMMITTED}>{customLabel}</option>}
      </select>
      {showInput && (
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
