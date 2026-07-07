"""Build a visually-rich HTML edition of the user manual, then render it to PDF.

USER_MANUAL.md remains the single source of truth. This script renders it to a
styled, self-contained HTML file (Alpha_Move_AI_User_Manual.html) and then prints
that to PDF (Alpha_Move_AI_User_Manual.pdf) with footer page numbers.

It replaces the old Word/.docx pipeline (build_manual.py): we no longer build a
.docx at all. The HTML is laid out with print CSS (A4 @page rules, page breaks
before each numbered section, "avoid break inside" on tables / callouts / images)
so it reads like a proper manual on screen and on paper.

Images are base64-embedded so the HTML is a single portable file and the PDF
renderer needs no file access.

Rendering engine (in order of preference):
  1. Playwright driving the installed Microsoft Edge (channel="msedge"). This is
     the only path that gives a real "Page X of Y" footer, via Playwright's
     header/footer template. No Chromium download is needed.
  2. Microsoft Edge headless --print-to-pdf (no footer page numbers — Chromium's
     CLI cannot inject them; we warn if we fall back to this).

Usage:
    python build_manual_html.py             # md -> html -> pdf
    python build_manual_html.py --html-only # stop at the HTML
"""

import base64
import html as _html
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote

_ROOT = os.path.dirname(os.path.abspath(__file__))
_MD = os.path.join(_ROOT, "USER_MANUAL.md")
_HTML = os.path.join(_ROOT, "Alpha_Move_AI_User_Manual.html")
_PDF = os.path.join(_ROOT, "Alpha_Move_AI_User_Manual.pdf")
_COVER = os.path.join(_ROOT, "manual_assets", "cover.png")

# ── Markdown parsing (only the constructs the hand-written manual uses) ────────

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
_IMAGE = re.compile(r"^!\[([^\]]*)\]\((.+)\)\s*$")


def parse_blocks(lines):
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if stripped == "":
            i += 1
            continue
        if stripped == "---":
            blocks.append(("hr", None))
            i += 1
            continue
        im = _IMAGE.match(stripped)
        if im:
            blocks.append(("image", (im.group(1).strip(), im.group(2).strip())))
            i += 1
            continue
        m = _HEADING.match(raw)
        if m:
            blocks.append(("heading", (len(m.group(1)), m.group(2).strip())))
            i += 1
            continue
        if stripped.startswith("```"):
            code = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", code))
            continue
        if stripped.startswith(">"):
            inner = []
            while i < n and lines[i].lstrip().startswith(">"):
                t = lines[i].lstrip()[1:]
                if t.startswith(" "):
                    t = t[1:]
                inner.append(t)
                i += 1
            blocks.append(("quote", parse_blocks(inner)))
            continue
        if "|" in raw and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            header = _split_row(raw)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(("table", (header, rows)))
            continue
        if _BULLET.match(raw) or _NUMBERED.match(raw):
            items = []
            while i < n:
                bm = _BULLET.match(lines[i])
                nm = _NUMBERED.match(lines[i])
                if bm:
                    items.append((len(bm.group(1)) // 2, None, bm.group(2).strip()))
                    i += 1
                elif nm:
                    items.append((len(nm.group(1)) // 2, nm.group(2), nm.group(3).strip()))
                    i += 1
                else:
                    break
            blocks.append(("list", items))
            continue
        para = [stripped]
        i += 1
        while i < n:
            nxt = lines[i]
            ns = nxt.strip()
            if ns == "" or ns == "---" or nxt.lstrip().startswith(">"):
                break
            if _HEADING.match(nxt) or ns.startswith("```"):
                break
            if _BULLET.match(nxt) or _NUMBERED.match(nxt):
                break
            if "|" in nxt and "|" in lines[i - 1]:
                break
            para.append(ns)
            i += 1
        blocks.append(("paragraph", " ".join(para)))
    return blocks


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


# ── Inline formatting → HTML ──────────────────────────────────────────────────

_INLINE = re.compile(
    r"(\*\*.+?\*\*"
    r"|\*[^*]+?\*"
    r"|`[^`]+?`"
    r"|\[[^\]]+?\]\([^)]+?\))"
)


def esc(t):
    return _html.escape(t, quote=False)


def inline_html(text):
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(esc(text[pos:m.start()]))
        tok = m.group(0)
        if tok.startswith("**"):
            out.append("<strong>" + esc(tok[2:-2]) + "</strong>")
        elif tok.startswith("`"):
            out.append("<code>" + esc(tok[1:-1]) + "</code>")
        elif tok.startswith("*"):
            out.append("<em>" + esc(tok[1:-1]) + "</em>")
        else:
            lm = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
            label, href = lm.group(1), lm.group(2)
            href_attr = _html.escape(href, quote=True)
            out.append(f'<a href="{href_attr}">{esc(label)}</a>')
        pos = m.end()
    if pos < len(text):
        out.append(esc(text[pos:]))
    return "".join(out)


# ── GitHub-style heading slugs (so the manual's #anchors resolve) ─────────────

def slug(text):
    s = text.lower()
    s = re.sub(r"[^a-z0-9 \-]", "", s)
    return s.replace(" ", "-")


def collect_anchor_aliases(blocks):
    """Map every #anchor referenced in the doc to the heading id it belongs to.

    The manual's TOC uses hand-shortened anchors (e.g. #11-how-to-find-investment
    -leads) that are a prefix of the full heading slug. We register those as alias
    ids on the matching heading so the internal links work."""
    referenced = set(re.findall(r"\]\(#([^)]+)\)", "\n".join(_raw_text(blocks))))
    headings = []

    def walk(bs):
        for kind, payload in bs:
            if kind == "heading":
                headings.append(slug(payload[1]))
            elif kind == "quote":
                walk(payload)
    walk(blocks)

    aliases = {}  # heading_slug -> list of alias ids
    for anchor in referenced:
        if anchor in headings:
            continue
        for hslug in headings:
            if hslug.startswith(anchor):
                aliases.setdefault(hslug, []).append(anchor)
                break
    return aliases


def _raw_text(blocks):
    out = []
    for kind, payload in blocks:
        if kind == "paragraph":
            out.append(payload)
        elif kind == "heading":
            out.append(payload[1])
        elif kind == "list":
            out.extend(t for _, _, t in payload)
        elif kind == "table":
            out.extend(payload[0])
            for r in payload[1]:
                out.extend(r)
        elif kind == "quote":
            out.extend(_raw_text(payload))
    return out


# ── Block rendering → HTML ────────────────────────────────────────────────────

def render_list(items):
    out, stack = [], []  # stack of (tag, level)

    def close_to(level):
        while stack and stack[-1][1] > level:
            out.append("</%s>" % stack.pop()[0])

    for level, number, text in items:
        tag = "ol" if number else "ul"
        if not stack or level > stack[-1][1]:
            out.append("<%s>" % tag)
            stack.append((tag, level))
        elif level < stack[-1][1]:
            close_to(level)
        if stack and stack[-1][1] == level and stack[-1][0] != tag:
            out.append("</%s>" % stack.pop()[0])
            out.append("<%s>" % tag)
            stack.append((tag, level))
        out.append("<li>" + inline_html(text) + "</li>")
    while stack:
        out.append("</%s>" % stack.pop()[0])
    return "".join(out)


def render_table(header, rows):
    out = ['<table><thead><tr>']
    for h in header:
        out.append("<th>" + inline_html(h) + "</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for ci in range(len(header)):
            out.append("<td>" + inline_html(row[ci] if ci < len(row) else "") + "</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


_IMG_CACHE = {}


def data_uri(path):
    if path in _IMG_CACHE:
        return _IMG_CACHE[path]
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    uri = f"data:{mime};base64,{b64}"
    _IMG_CACHE[path] = uri
    return uri


def render_image(alt, rel_path):
    rel_path = unquote(rel_path)
    path = rel_path if os.path.isabs(rel_path) else os.path.join(_ROOT, rel_path)
    if not os.path.isfile(path):
        print(f"WARNING: image not found at {path}; skipping.")
        return ""
    cap = f'<figcaption>{inline_html(alt)}</figcaption>' if alt else ""
    return f'<figure><img src="{data_uri(path)}" alt="{_html.escape(alt, quote=True)}">{cap}</figure>'


def render_quote(inner_blocks):
    body = render_blocks(inner_blocks, top_level=False)
    klass = "callout"
    flat = " ".join(_raw_text(inner_blocks)).lower()
    if "under the hood" in flat:
        klass += " uth"
    elif "disclaimer" in flat or "important" in flat:
        klass += " warn"
    else:
        klass += " note"
    return f'<div class="{klass}">{body}</div>'


def render_blocks(blocks, *, top_level=False, aliases=None):
    aliases = aliases or {}
    out = []
    skip_next_list = False
    in_toc = False
    for kind, payload in blocks:
        if kind == "heading":
            level, text = payload
            hid = slug(text)
            alias_spans = "".join(f'<span id="{a}"></span>' for a in aliases.get(hid, []))
            if top_level and text.lower() == "table of contents":
                out.append('<section class="toc">')
                out.append(f'<h2 id="{hid}">{alias_spans}{inline_html(text)}</h2>')
                in_toc = True
                continue
            cls = ""
            if top_level and level == 2:
                cls = ' class="section-start"'
            out.append(f"<h{level} id=\"{hid}\"{cls}>{alias_spans}{inline_html(text)}</h{level}>")
        elif kind == "paragraph":
            out.append("<p>" + inline_html(payload) + "</p>")
        elif kind == "list":
            if skip_next_list:
                skip_next_list = False
                continue
            out.append(render_list(payload))
            if in_toc:
                out.append("</section>")
                in_toc = False
        elif kind == "table":
            out.append('<div class="table-wrap">' + render_table(payload[0], payload[1]) + "</div>")
        elif kind == "code":
            out.append("<pre><code>" + esc("\n".join(payload)) + "</code></pre>")
        elif kind == "image":
            out.append(render_image(payload[0], payload[1]))
        elif kind == "quote":
            out.append(render_quote(payload))
        elif kind == "hr":
            out.append('<hr class="rule">')
    return "".join(out)


# ── Cover + document assembly ─────────────────────────────────────────────────

CSS = r"""
:root{
  --ink:#1d2430; --muted:#5b6675; --line:#e2e6ec; --soft:#f6f8fb;
  --accent:#e8762b;        /* brand orange */
  --accent2:#7c5cff;       /* brand purple */
  --navy:#16263d;
  --code:#b1184b;
}
*{box-sizing:border-box;}
html{-webkit-print-color-adjust:exact; print-color-adjust:exact;}
body{
  font-family:"Segoe UI","Helvetica Neue",Arial,sans-serif;
  color:var(--ink); font-size:10.6pt; line-height:1.55; margin:0;
  background:#fff;
}
.page{max-width:760px; margin:0 auto; padding:0 6px;}

h1,h2,h3,h4{color:var(--navy); line-height:1.25; font-weight:700;
  break-after:avoid; page-break-after:avoid;}
h2{font-size:18pt; margin:0 0 .5em; padding-bottom:.28em;
  border-bottom:2px solid var(--accent);}
h2.section-start{break-before:page; page-break-before:always; padding-top:2pt;}
h3{font-size:13.2pt; margin:1.4em 0 .45em; padding-left:10px;
  border-left:4px solid var(--accent2);}
h4{font-size:11.4pt; margin:1.15em 0 .35em; color:var(--accent2);
  text-transform:none; letter-spacing:.2px;}
p{margin:.5em 0;}
a{color:#1f63c8; text-decoration:none;}
a:hover{text-decoration:underline;}
strong{color:#0f1722;}
code{font-family:"Cascadia Code",Consolas,"Courier New",monospace;
  font-size:.9em; color:var(--code); background:#f4f1f3;
  padding:.04em .32em; border-radius:3px;}
pre{background:#f5f6f8; border:1px solid var(--line); border-left:3px solid var(--accent2);
  border-radius:5px; padding:11px 14px; overflow:auto; break-inside:avoid; page-break-inside:avoid;}
pre code{background:none; color:#243; padding:0; font-size:.86em; line-height:1.5;}

hr.rule{border:0; border-top:1px solid var(--line); margin:1.4em 0;}

/* Tables — horizontal rules only, for a cleaner, more modern read */
.table-wrap{break-inside:auto;}
table{width:100%; border-collapse:collapse; margin:.7em 0 1em; font-size:9.6pt;}
th,td{border:0; border-bottom:1px solid var(--line); padding:6px 10px;
  text-align:left; vertical-align:top;}
thead th{background:var(--navy); color:#fff; font-weight:600;
  border-bottom:2px solid var(--accent);}
thead th:first-child{border-radius:4px 0 0 0;}
thead th:last-child{border-radius:0 4px 0 0;}
tbody tr:nth-child(even){background:var(--soft);}
td code,th code{font-size:.86em;}

/* Lists */
ul,ol{margin:.45em 0 .7em; padding-left:1.5em;}
li{margin:.18em 0;}
li>ul,li>ol{margin:.2em 0;}

/* Callout boxes */
.callout{border-radius:6px; padding:11px 15px; margin:1em 0;
  break-inside:avoid; page-break-inside:avoid; font-size:9.9pt;}
.callout p:first-child{margin-top:0;}
.callout p:last-child{margin-bottom:0;}
.callout.note{background:#eef4ff; border:1px solid #d3e1fb; border-left:4px solid #3b82f6;}
.callout.warn{background:#fff5ec; border:1px solid #ffd9b8; border-left:4px solid var(--accent);}
.callout.uth{background:#f3f4f8; border:1px solid #dfe2ec; border-left:4px solid var(--accent2);}
/* The bold lead-in ("Under the hood — …", "Tip:", "Important…") becomes a
   coloured heading line, so each box reads like a titled panel. */
.callout>p:first-child>strong:first-child{display:block; font-size:10.2pt;
  margin-bottom:.3em; letter-spacing:.2px;}
.callout.note>p:first-child>strong:first-child{color:#1d4ed8;}
.callout.warn>p:first-child>strong:first-child{color:#c2540a;}
.callout.uth>p:first-child>strong:first-child{color:var(--accent2);}
.callout table{margin:.5em 0;}

/* Figures */
figure{margin:1.1em 0; text-align:center; break-inside:avoid; page-break-inside:avoid;}
figure img{max-width:100%; border:1px solid var(--line); border-radius:6px;
  box-shadow:0 2px 10px rgba(20,38,61,.10);}
figcaption{color:var(--muted); font-style:italic; font-size:8.8pt; margin-top:.5em;}

/* Cover */
.cover{height:100vh; min-height:960px; display:flex; flex-direction:column;
  align-items:center; justify-content:center; text-align:center;
  break-after:page; page-break-after:always; padding:0 20px;}
.cover .kicker{color:var(--accent); font-weight:700; letter-spacing:3px;
  text-transform:uppercase; font-size:11pt; margin-bottom:6px;}
.cover h1{font-size:30pt; color:var(--navy); margin:.1em 0 .15em; line-height:1.15; border:0;}
.cover .sub{color:var(--muted); font-size:12.5pt; max-width:540px; margin:.4em auto 0;}
.cover img{width:300px; max-width:62%; margin:30px auto; border-radius:14px;
  box-shadow:0 10px 30px rgba(20,38,61,.18);}
.cover .meta{margin-top:26px; font-size:10pt; color:var(--ink);}
.cover .meta div{margin:3px 0;}
.cover .rulebar{width:90px; height:4px; background:var(--accent); border-radius:2px; margin:18px auto;}

/* Intro note under cover */
.about{background:#f3f4f8; border:1px solid #dfe2ec; border-left:4px solid var(--accent2);
  border-radius:6px; padding:13px 16px; margin:0 0 1.2em; font-size:9.9pt;}

/* Table of contents — two columns so it fits one page and scans faster */
section.toc{break-after:page; page-break-after:always;}
section.toc h2{border-bottom:2px solid var(--accent);}
section.toc>ol{column-count:2; column-gap:32px;}
section.toc ol{list-style:decimal; padding-left:1.7em; font-size:10pt;}
section.toc ol li::marker{color:var(--accent); font-weight:700;}
section.toc ul{list-style:none; padding-left:1.4em; font-size:9.4pt; color:var(--muted);}
section.toc li{margin:.3em 0;}
section.toc a{color:var(--ink);}
section.toc a:hover{color:var(--accent);}

@page{
  size:A4;
  margin:18mm 15mm 20mm 15mm;
}
"""


def build_html(md_path):
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks = parse_blocks(lines)
    aliases = collect_anchor_aliases(blocks)

    # Pull the cover material off the front: the H1 title, the bold metadata
    # paragraphs, and the "About the Under the hood boxes" note, up to the first
    # horizontal rule.
    title = "Alpha Move AI — User Manual"
    cover_meta = []
    about_block = None
    body_start = 0
    if blocks and blocks[0][0] == "heading" and blocks[0][1][0] == 1:
        title = blocks[0][1][1]
        i = 1
        while i < len(blocks) and blocks[i][0] != "hr":
            kind, payload = blocks[i]
            if kind == "paragraph":
                cover_meta.append(payload)
            elif kind == "quote":
                about_block = payload
            i += 1
        body_start = i + 1  # skip the hr

    # Split the title on the em dash for a cleaner cover.
    parts = [p.strip() for p in re.split(r"\s+[—-]\s+", title)]
    head = parts[0] if parts else title
    tail = " — ".join(parts[1:]) if len(parts) > 1 else ""

    cover_img = f'<img src="{data_uri(_COVER)}" alt="cover">' if os.path.isfile(_COVER) else ""
    meta_html = "".join(f"<div>{inline_html(m)}</div>" for m in cover_meta)

    cover = f"""
<section class="cover">
  <div class="kicker">User Manual</div>
  <h1>{esc(head)}</h1>
  {f'<div class="sub">{esc(tail)}</div>' if tail else ''}
  <div class="rulebar"></div>
  {cover_img}
  <div class="meta">{meta_html}</div>
</section>
"""

    about_html = ""
    if about_block:
        about_html = f'<div class="about">{render_blocks(about_block)}</div>'

    body = render_blocks(blocks[body_start:], top_level=True, aliases=aliases)

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
{cover}
<main class="page">
{about_html}
{body}
</main>
</body>
</html>
"""
    with open(_HTML, "w", encoding="utf-8") as f:
        f.write(doc)
    return _HTML


# ── PDF rendering ─────────────────────────────────────────────────────────────

_PLAYWRIGHT_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [htmlPath, pdfPath] = process.argv.slice(2);
  const url = 'file:///' + htmlPath.replace(/\\/g, '/');
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'load' });
  // networkidle fires almost immediately for a file:// page — wait until the
  // webfonts are loaded and every embedded base64 image has actually decoded,
  // otherwise page.pdf() races layout and emits a silently truncated document
  // (observed: 37 of 69 pages, cut mid-manual).
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images).map((img) => img.decode().catch(() => {}))
    );
  });
  await page.waitForTimeout(500);
  const footer = `<div style="width:100%; font-family:'Segoe UI',Arial,sans-serif;
      font-size:8px; color:#8a93a1; padding:0 15mm; display:flex;
      justify-content:space-between;">
      <span>Alpha Move AI — UK Stock Screener</span>
      <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
    </div>`;
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: footer,
    margin: { top: '18mm', bottom: '20mm', left: '15mm', right: '15mm' },
  });
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


# A silently truncated render (see the decode-wait comment in the Playwright
# script) once cut the manual from 69 pages to 37 with exit code 0. Any output
# below this floor is treated as a failed render, never returned as success.
_MIN_PAGES = 50


def _pdf_page_count(path):
    """Page count via pypdfium2, or None if it isn't importable."""
    try:
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(path))
    except Exception:
        return None


def _looks_complete(pdf_path):
    n = _pdf_page_count(pdf_path)
    if n is None:
        print("  (pypdfium2 not available — skipping page-count sanity check)")
        return True
    if n < _MIN_PAGES:
        print(f"  Render sanity check FAILED: {n} pages < floor of {_MIN_PAGES}.")
        return False
    print(f"  Render sanity check passed: {n} pages.")
    return True


def export_pdf(html_path, pdf_path):
    for attempt in (1, 2):
        if _export_pdf_playwright(html_path, pdf_path) and _looks_complete(pdf_path):
            return "Playwright + Microsoft Edge (with page numbers)"
        print(f"  Playwright attempt {attempt} did not produce a complete PDF.")
    if _export_pdf_edge(html_path, pdf_path) and _looks_complete(pdf_path):
        return "Microsoft Edge --print-to-pdf (WARNING: no footer page numbers)"
    raise RuntimeError(
        "Could not render a complete PDF. Install Playwright (`npm i playwright`) "
        "so the page-numbered footer works, or ensure Microsoft Edge is installed."
    )


def _node_has_playwright():
    try:
        r = subprocess.run(
            ["node", "-e", "require.resolve('playwright')"],
            cwd=_ROOT, capture_output=True, text=True,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _export_pdf_playwright(html_path, pdf_path):
    if not _node_has_playwright():
        print("Playwright not found for Node; trying to install it (no browser download)…")
        env = dict(os.environ, PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1")
        try:
            subprocess.run(["npm", "install", "playwright", "--no-save"],
                           cwd=_ROOT, env=env, check=True, shell=(os.name == "nt"))
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"  npm install playwright failed ({exc}).")
            return False
        if not _node_has_playwright():
            return False
    script = os.path.join(_ROOT, "_render_pdf.js")
    with open(script, "w", encoding="utf-8") as f:
        f.write(_PLAYWRIGHT_SCRIPT)
    try:
        subprocess.run(["node", script, html_path, pdf_path],
                       cwd=_ROOT, check=True, shell=(os.name == "nt"))
        return os.path.isfile(pdf_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"  Playwright render failed ({exc}).")
        return False
    finally:
        if os.path.isfile(script):
            os.remove(script)


def _find_edge():
    for p in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if os.path.isfile(p):
            return p
    return shutil.which("msedge")


def _export_pdf_edge(html_path, pdf_path):
    edge = _find_edge()
    if not edge:
        return False
    url = "file:///" + html_path.replace("\\", "/")
    subprocess.run([
        edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}", url,
    ], check=True)
    return os.path.isfile(pdf_path)


def main():
    html_only = "--html-only" in sys.argv
    if not os.path.isfile(_MD):
        print(f"Source not found: {_MD}")
        sys.exit(1)
    build_html(_MD)
    size = os.path.getsize(_HTML)
    print(f"Built {os.path.basename(_HTML)} ({size:,} bytes) from USER_MANUAL.md.")
    if html_only:
        return
    engine = export_pdf(_HTML, _PDF)
    psize = os.path.getsize(_PDF)
    print(f"Built {os.path.basename(_PDF)} ({psize:,} bytes) via {engine}.")


if __name__ == "__main__":
    main()
