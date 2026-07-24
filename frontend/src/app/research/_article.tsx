"use client";

import type { CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { colors } from "@/lib/theme";

// The rendered article — header (date/tags/title) + Markdown body with the
// site's prose styling. Shared between the public /research/[slug] page and
// the admin editor's preview mode, so "preview" is exactly what publishes.
export default function ArticleView({
  title,
  dateLabel,
  tags,
  body,
  // The public article page renders its own hero (title/date/tags over the
  // cover image), so it hides this built-in header. The admin preview keeps it
  // so "preview" still shows the full standalone article.
  showHeader = true,
}: {
  title: string;
  dateLabel: string;
  tags: string[];
  body: string;
  showHeader?: boolean;
}) {
  return (
    <article>
      {showHeader && (
        <>
          <div
            style={{
              fontFamily: "monospace",
              fontSize: 11,
              color: colors.textFaint,
              textTransform: "uppercase",
              letterSpacing: 0.5,
              marginBottom: 10,
              display: "flex",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <span>{dateLabel}</span>
            {tags?.map((t) => (
              <span key={t} style={{ color: colors.indigo }}>
                #{t}
              </span>
            ))}
          </div>
          <h1
            style={{
              fontFamily: "var(--font-mulish), var(--font-inter), sans-serif",
              fontSize: 32,
              fontWeight: 700,
              color: colors.white,
              margin: "0 0 24px",
              lineHeight: 1.2,
            }}
          >
            {title}
          </h1>
        </>
      )}

      <div className="research-prose" style={proseStyle}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // A half-written image link (![]()), e.g. in a body saved mid-edit,
            // yields <img src=""> — React warns and the browser re-fetches the
            // page as the "image". Render nothing until the URL exists. (node
            // is react-markdown's AST handle — destructured away so it isn't
            // spread onto the DOM element.)
            img: ({ node: _node, ...props }) => (props.src ? <img {...props} /> : null),
            // A paragraph whose only content is a single link becomes a
            // prominent call-to-action button. Authors get a button just by
            // putting a bare `[label](url)` on its own line.
            p: ({ node, children, ...props }) => {
              const kids = (node?.children ?? []).filter(
                (c: { type?: string; value?: string }) =>
                  !(c.type === "text" && !(c.value ?? "").trim()),
              );
              const onlyLink =
                kids.length === 1 &&
                (kids[0] as { type?: string; tagName?: string }).type === "element" &&
                (kids[0] as { tagName?: string }).tagName === "a";
              return onlyLink ? (
                <p className="research-cta">{children}</p>
              ) : (
                <p {...props}>{children}</p>
              );
            },
          }}
        >
          {body}
        </ReactMarkdown>
      </div>

      {/* Prose styling for the markdown body — scoped to .research-prose so it
          can't leak into the rest of the app's monospace chrome. */}
      <style jsx global>{`
        .research-prose > :first-child { margin-top: 0; }
        .research-prose h2 {
          font-family: var(--font-mulish), sans-serif;
          font-size: 22px; color: ${colors.white};
          margin: 32px 0 12px; line-height: 1.3;
        }
        .research-prose h3 {
          font-family: var(--font-mulish), sans-serif;
          font-size: 18px; color: ${colors.white};
          margin: 24px 0 10px;
        }
        .research-prose p { margin: 0 0 16px; }
        .research-prose ul, .research-prose ol { margin: 0 0 16px; padding-left: 24px; }
        .research-prose li { margin: 4px 0; }
        .research-prose a {
          color: #b3bbff; font-weight: 600;
          text-decoration: underline; text-decoration-color: rgba(179, 187, 255, 0.5);
          text-underline-offset: 2px; transition: color 0.15s ease;
        }
        .research-prose a:hover { color: #d6dbff; text-decoration-color: #d6dbff; }
        /* Standalone-link paragraph → CTA button */
        .research-prose .research-cta { margin: 26px 0; }
        .research-prose .research-cta a {
          display: inline-flex; align-items: center; gap: 8px;
          font-family: var(--font-inter), sans-serif; font-weight: 700; font-size: 14px;
          color: #0a0a0a; background: linear-gradient(135deg, #a5aefc, #8b93f8);
          padding: 12px 22px; border-radius: 7px; text-decoration: none;
          box-shadow: 0 6px 22px rgba(129, 140, 248, 0.28); transition: filter 0.15s ease;
        }
        .research-prose .research-cta a:hover { filter: brightness(1.08); text-decoration: none; }
        .research-prose blockquote {
          border-left: 3px solid ${colors.accent};
          margin: 16px 0; padding: 4px 16px; color: ${colors.textMuted};
          background: ${colors.bgCardAlt};
        }
        .research-prose code {
          font-family: monospace; font-size: 0.9em;
          background: #1a1a1a; padding: 1px 5px; border-radius: 3px; color: ${colors.cyan};
        }
        .research-prose pre {
          background: #0d0d0d; border: 1px solid ${colors.border};
          border-radius: 4px; padding: 14px; overflow-x: auto; margin: 0 0 16px;
        }
        .research-prose pre code { background: none; padding: 0; color: ${colors.text}; }
        .research-prose img { max-width: 100%; height: auto; border-radius: 4px; }
        .research-prose hr { border: none; border-top: 1px solid ${colors.border}; margin: 28px 0; }
        .research-prose table {
          border-collapse: collapse; width: 100%; margin: 0 0 16px; font-size: 14px; display: block; overflow-x: auto;
        }
        .research-prose th, .research-prose td {
          border: 1px solid ${colors.border}; padding: 6px 10px; text-align: left;
        }
        .research-prose th { background: ${colors.bgCardAlt}; color: ${colors.accent}; }
      `}</style>
    </article>
  );
}

const proseStyle: CSSProperties = {
  fontFamily: "var(--font-inter), sans-serif",
  fontSize: 16,
  lineHeight: 1.7,
  color: colors.text,
};
