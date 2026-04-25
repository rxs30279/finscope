"""Company news: Google News RSS aggregator + combined feed with RNS.

- Google News RSS is free, no API key, no quota. Query format:
  https://news.google.com/rss/search?q=...&hl=en-GB&gl=UK&ceid=UK:en
- Results cached in `company_news` table with a 24h TTL per symbol so repeat
  page visits serve from DB.
- `GET /api/news/{symbol}` returns { rns: [...], google: [...] } — both lists
  limited to the last 6 months, newest first. RNS rows come from the existing
  `rns_announcements` table (no fetch, no scraping).
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hashlib
import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, HTTPException, Query
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/news", tags=["news"])

_USER_AGENT = "Mozilla/5.0 (compatible; UKStockScreener/1.0)"
_CACHE_TTL_HOURS = 24
_HISTORY_MONTHS = 6
_SUMMARY_LOOKBACK_DAYS = 60

_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        if not _DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
        from openai import OpenAI
        _llm_client = OpenAI(api_key=_DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)
    return _llm_client


# ── DB ────────────────────────────────────────────────────────────────────────

_DB_CONFIG = {
    "dbname":   os.environ.get("DB_NAME", "postgres"),
    "user":     os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host":     os.environ.get("DB_HOST", ""),
    "port":     os.environ.get("DB_PORT", "5432"),
    "sslmode":  "require",
}

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **_DB_CONFIG)
    return _pool


def _query(sql, params=None, fetch=True):
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        if not fetch:
            return None
        return [dict(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def _ensure_schema():
    """Create the news tables on first use (idempotent)."""
    _query("""
        CREATE TABLE IF NOT EXISTS company_news (
            id            TEXT PRIMARY KEY,
            symbol        TEXT NOT NULL,
            title         TEXT NOT NULL,
            link          TEXT NOT NULL,
            source        TEXT,
            published_at  TIMESTAMPTZ,
            fetched_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """, fetch=False)
    _query("""
        CREATE INDEX IF NOT EXISTS idx_company_news_symbol_pub
        ON company_news(symbol, published_at DESC)
    """, fetch=False)
    _query("""
        CREATE TABLE IF NOT EXISTS company_news_summary (
            symbol       TEXT PRIMARY KEY,
            summary      TEXT NOT NULL,
            themes       JSONB,
            outlook      TEXT,
            rns_count    INT,
            google_count INT,
            model        TEXT,
            generated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, fetch=False)


# ── Google News RSS ───────────────────────────────────────────────────────────

def _build_query(name: str, symbol: str) -> str:
    # Quoted name is the most reliable. Bare ticker adds false positives on
    # common words (e.g. BP., III.).
    return f'"{name}"'


def _google_news_url(query: str) -> str:
    qs = urllib.parse.urlencode({
        "q":    query,
        "hl":   "en-GB",
        "gl":   "UK",
        "ceid": "UK:en",
    })
    return f"https://news.google.com/rss/search?{qs}"


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Parse Google News RSS into a list of {title, link, source, published_at}."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title  = (item.findtext("title")  or "").strip()
        link   = (item.findtext("link")   or "").strip()
        pubraw = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None and source_el.text else ""
        try:
            pub = parsedate_to_datetime(pubraw) if pubraw else None
            if pub and pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pub = None
        if not title or not link:
            continue
        items.append({
            "title":        title,
            "link":         link,
            "source":       source,
            "published_at": pub,
        })
    return items


def _fetch_google_news(name: str, symbol: str, timeout: int = 20) -> list[dict]:
    url = _google_news_url(_build_query(name, symbol))
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError):
        return []
    return _parse_rss(data)


def _row_id(symbol: str, link: str) -> str:
    h = hashlib.sha1(f"{symbol}|{link}".encode("utf-8")).hexdigest()
    return h[:32]


def _upsert_news(symbol: str, items: list[dict]) -> int:
    if not items:
        return 0
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        inserted = 0
        for it in items:
            cur.execute("""
                INSERT INTO company_news (id, symbol, title, link, source, published_at, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE
                    SET fetched_at = NOW(),
                        title      = EXCLUDED.title,
                        source     = EXCLUDED.source
            """, (
                _row_id(symbol, it["link"]),
                symbol, it["title"], it["link"], it["source"], it["published_at"],
            ))
            inserted += cur.rowcount
        return inserted
    finally:
        pool.putconn(conn)


# ── Cache + merged endpoint ───────────────────────────────────────────────────

def _cache_is_fresh(symbol: str) -> bool:
    rows = _query("""
        SELECT MAX(fetched_at) AS last
        FROM company_news
        WHERE symbol = %s
    """, (symbol,))
    last = rows[0]["last"] if rows else None
    if not last:
        return False
    age = datetime.now(timezone.utc) - last
    return age < timedelta(hours=_CACHE_TTL_HOURS)


def _load_google(symbol: str) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=_HISTORY_MONTHS * 30)
    return _query("""
        SELECT id, title, link, source, published_at
        FROM company_news
        WHERE symbol = %s
          AND (published_at IS NULL OR published_at >= %s)
        ORDER BY published_at DESC NULLS LAST
        LIMIT 80
    """, (symbol, since))


def _load_rns(symbol: str) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=_HISTORY_MONTHS * 30)
    return _query("""
        SELECT id, published_at, wire, headline, url, tier, category, score,
               llm_score, llm_thesis, llm_action, llm_risks
        FROM rns_announcements
        WHERE symbol = %s
          AND published_at >= %s
        ORDER BY published_at DESC
        LIMIT 200
    """, (symbol, since))


def _get_company_name(symbol: str) -> str | None:
    rows = _query("SELECT name FROM company_metadata WHERE symbol = %s", (symbol,))
    return rows[0]["name"] if rows else None


# ── DeepSeek summariser ───────────────────────────────────────────────────────

def _load_summary(symbol: str) -> dict | None:
    rows = _query("""
        SELECT summary, themes, outlook, rns_count, google_count, model, generated_at
        FROM company_news_summary
        WHERE symbol = %s
    """, (symbol,))
    return rows[0] if rows else None


def _save_summary(symbol: str, result: dict, rns_n: int, google_n: int) -> None:
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO company_news_summary
                (symbol, summary, themes, outlook, rns_count, google_count, model, generated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                summary      = EXCLUDED.summary,
                themes       = EXCLUDED.themes,
                outlook      = EXCLUDED.outlook,
                rns_count    = EXCLUDED.rns_count,
                google_count = EXCLUDED.google_count,
                model        = EXCLUDED.model,
                generated_at = NOW()
        """, (
            symbol,
            (result.get("summary") or "")[:2000],
            json.dumps(result.get("themes") or []),
            (result.get("outlook") or "")[:1000],
            rns_n, google_n,
            _DEEPSEEK_MODEL,
        ))
    finally:
        pool.putconn(conn)


def _build_summary_messages(name: str, symbol: str, rns: list[dict], google: list[dict]) -> list[dict]:
    system = (
        "You are a UK equity analyst. Summarise the last 60 days of news for one "
        "company — combining regulatory announcements (RNS) with press "
        "coverage. Focus on what actually changed the investment case: "
        "earnings, guidance, M&A, management, strategy, regulatory, legal. "
        "Ignore routine TR-1 / holding notifications, director share dealings "
        "under £100k, and boilerplate press that just rehashes prior news. "
        "Return STRICT JSON only."
    )

    def fmt_date(v):
        if v is None: return "?"
        if isinstance(v, str): return v[:10]
        try: return v.strftime("%Y-%m-%d")
        except Exception: return str(v)[:10]

    rns_lines = "\n".join(
        f"  - {fmt_date(r.get('published_at'))}  [{r.get('tier') or '?'}] "
        f"{(r.get('category') or '').replace('_',' ')}: {r.get('headline') or ''}"
        f"{' — ' + r['llm_thesis'] if r.get('llm_thesis') else ''}"
        for r in rns
    ) or "  (none)"

    google_lines = "\n".join(
        f"  - {fmt_date(g.get('published_at'))}  {g.get('source') or '?'}: {g.get('title') or ''}"
        for g in google
    ) or "  (none)"

    user = f"""Company: {name} ({symbol})
Window: last 60 days

Regulatory (RNS) announcements
{rns_lines}

Press / Google News headlines
{google_lines}

Produce a JSON object with exactly these fields:
  summary   string: 2-3 sentences, plain English, the single biggest takeaway from the last 60 days
  themes    array of 3-5 objects, each: {{title: short phrase, detail: one sentence}}
  outlook   string: one sentence on what to watch next (catalysts, upcoming events, open questions)

Return JSON only — no preamble, no code fence."""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


def _call_summariser(messages: list[dict]) -> dict:
    client = _get_llm_client()
    resp = client.chat.completions.create(
        model=_DEEPSEEK_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=700,
    )
    return json.loads(resp.choices[0].message.content)


def _generate_summary(symbol: str) -> dict:
    name = _get_company_name(symbol)
    if not name:
        raise HTTPException(404, f"Unknown symbol {symbol}")

    since = datetime.now(timezone.utc) - timedelta(days=_SUMMARY_LOOKBACK_DAYS)
    rns = _query("""
        SELECT published_at, tier, category, headline, llm_thesis
        FROM rns_announcements
        WHERE symbol = %s
          AND published_at >= %s
        ORDER BY published_at DESC
        LIMIT 60
    """, (symbol, since))
    google = _query("""
        SELECT published_at, source, title
        FROM company_news
        WHERE symbol = %s
          AND (published_at IS NULL OR published_at >= %s)
        ORDER BY published_at DESC NULLS LAST
        LIMIT 40
    """, (symbol, since))

    if not rns and not google:
        raise HTTPException(400, "No news in the last 60 days to summarise")

    messages = _build_summary_messages(name, symbol, rns, google)
    result = _call_summariser(messages)
    _save_summary(symbol, result, len(rns), len(google))

    return {
        "symbol":       symbol,
        "summary":      result.get("summary"),
        "themes":       result.get("themes"),
        "outlook":      result.get("outlook"),
        "rns_count":    len(rns),
        "google_count": len(google),
        "model":        _DEEPSEEK_MODEL,
        "generated_at": datetime.now(timezone.utc),
    }


@router.post("/{symbol}/summary")
def generate_summary(symbol: str):
    """Call DeepSeek to summarise the last 60 days of news for this company."""
    _ensure_schema()
    return _generate_summary(symbol)


@router.get("/{symbol}")
def get_company_news(symbol: str, refresh: bool = Query(False)):
    """Combined news feed for one symbol.

    Returns:
        { symbol, name, rns: [...], google: [...], google_fetched_at }

    Google News is fetched on first view (or when the cache is >24h old, or
    when refresh=true). RNS is read live from the rns_announcements table.
    """
    _ensure_schema()
    name = _get_company_name(symbol)
    if not name:
        raise HTTPException(404, f"Unknown symbol {symbol}")

    if refresh or not _cache_is_fresh(symbol):
        items = _fetch_google_news(name, symbol)
        _upsert_news(symbol, items)

    google = _load_google(symbol)
    rns    = _load_rns(symbol)
    last_rows = _query(
        "SELECT MAX(fetched_at) AS last FROM company_news WHERE symbol = %s",
        (symbol,),
    )
    last = last_rows[0]["last"] if last_rows else None

    return {
        "symbol":             symbol,
        "name":               name,
        "rns":                rns,
        "google":             google,
        "google_fetched_at":  last,
        "summary":            _load_summary(symbol),
    }
