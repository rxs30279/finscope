"""Digest send pacing (email_rns_digest._interleave_by_provider / _pace).

Mailbox providers throttle per (sending IP × recipient domain) and we send from
Resend's shared pool, so the fix is to avoid hitting one provider in a burst.
Interleaving is meant to do that for free; the sleep is only a floor for lists
interleaving can't spread. These tests pin both halves, and the cost claim.
"""
import pytest

import email_rns_digest as erd


class FakeClock:
    """Deterministic stand-in for the time module — no real sleeping, and the
    'duration' of each Resend call is advanced explicitly by the test."""
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _run(emails, monkeypatch, per_send=0.4):
    """Replay main()'s pacing loop over `emails`, returning (order, total slept)."""
    clock = FakeClock()
    monkeypatch.setattr(erd, "time", clock)
    ordered = erd._interleave_by_provider(emails)
    last, slept = {}, 0.0
    for email in ordered:
        provider = erd.provider_of(email.rsplit("@", 1)[-1])
        slept = erd._pace(provider, last, slept)
        last[provider] = clock.monotonic()
        clock.now += per_send
    return ordered, slept


def _providers(emails):
    return [erd.provider_of(e.rsplit("@", 1)[-1]) for e in emails]


# ── Interleaving ──────────────────────────────────────────────────────────────

def test_interleave_is_a_permutation():
    """Must never drop or duplicate a recipient — this reorders a send list."""
    emails = [f"u{i}@gmail.com" for i in range(45)] + [f"m{i}@hotmail.co.uk" for i in range(9)]
    out = erd._interleave_by_provider(emails)
    assert sorted(out) == sorted(emails)
    assert len(out) == len(emails)


def test_interleave_spreads_the_minority_provider():
    """The 21 Jul shape: 9 Microsoft among 45 others must not end up adjacent."""
    emails = [f"u{i}@gmail.com" for i in range(45)] + [f"m{i}@hotmail.co.uk" for i in range(9)]
    provs = _providers(erd._interleave_by_provider(emails))
    positions = [i for i, p in enumerate(provs) if p == "microsoft"]
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    assert min(gaps) >= 4, f"Microsoft sends bunched up: {positions}"
    # Naive round-robin would put all 9 inside the first 18 slots; even spread
    # means the last one lands near the end of the run.
    assert positions[-1] > len(emails) * 0.7


def test_interleave_preserves_order_within_a_provider():
    emails = [f"u{i}@gmail.com" for i in range(6)] + [f"m{i}@hotmail.co.uk" for i in range(3)]
    out = erd._interleave_by_provider(emails)
    assert [e for e in out if "gmail" in e] == [f"u{i}@gmail.com" for i in range(6)]
    assert [e for e in out if "hotmail" in e] == [f"m{i}@hotmail.co.uk" for i in range(3)]


def test_interleave_groups_provider_not_domain():
    """hotmail.co.uk and outlook.com throttle as one provider, so they must be
    spread against each other — not treated as two independent groups."""
    emails = ["a@hotmail.co.uk", "b@outlook.com", "c@hotmail.com", "d@gmail.com"]
    provs = _providers(erd._interleave_by_provider(emails))
    assert provs.count("microsoft") == 3


def test_interleave_handles_empty_and_single():
    assert erd._interleave_by_provider([]) == []
    assert erd._interleave_by_provider(["a@gmail.com"]) == ["a@gmail.com"]


# ── Pacing ────────────────────────────────────────────────────────────────────

def test_realistic_list_stays_cheap(monkeypatch):
    """The cost claim: on today's 45-Google/9-Microsoft list, interleaving does
    nearly all the work and pacing adds only a few seconds to a ~21s run — it
    must not push the cron request anywhere near its timeout."""
    emails = [f"u{i}@gmail.com" for i in range(45)] + [f"m{i}@hotmail.co.uk" for i in range(9)]
    _, slept = _run(emails, monkeypatch)
    assert slept < 5.0


def test_non_throttling_providers_are_never_paced(monkeypatch):
    """Pacing Google would cost ~72s on the real list for a provider that has
    never deferred us — the budget would be spent on the wrong problem."""
    emails = [f"u{i}@gmail.com" for i in range(45)]
    _, slept = _run(emails, monkeypatch, per_send=0.0)
    assert slept == 0.0


def test_mixed_list_paces_only_microsoft(monkeypatch):
    """Same list, same clock: the Microsoft half sleeps, the Google half doesn't."""
    ms_only, ms_slept = _run([f"m{i}@hotmail.co.uk" for i in range(9)], monkeypatch, per_send=0.0)
    _, google_slept = _run([f"u{i}@gmail.com" for i in range(9)], monkeypatch, per_send=0.0)
    assert ms_slept == pytest.approx(8 * 2.0)
    assert google_slept == 0.0


def test_single_provider_list_gets_paced(monkeypatch):
    """Interleaving can't help when everyone is Microsoft — the floor must."""
    emails = [f"m{i}@hotmail.co.uk" for i in range(10)]
    _, slept = _run(emails, monkeypatch, per_send=0.1)
    assert slept > 0
    # 9 gaps of (2.0 - 0.1) each, capped by the budget.
    assert slept == pytest.approx(min(9 * 1.9, erd._SEND_GAP_BUDGET_S))


def test_pacing_respects_the_budget(monkeypatch):
    """A big single-provider list must not blow the cron-job.org timeout: past
    the budget it degrades to sending fast rather than missing the deadline."""
    monkeypatch.setattr(erd, "_SEND_GAP_BUDGET_S", 5.0)
    emails = [f"m{i}@hotmail.co.uk" for i in range(200)]
    _, slept = _run(emails, monkeypatch, per_send=0.0)
    assert slept <= 5.0


def test_first_send_to_a_provider_never_sleeps(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(erd, "time", clock)
    assert erd._pace("microsoft", {}, 0.0) == 0.0
    assert clock.slept == []


def test_gap_of_zero_disables_pacing(monkeypatch):
    monkeypatch.setattr(erd, "_SEND_GAP_S", 0.0)
    emails = [f"m{i}@hotmail.co.uk" for i in range(20)]
    _, slept = _run(emails, monkeypatch, per_send=0.0)
    assert slept == 0.0


def test_no_sleep_when_gap_already_elapsed(monkeypatch):
    """Slow sends are their own pacing — don't add delay on top."""
    clock = FakeClock()
    monkeypatch.setattr(erd, "time", clock)
    clock.now = 100.0
    slept = erd._pace("microsoft", {"microsoft": 90.0}, 0.0)  # 10s ago, gap is 2s
    assert slept == 0.0
    assert clock.slept == []
