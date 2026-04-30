"""Inngest client initialisation.

Environment:
  INNGEST_EVENT_KEY    — from Inngest Cloud dashboard (required for sending events)
  INNGEST_SIGNING_KEY  — from Inngest Cloud dashboard (required for serving)
"""
import os
import inngest
from dotenv import load_dotenv

load_dotenv()

_client = inngest.Inngest(
    name="Finance API",
    event_key=os.environ.get("INNGEST_EVENT_KEY", ""),
    signing_key=os.environ.get("INNGEST_SIGNING_KEY", ""),
)


def get_client() -> inngest.Inngest:
    return _client
