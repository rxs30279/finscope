"use client";

import { useState } from "react";

// "more"/"less" toggle for the company description. Collapsed, it shows the first
// ~300 chars followed by a "…more" unit glued right after the text; expanded, the
// full text with an inline "less". The full description is truncated out of the
// collapsed DOM, so it's carried in the company JSON-LD (see CompanyHeader) to
// stay crawlable.
const CLAMP = 300;

const textStyle: React.CSSProperties = {
  color: "#94a3b8",
  fontSize: 13,
  lineHeight: 1.7,
  margin: 0,
  maxWidth: 820,
};

const linkStyle: React.CSSProperties = { color: "#a78bfa", cursor: "pointer" };

export default function ExpandableText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > CLAMP;

  if (isLong && !expanded) {
    // Cut back to the last whole word so we don't slice mid-word before "…more".
    const slice = text.slice(0, CLAMP).replace(/\s+\S*$/, "");
    return (
      <p style={textStyle}>
        {slice}
        <span
          onClick={() => setExpanded(true)}
          style={{ ...linkStyle, whiteSpace: "nowrap" }}
        >
          …more
        </span>
      </p>
    );
  }

  return (
    <p style={textStyle}>
      {text}
      {isLong && (
        <span onClick={() => setExpanded(false)} style={{ ...linkStyle, marginLeft: 6 }}>
          less
        </span>
      )}
    </p>
  );
}
