"""SES delivery events: SQS → email_events.

SES publishes send/delivery/bounce/complaint events to an SNS topic, which
fans out to an SQS queue; this module drains that queue into the same
`email_events` table the Resend webhook writes to.

Why a queue and not an HTTPS endpoint: SNS can POST directly to a URL, but
verifying those POSTs means X.509 certificate-chain validation against an
Amazon signing cert. Getting that subtly wrong yields an endpoint anyone can
forge delivery history into — strictly weaker than the Svix HMAC it replaces.
Pulling from SQS with IAM credentials has no public attack surface at all.

Why this pipeline is mandatory rather than nice-to-have: SES has no message
log. Resend's dashboard was what exposed the 03 Jun–10 Jul silent-fallback bug
(docs/digest-segment-fallback-incident.md). Once SES is the sender, this table
IS the delivery record — if the drain stops, we are blind.

SES event names are normalised into the existing `email.*` vocabulary so
email_events.recent_summary, _PROBLEM_EVENTS, provider_of and the whole
/status deliverability card keep working unchanged.

Env:
  AWS_REGION             — default eu-west-2 (London)
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  SES_EVENT_QUEUE_URL    — full SQS queue URL
"""
import json
import os
from datetime import datetime, timezone

import psycopg2.extras

from db import connection


# SES event type → the email.* vocabulary already in the table and the
# /status card. Anything absent here is dropped rather than stored under a
# name nothing queries: _PROBLEM_EVENTS matches exact strings, so an
# unmapped "Bounce" would be recorded and then silently excluded from the
# problem rate — worse than not storing it.
_EVENT_MAP = {
    "Send":          "email.sent",
    "Delivery":      "email.delivered",
    "Bounce":        "email.bounced",
    "Complaint":     "email.complained",
    "DeliveryDelay": "email.delivery_delayed",
    "Reject":        "email.failed",
    # Subscribed defensively: if Open/Click are ever ticked on the config set
    # by accident, they map to the Resend spelling rather than arriving as
    # unrecognised noise.
    "Open":          "email.opened",
    "Click":         "email.clicked",
}

# Where each event type keeps its own timestamp and detail sub-object.
_SUBOBJECT = {
    "Bounce":        "bounce",
    "Complaint":     "complaint",
    "Delivery":      "delivery",
    "DeliveryDelay": "deliveryDelay",
    "Send":          "send",
    "Reject":        "reject",
    "Open":          "open",
    "Click":         "click",
}

# Sub-objects worth keeping in `detail` — the bounce/complaint diagnostics are
# what turn "it failed" into "the mailbox is full" vs "the domain is gone".
_DETAIL_TYPES = ("bounce", "complaint", "deliveryDelay", "reject")

_MAX_BATCHES = int(os.environ.get("SES_DRAIN_MAX_BATCHES", "20"))


def _client():
    import boto3  # local import: nothing else in the app needs boto3 loaded
    return boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "eu-west-2"))


def _parse_ts(value) -> datetime | None:
    """SES timestamps are ISO 8601, usually Z-suffixed. Normalise to aware UTC
    so lag arithmetic never compares across tz-awareness."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_event(notification: dict, event_id: str) -> dict | None:
    """Flatten one SES event notification into the email_events row shape.

    Returns None for anything unrecognised — SNS subscription-confirmation
    messages and test publishes both land in the queue too.
    """
    mail = notification.get("mail")
    if not isinstance(mail, dict):
        return None

    ses_type = notification.get("eventType") or notification.get("notificationType")
    event_type = _EVENT_MAP.get(ses_type)
    if not event_type:
        return None

    # SES message id is the same value SendEmail returned, so a row here can be
    # tied back to the send that produced it.
    email_id = mail.get("messageId")
    if not email_id:
        return None

    destinations = mail.get("destination") or []
    recipient = str(destinations[0]).strip().lower() if destinations else None
    domain = recipient.split("@")[-1] if recipient and "@" in recipient else None

    sub_key = _SUBOBJECT.get(ses_type, "")
    sub = notification.get(sub_key) if isinstance(notification.get(sub_key), dict) else {}

    detail = {sub_key: sub} if sub and sub_key in _DETAIL_TYPES else None

    return {
        "event_id": event_id,
        "provider": "ses",
        "email_id": str(email_id),
        "event_type": event_type,
        "recipient": recipient,
        "recipient_domain": domain,
        "subject": (mail.get("commonHeaders") or {}).get("subject"),
        # The event's own timestamp when it has one, else the send time. Never
        # NULL — it is the primary sort key for the /status window.
        "occurred_at": _parse_ts(sub.get("timestamp"))
                       or _parse_ts(mail.get("timestamp"))
                       or datetime.now(timezone.utc),
        "email_created_at": _parse_ts(mail.get("timestamp")),
        "detail": detail,
    }


def unwrap(body: str) -> tuple[str | None, dict | None]:
    """Parse one SQS message body once: the SNS envelope's MessageId (used as
    the idempotency key) and the SES notification nested inside it.

    Raw message delivery is deliberately OFF on the subscription, so every
    body is an SNS envelope whose `Message` field is the SES JSON as a string.
    Either element of the tuple may be None: envelopes that carry no parseable
    notification (e.g. the SubscriptionConfirmation SNS sends when the
    subscription is created) still yield a MessageId.
    """
    try:
        envelope = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return None, None
    if not isinstance(envelope, dict):
        return None, None

    envelope_id = envelope.get("MessageId")

    message = envelope.get("Message")
    if not isinstance(message, str):
        return envelope_id, None
    try:
        parsed = json.loads(message)
    except json.JSONDecodeError:
        return envelope_id, None
    return envelope_id, (parsed if isinstance(parsed, dict) else None)


def _insert(row: dict) -> None:
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO email_events (
                event_id, provider, email_id, event_type, recipient,
                recipient_domain, subject, occurred_at, email_created_at, detail
            ) VALUES (%(event_id)s, %(provider)s, %(email_id)s, %(event_type)s,
                      %(recipient)s, %(recipient_domain)s, %(subject)s,
                      %(occurred_at)s, %(email_created_at)s, %(detail)s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            {**row, "detail": psycopg2.extras.Json(row["detail"]) if row["detail"] else None},
        )
        conn.commit()


def _record_bounce(recipient: str, occurred_at, reason: str) -> None:
    """Stamp subscribers.bounced_at on the FIRST hard bounce for an address.

    A record only -- migration 019's own semantics say bounced_at does not
    gate sends, the provider's suppression list does. `bounced_at IS NULL`
    means later bounces of an already-flagged address add nothing, so the
    column always reflects the first failure, not the most recent.
    """
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE subscribers
               SET bounced_at = %s, bounce_reason = %s
             WHERE email = %s AND bounced_at IS NULL
            """,
            (occurred_at, reason, recipient),
        )
        conn.commit()


def _maybe_record_bounce(row: dict) -> None:
    """Stamp bounced_at for a permanent bounce. Transient bounces and
    complaints are excluded -- both are recoverable, and neither implies the
    address itself is dead. Best-effort: the email_events row is already
    committed by `_insert`, so a failure here must not lose it or the
    drain's place in the queue."""
    bounce = (row.get("detail") or {}).get("bounce") or {}
    if bounce.get("bounceType") != "Permanent":
        return
    recipient = row.get("recipient")
    if not recipient:
        return
    recipients = bounce.get("bouncedRecipients") or []
    diagnostic = recipients[0].get("diagnosticCode") if recipients else None
    reason = diagnostic or f"{bounce.get('bounceType')}/{bounce.get('bounceSubType')}"
    try:
        _record_bounce(recipient, row["occurred_at"], reason)
    except Exception as e:
        print(f"[ses-events] WARNING: bounced_at stamp failed for {recipient}: {e}")


def drain_queue(max_batches: int | None = None) -> dict:
    """Drain the SES event queue into email_events. Returns a stats dict.

    A message is deleted only after its row is committed, so a crash mid-batch
    redelivers rather than loses. The SNS MessageId is the idempotency key and
    is stable across SNS's own retries, so redelivery is a no-op via
    ON CONFLICT DO NOTHING.

    Messages that parse to nothing recognisable are deleted too — leaving them
    to cycle until they hit the DLQ would mean the queue depth alarm fires on
    routine SNS control messages.
    """
    queue_url = os.environ.get("SES_EVENT_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("SES_EVENT_QUEUE_URL not configured")

    sqs = _client()
    stats = {"received": 0, "stored": 0, "skipped": 0, "batches": 0}
    limit = max_batches if max_batches is not None else _MAX_BATCHES

    # A crash mid-loop (an SQS call failing partway through, say) must not
    # discard whatever was already drained -- run_email_events.py stamps
    # exactly this dict either way, so losing it here means a real batch of
    # work reads as "nothing happened" in pipeline_runs.
    try:
        for _ in range(limit):
            resp = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                # Long poll: one 10s call instead of a spin of empty short polls.
                WaitTimeSeconds=10,
            )
            messages = resp.get("Messages") or []
            if not messages:
                break

            stats["batches"] += 1
            for message in messages:
                stats["received"] += 1
                body = message.get("Body") or ""
                envelope_id, notification = unwrap(body)

                row = parse_event(notification, envelope_id) if (notification and envelope_id) else None

                if row is None:
                    stats["skipped"] += 1
                else:
                    _insert(row)
                    stats["stored"] += 1
                    if row["event_type"] == "email.bounced":
                        _maybe_record_bounce(row)

                sqs.delete_message(QueueUrl=queue_url,
                                   ReceiptHandle=message["ReceiptHandle"])
    except Exception as e:
        stats["error"] = f"{type(e).__name__}: {e}"

    return stats
