"""Canonical sector-name mapping for the API boundary.

`company_metadata.sector` stores raw GICS/yfinance names ("Consumer Defensive",
"Consumer Cyclical", ...). The rest of the app — sidebar, market rotation,
heatmap — speaks ICB ("Consumer Staples", "Consumer Discretionary", ...). The
screener used to leak the raw GICS names, so its dropdown/table disagreed with
the sidebar for the same stocks.

This module is the single place that translates between the two. The DB stays
the GICS source of truth; we map to ICB on the way out and back to GICS when a
filter selection comes in. Mirrors SECTOR_LABELS in frontend HeatmapTab.js.
"""

# GICS/yfinance name (as stored in the DB) → ICB display name. Sectors not
# listed (Energy, Industrials, Technology, Utilities, Real Estate) share the
# same name in both systems and pass through unchanged.
GICS_TO_ICB = {
    "Basic Materials": "Materials",
    "Communication Services": "Telecommunications",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
}

# Reverse lookup: ICB display name → raw GICS value(s) in the DB. Built as a list
# per ICB name so it stays correct even if the forward map ever becomes
# many-to-one.
ICB_TO_GICS: dict = {}
for _gics, _icb in GICS_TO_ICB.items():
    ICB_TO_GICS.setdefault(_icb, []).append(_gics)


def to_icb(sector):
    """Map a raw GICS/yfinance sector to its ICB display name (identity if unmapped)."""
    if sector is None:
        return None
    return GICS_TO_ICB.get(sector, sector)


def to_gics(sector):
    """Map an ICB display name back to the raw GICS value(s) stored in the DB.

    Returns a list because the screener filters against the DB's GICS column.
    An unmapped name (already-GICS, or a sector with the same name in both
    systems) maps to itself.
    """
    if sector is None:
        return []
    return ICB_TO_GICS.get(sector, [sector])
