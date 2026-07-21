"""SES delivery events: SNS unwrap, normalisation, dedupe (ses_events.py).

The normalisation half is what matters most. /status reads problem rates by
matching event_type against exact strings in email_events._PROBLEM_EVENTS, so
an event stored under SES's own spelling ("Bounce") is worse than one not
stored at all: it inflates the message denominator while never counting as a
problem, quietly diluting the rate the cutover is judged on.
"""
import json

import pytest

import ses_events
from email_events import _PROBLEM_EVENTS, provider_of


def _sns(notification: dict, message_id: str = "sns-1") -> str:
    """Wrap an SES notification the way SNS delivers it with raw delivery off."""
    return json.dumps({
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": "arn:aws:sns:eu-west-2:123456789012:alphamove-ses-events",
        "Message": json.dumps(notification),
    })


def _mail(**overrides) -> dict:
    mail = {
        "timestamp": "2026-07-21T06:30:44.861Z",
        "messageId": "0100018f-abcd-1234",
        "source": "digest@alphamoveai.co.uk",
        "destination": ["BenjaminJackMoore@hotmail.co.uk"],
        "commonHeaders": {"subject": "RNS Digest Tue 21 Jul — 32 items"},
    }
    mail.update(overrides)
    return mail


DELIVERY_DELAY = {
    "eventType": "DeliveryDelay",
    "mail": _mail(),
    "deliveryDelay": {
        "timestamp": "2026-07-21T09:14:02.000Z",
        "delayType": "TransientCommunicationFailure",
        "expirationTime": "2026-07-21T18:30:44.000Z",
    },
}

BOUNCE = {
    "eventType": "Bounce",
    "mail": _mail(destination=["info@bioseekers.com"]),
    "bounce": {
        "timestamp": "2026-07-21T06:31:02.000Z",
        "bounceType": "Permanent",
        "bounceSubType": "NoEmail",
        "bouncedRecipients": [{"emailAddress": "info@bioseekers.com",
                               "diagnosticCode": "smtp; 550 5.1.1 user unknown"}],
    },
}


# ── SNS envelope ──────────────────────────────────────────────────────────────

def test_unwraps_sns_envelope():
    assert ses_events.unwrap(_sns(DELIVERY_DELAY))["eventType"] == "DeliveryDelay"


def test_unwrap_returns_none_for_subscription_confirmation():
    """SNS posts one of these when the subscription is created; it has no
    Message payload to parse and must not blow up the drain."""
    body = json.dumps({"Type": "SubscriptionConfirmation", "MessageId": "x",
                       "Token": "abc", "SubscribeURL": "https://..."})
    assert ses_events.unwrap(body) is None


def test_unwrap_returns_none_for_garbage():
    assert ses_events.unwrap("not json") is None
    assert ses_events.unwrap(json.dumps({"Message": "also not json"})) is None


# ── Event-name normalisation ──────────────────────────────────────────────────

@pytest.mark.parametrize("ses_type,expected", [
    ("Send",          "email.sent"),
    ("Delivery",      "email.delivered"),
    ("Bounce",        "email.bounced"),
    ("Complaint",     "email.complained"),
    ("DeliveryDelay", "email.delivery_delayed"),
    ("Reject",        "email.failed"),
])
def test_normalises_event_names(ses_type, expected):
    row = ses_events.parse_event({"eventType": ses_type, "mail": _mail()}, "sns-1")
    assert row["event_type"] == expected


def test_problem_events_match_the_status_cards_vocabulary():
    """The four SES failure modes must land on strings /status already treats
    as problems — this is the assertion that catches a typo'd mapping."""
    for ses_type in ("Bounce", "Complaint", "DeliveryDelay", "Reject"):
        row = ses_events.parse_event({"eventType": ses_type, "mail": _mail()}, "sns-1")
        assert row["event_type"] in _PROBLEM_EVENTS


def test_unknown_event_type_is_dropped():
    assert ses_events.parse_event({"eventType": "Rendering Failure",
                                   "mail": _mail()}, "sns-1") is None


def test_accepts_notification_type_spelling():
    """SES emits `notificationType` on the older SNS notification shape and
    `eventType` via configuration-set destinations. Accept both."""
    row = ses_events.parse_event({"notificationType": "Bounce", "mail": _mail()}, "sns-1")
    assert row["event_type"] == "email.bounced"


# ── Field mapping ─────────────────────────────────────────────────────────────

def test_maps_fields_from_the_ses_shape():
    row = ses_events.parse_event(DELIVERY_DELAY, "sns-1")
    assert row["event_id"] == "sns-1"
    assert row["provider"] == "ses"
    assert row["email_id"] == "0100018f-abcd-1234"
    assert row["recipient"] == "benjaminjackmoore@hotmail.co.uk"   # lowercased
    assert row["recipient_domain"] == "hotmail.co.uk"
    assert row["subject"] == "RNS Digest Tue 21 Jul — 32 items"


def test_recipient_domain_buckets_to_the_right_provider():
    """The Microsoft-vs-everyone-else cut is the whole point of the table."""
    row = ses_events.parse_event(DELIVERY_DELAY, "sns-1")
    assert provider_of(row["recipient_domain"]) == "microsoft"


def test_event_time_and_send_time_are_distinct():
    """occurred_at - email_created_at is the deferral lag; collapsing them to
    one value silently reports every deferral as instant."""
    row = ses_events.parse_event(DELIVERY_DELAY, "sns-1")
    assert row["occurred_at"].hour == 9
    assert row["email_created_at"].hour == 6
    assert row["occurred_at"] > row["email_created_at"]


def test_keeps_bounce_diagnostics():
    row = ses_events.parse_event(BOUNCE, "sns-2")
    assert row["detail"]["bounce"]["bounceType"] == "Permanent"
    assert "550 5.1.1" in row["detail"]["bounce"]["bouncedRecipients"][0]["diagnosticCode"]


def test_delivery_carries_no_detail():
    """detail is for diagnosing failures; a successful delivery has nothing
    worth storing and should not bloat the JSONB column."""
    row = ses_events.parse_event(
        {"eventType": "Delivery", "mail": _mail(),
         "delivery": {"timestamp": "2026-07-21T06:30:50.000Z"}}, "sns-3")
    assert row["detail"] is None


def test_occurred_at_falls_back_to_send_time():
    row = ses_events.parse_event({"eventType": "Send", "mail": _mail()}, "sns-1")
    assert row["occurred_at"] is not None


def test_missing_mail_object_is_dropped():
    assert ses_events.parse_event({"eventType": "Bounce"}, "sns-1") is None


def test_missing_message_id_is_dropped():
    assert ses_events.parse_event(
        {"eventType": "Bounce", "mail": {"destination": ["a@b.com"]}}, "sns-1") is None


# ── drain_queue ───────────────────────────────────────────────────────────────

class _StubSQS:
    """One batch then empty, so drain_queue's loop terminates naturally."""

    def __init__(self, bodies):
        self.batches = [[{"Body": b, "ReceiptHandle": f"rh-{i}"}
                         for i, b in enumerate(bodies)], []]
        self.deleted = []

    def receive_message(self, **kwargs):
        batch = self.batches.pop(0) if self.batches else []
        return {"Messages": batch} if batch else {}

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted.append(ReceiptHandle)


@pytest.fixture
def drained(monkeypatch):
    monkeypatch.setenv("SES_EVENT_QUEUE_URL", "https://sqs.eu-west-2.amazonaws.com/1/q")
    rows = []
    monkeypatch.setattr(ses_events, "_insert", rows.append)
    return rows


def test_drain_stores_and_deletes(monkeypatch, drained):
    sqs = _StubSQS([_sns(DELIVERY_DELAY, "sns-1"), _sns(BOUNCE, "sns-2")])
    monkeypatch.setattr(ses_events, "_client", lambda: sqs)

    stats = ses_events.drain_queue()

    assert stats["received"] == 2 and stats["stored"] == 2
    assert [r["event_id"] for r in drained] == ["sns-1", "sns-2"]
    # Deleted only after the row is written — a crash mid-batch must redeliver.
    assert len(sqs.deleted) == 2


def test_drain_deletes_unparseable_messages(monkeypatch, drained):
    """Otherwise routine SNS control messages cycle until they hit the DLQ and
    trip the queue-depth alarm."""
    body = json.dumps({"Type": "SubscriptionConfirmation", "MessageId": "sns-x"})
    sqs = _StubSQS([body])
    monkeypatch.setattr(ses_events, "_client", lambda: sqs)

    stats = ses_events.drain_queue()

    assert stats["skipped"] == 1 and stats["stored"] == 0
    assert len(sqs.deleted) == 1


def test_drain_uses_sns_message_id_as_idempotency_key(monkeypatch, drained):
    """SNS redelivers the same MessageId on retry; that stability is what makes
    ON CONFLICT DO NOTHING a real dedupe rather than a duplicate-row generator."""
    sqs = _StubSQS([_sns(BOUNCE, "sns-dup"), _sns(BOUNCE, "sns-dup")])
    monkeypatch.setattr(ses_events, "_client", lambda: sqs)

    ses_events.drain_queue()

    assert [r["event_id"] for r in drained] == ["sns-dup", "sns-dup"]


def test_drain_requires_queue_url(monkeypatch):
    monkeypatch.delenv("SES_EVENT_QUEUE_URL", raising=False)
    with pytest.raises(RuntimeError, match="SES_EVENT_QUEUE_URL"):
        ses_events.drain_queue()
