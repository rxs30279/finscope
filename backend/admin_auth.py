"""Shared-secret guard for the expensive refresh/LLM endpoints.

These routes trigger paid or heavy work — DeepSeek calls, GitHub Actions
dispatches, bulk yfinance jobs — so they must not be callable by anonymous
clients (CORS only restricts browsers, not curl). The app's own UI and any
cron callers authenticate by sending the token in the X-Admin-Token header.

Env:
  ADMIN_API_TOKEN — random secret; must be set or every guarded route 503s
                    (fail closed rather than silently open).

The frontend embeds the same token at build time (REACT_APP_ADMIN_TOKEN in
utils.js), so it is recoverable from the JS bundle. That is a deliberate
trade-off: the goal is to stop drive-by scanners and casual cost abuse, not
a determined attacker. Rotate by changing both env vars and redeploying.
"""
import hmac
import os

from fastapi import Header, HTTPException


def require_admin_token(x_admin_token: str = Header(default="")):
    expected = os.environ.get("ADMIN_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "ADMIN_API_TOKEN not configured")
    if not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(403, "Invalid or missing X-Admin-Token")
