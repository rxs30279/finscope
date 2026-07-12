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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from dotenv import load_dotenv

from admin_auth import require_admin_token  # noqa: F401 (kept for the re-gate path on /{symbol}/summary)
from request_utils import client_ip as _client_ip

load_dotenv()

router = APIRouter(prefix="/api/news", tags=["news"])

_USER_AGENT = "Mozilla/5.0 (compatible; UKStockScreener/1.0)"
_CACHE_TTL_HOURS = 24
_HISTORY_MONTHS = 6
_SUMMARY_LOOKBACK_DAYS = 60
# The summary endpoint is public, so guard DeepSeek spend with a per-symbol
# cooldown: a regenerate within this many hours just re-serves the cached row.
_SUMMARY_COOLDOWN_HOURS = 24
# Plus a per-IP cap on *fresh* generations (cooldown-served hits don't count),
# so one client can't walk the whole universe and rack up spend in a day. Backed
# by the summary_rate_hits table so the cap is shared across workers.
_SUMMARY_RATE_LIMIT = 20
_SUMMARY_RATE_WINDOW_HOURS = 24
# Service-wide ceiling on fresh generations per window, since per-IP buckets can
# be diversified by forged proxy headers (see request_utils.client_ip). This is
# the hard bound on daily DeepSeek spend. Env-tunable without a redeploy.
_SUMMARY_GLOBAL_LIMIT = int(os.environ.get("SUMMARY_GLOBAL_RATE_LIMIT", "60"))

_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        if not _DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
        import httpx
        from openai import OpenAI
        # On Vercel this call fails with APIConnectionError ("Connection error.")
        # while the identical call works from Render. The difference is the
        # route: Vercel's serverless egress picks an IPv6 path to
        # api.deepseek.com that doesn't connect. Bind the outbound socket to an
        # IPv4 local address to force IPv4. Cap time/retries so a bad route fails
        # fast instead of hanging near the platform timeout.
        _llm_client = OpenAI(
            api_key=_DEEPSEEK_API_KEY,
            base_url=_DEEPSEEK_BASE_URL,
            timeout=40.0,
            max_retries=1,
            http_client=httpx.Client(
                timeout=40.0,
                transport=httpx.HTTPTransport(local_address="0.0.0.0"),
            ),
        )
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


_schema_ready = False


def _ensure_schema():
    """Create the news tables on first use (idempotent).

    Runs once per process. The DDL is invoked on every news request, so without
    this guard each GET would fire a batch of CREATE TABLE IF NOT EXISTS
    round-trips to Postgres for no reason — pure wasted DB traffic. A worker
    crash/restart re-runs it, which is fine (still idempotent). The flag is a
    plain bool: a brief startup race just re-runs the harmless DDL once or twice
    before converging, so no lock is needed."""
    global _schema_ready
    if _schema_ready:
        return
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
    # One row per fresh summary generation, used by the per-IP rate limiter.
    # Shared across workers (unlike the old in-process counter). Pruned by the
    # limiter itself, so it stays tiny.
    _query("""
        CREATE TABLE IF NOT EXISTS summary_rate_hits (
            ip     TEXT NOT NULL,
            hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """, fetch=False)
    _query("""
        CREATE INDEX IF NOT EXISTS idx_summary_rate_hits_ip_at
        ON summary_rate_hits(ip, hit_at DESC)
    """, fetch=False)
    _schema_ready = True


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


def _load_fundamentals(symbol: str) -> dict | None:
    """Compact fundamentals + our precomputed factor scores for one symbol.

    Built from the same tables/joins as the screener so the summary sees the
    same numbers the rest of the app shows. quality_score and pegy reuse the
    canonical helpers in main (rather than re-deriving them here and drifting);
    risk/momentum/piotroski/altman come precomputed from screener_scores.
    Returns None if the symbol has no TTM financials row."""
    rows = _query("""
        SELECT m.sector, m.financial_currency,
               t.market_cap, t.revenue,
               CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END AS price_to_earnings,
               t.price_to_book, t.price_to_sales, t.dividend_yield, t.fcf,
               t.dividends_per_share, t.period_end_price, t.eps_diluted, t.eps_cagr_10,
               t.roe, t.roic, t.gross_margin, t.operating_margin, t.net_income_margin, t.fcf_margin,
               t.revenue_growth, t.eps_diluted_growth, t.debt_to_equity, t.current_ratio,
               t.roic_median, t.roe_median, t.gross_margin_median,
               t.operating_margin_median, t.net_margin_median,
               a.total_analysts, a.eps_growth_next_yr, a.eps_est_current_yr,
               s.momentum_score, s.risk_score, s.piotroski_score,
               s.altman_z, s.volatility_annualised
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol)
                   symbol, total_analysts, eps_growth_next_yr, eps_est_current_yr
            FROM analyst_snapshots
            ORDER BY symbol, snapshot_date DESC
        ) a ON a.symbol = t.company_symbol
        LEFT JOIN screener_scores s ON s.symbol = t.company_symbol
        WHERE t.company_symbol = %s
        LIMIT 1
    """, (symbol,))
    if not rows:
        return None
    f = rows[0]
    try:
        from main import _quality_score, _value_score, _attach_pegy
        _attach_pegy([f])  # adds f["pegy"] in place; value_score uses it
        f["quality_score"] = _quality_score(f)
        f["value_score"] = _value_score(f)
    except Exception as e:  # never let scoring break the summary
        print(f"[news] fundamentals scoring failed for {symbol}: {type(e).__name__}: {e}", flush=True)
    return f


def _fundamentals_block(f: dict | None) -> str:
    """Render the fundamentals/scores dict as compact labelled lines for the
    prompt. Skips anything missing so we never feed the model 'None'."""
    if not f:
        return "  (no fundamentals on file)"
    cur = f.get("financial_currency") or ""

    def _n(x):
        return float(x) if isinstance(x, (int, float)) else None

    def pct(x):
        x = _n(x)
        return f"{x * 100:.1f}%" if x is not None else None

    def num(x):
        x = _n(x)
        return f"{x:.2f}" if x is not None else None

    def money(x):
        x = _n(x)
        if x is None:
            return None
        for unit, div in (("bn", 1e9), ("m", 1e6)):
            if abs(x) >= div:
                return f"{cur} {x / div:.2f}{unit}".strip()
        return f"{cur} {x:.0f}".strip()

    lines: list[str] = []

    def add(label, val):
        if val is not None and val != "":
            lines.append(f"  - {label}: {val}")

    # Our factor scores
    add("Quality score (0-10, higher = better)", f.get("quality_score"))
    add("Value score (0-10, higher = cheaper)", f.get("value_score"))
    add("Risk score (1-10, higher = riskier)", f.get("risk_score"))
    add("Momentum score (1-10, higher = stronger 12-1m)", f.get("momentum_score"))
    add("Piotroski F-score (0-9, higher = better)", f.get("piotroski_score"))
    add("Altman Z (>3 safe, <1.8 distress)", num(f.get("altman_z")))
    # Valuation
    add("PEGY (lower = cheaper vs growth+yield)", num(f.get("pegy")))
    add("P/E", num(f.get("price_to_earnings")))
    add("P/B", num(f.get("price_to_book")))
    add("P/S", num(f.get("price_to_sales")))
    add("Dividend yield", pct(f.get("dividend_yield")))
    # Size & profitability
    add("Market cap", money(f.get("market_cap")))
    add("Revenue (TTM)", money(f.get("revenue")))
    add("Operating margin", pct(f.get("operating_margin")))
    add("Net margin", pct(f.get("net_income_margin")))
    add("ROE", pct(f.get("roe")))
    add("ROIC", pct(f.get("roic")))
    add("Revenue growth (YoY)", pct(f.get("revenue_growth")))
    add("EPS growth (YoY)", pct(f.get("eps_diluted_growth")))
    add("Debt / equity", num(f.get("debt_to_equity")))
    return "\n".join(lines) or "  (no fundamentals on file)"


def _build_summary_messages(name: str, symbol: str, rns: list[dict], google: list[dict], fundamentals: dict | None = None) -> list[dict]:
    system = (
        "You are a UK equity analyst. Summarise the last 60 days of news for one "
        "company — combining regulatory announcements (RNS) with press "
        "coverage. Focus on what actually changed the investment case: "
        "earnings, guidance, M&A, management, strategy, regulatory, legal. "
        "Ignore routine TR-1 / holding notifications, director share dealings "
        "under £100k, and boilerplate press that just rehashes prior news. "
        "You are also given the company's current fundamentals and our factor "
        "scores (quality, value, risk, momentum). Use them as context — to "
        "judge whether the news strengthens or undermines an already strong or "
        "weak setup, or sits at odds with it (e.g. upbeat news on a high-risk, "
        "richly-valued name). The summary stays news-led; the fundamentals are "
        "supporting colour, not the subject. Don't just restate the numbers. "
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

Fundamentals & factor scores (current snapshot)
{_fundamentals_block(fundamentals)}

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

    fundamentals = _load_fundamentals(symbol)
    messages = _build_summary_messages(name, symbol, rns, google, fundamentals)
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


def _check_summary_rate_limit(ip: str) -> None:
    """Reserve a slot in this IP's rolling window, or raise 429. Backed by the
    summary_rate_hits table so the cap is shared across both workers (the old
    in-process counter gave each worker its own quota). One CTE prunes expired
    rows, counts what's left in-window, and inserts a new hit only if still
    under the limits. It's a soft cap: two simultaneous requests take separate
    snapshots and could both pass at the boundary, so the effective ceiling is
    limit + (concurrent requests - 1) — at most one over with two workers.

    Two limits: per-IP for fairness, plus a service-wide cap. The per-IP key
    can be diversified by a caller who forges proxy headers against the API
    origin directly (see request_utils.client_ip), so the global cap is what
    actually bounds worst-case DeepSeek spend per window."""
    rows = _query(
        """
        WITH pruned AS (
            DELETE FROM summary_rate_hits
            WHERE hit_at < NOW() - make_interval(hours => %(window)s)
        ),
        win AS (
            SELECT COUNT(*) FILTER (WHERE ip = %(ip)s) AS n_ip,
                   COUNT(*) AS n_all
            FROM summary_rate_hits
            WHERE hit_at > NOW() - make_interval(hours => %(window)s)
        ),
        ins AS (
            INSERT INTO summary_rate_hits (ip)
            SELECT %(ip)s FROM win
            WHERE win.n_ip < %(limit)s AND win.n_all < %(global_limit)s
            RETURNING 1
        )
        SELECT (SELECT n_ip FROM win) AS n_ip,
               (SELECT n_all FROM win) AS n_all,
               (SELECT COUNT(*) FROM ins) AS inserted
        """,
        {
            "ip": ip,
            "window": _SUMMARY_RATE_WINDOW_HOURS,
            "limit": _SUMMARY_RATE_LIMIT,
            "global_limit": _SUMMARY_GLOBAL_LIMIT,
        },
    )
    if not rows or rows[0]["inserted"] == 0:
        if rows and (rows[0]["n_all"] or 0) >= _SUMMARY_GLOBAL_LIMIT:
            raise HTTPException(
                429,
                "The AI summariser has hit its service-wide daily budget. "
                "Try again tomorrow — cached summaries are unaffected.",
            )
        raise HTTPException(
            429,
            f"Rate limit: max {_SUMMARY_RATE_LIMIT} fresh summaries per "
            f"{_SUMMARY_RATE_WINDOW_HOURS}h. Try again later.",
        )


# Public: any visitor can trigger a summary. A cached summary is served to
# everyone via GET /{symbol} (see _load_summary), so most views cost nothing;
# this POST only spends DeepSeek on an explicit (re)generate click. To re-gate
# it as admin-only, restore `dependencies=[Depends(require_admin_token)]`.
@router.post("/{symbol}/summary")
def generate_summary(symbol: str, request: Request):
    """Call DeepSeek to summarise the last 60 days of news for this company."""
    _ensure_schema()

    # Per-symbol cooldown: if a fresh summary already exists, re-serve it
    # rather than spending DeepSeek again. Keeps the public button cheap under
    # repeated/automated clicks. Cooldown hits don't count toward the rate limit.
    cached = _load_summary(symbol)
    if cached and cached.get("generated_at"):
        age = datetime.now(timezone.utc) - cached["generated_at"]
        if age < timedelta(hours=_SUMMARY_COOLDOWN_HOURS):
            return {"symbol": symbol, "cached": True, **cached}

    # Past the cooldown → this will spend DeepSeek, so count it against the IP.
    _check_summary_rate_limit(_client_ip(request))

    try:
        return _generate_summary(symbol)
    except HTTPException:
        raise  # 404 unknown symbol / 400 no news — already meaningful
    except Exception as e:
        # DeepSeek upstream failure (5xx / 429 / timeout), malformed JSON, etc.
        # Surface a clean reason via response.detail instead of a bare 500 so the
        # UI can show it and the real cause is visible in the logs.
        print(f"[news] summary failed for {symbol}: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(502, f"AI summariser unavailable: {e}") from e


@router.get("/{symbol}")
def get_company_news(symbol: str, refresh: bool = Query(False), response: Response = None):
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

    # RNS lands intraday, so hold only 15 min at the edge. A forced refresh must
    # always hit live data, so never cache that variant.
    if response is not None:
        response.headers["Cache-Control"] = (
            "no-store" if refresh
            else "public, s-maxage=900, stale-while-revalidate=3600"
        )

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
