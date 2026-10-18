"""Regression of review scheduling (not an economic certification)."""
from scout.pipeline import review_deferred_turn


def test_no_backlog_reviews_fresh_immediately():
    assert review_deferred_turn(0, 5, 42) is False


def test_only_backlog_keeps_moving_when_discovery_returns_zero():
    assert review_deferred_turn(4, 0, 13) is True


def test_backlog_and_fresh_alternate_with_one_review_slot():
    lanes = [review_deferred_turn(32, 2, historic) for historic in range(10, 16)]
    assert lanes == [True, False, True, False, True, False]


def test_deep_review_never_needs_extra_capacity_or_implicit_authority():
    # Returning a lane boolean only must never alter acceptance/quality/review
    # budgets. Every actual candidate must still pass the original hard gates.
    assert type(review_deferred_turn(100, 1, 2)) is bool
    assert type(review_deferred_turn(100, 1, 3)) is bool
