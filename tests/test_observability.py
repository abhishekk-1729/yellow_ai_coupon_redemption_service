"""Logging is the only thing you have when a redemption misbehaves in production.

These tests pin the properties that make a log line useful: it is valid JSON, it
carries the correlation id that ties a request together, it carries the
identifiers needed to act on it, and one failure produces exactly one record.
"""

import json
import logging
import uuid

import pytest
from django.urls import reverse

from redemption.observability.correlation import (
    CORRELATION_ID_HEADER,
    CorrelationIdFilter,
    get_correlation_id,
    set_correlation_id,
)
from redemption.observability.formatter import JsonFormatter
from redemption.models import CouponType
from tests.factories import make_coupon, make_order, make_user


class _Capture(logging.Handler):
    """Collects records emitted by a specific logger."""

    def __init__(self) -> None:
        """Start with an empty record buffer and the production filter attached."""
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(CorrelationIdFilter())

    def emit(self, record: logging.LogRecord) -> None:
        """Buffer a record.

        Args:
            record: Record emitted by the attached logger.
        """
        self.records.append(record)


@pytest.fixture
def capture_logs():
    """Attach a capturing handler to a named logger for the duration of a test.

    ``caplog`` installs its handler on the root logger, which never sees the
    ``redemption`` logger because that one sets ``propagate = False``.

    Returns:
        A factory taking a logger name and returning the capture handler.
        ``level`` is left alone unless given -- overriding it would defeat any
        test asserting that a configured level suppresses a record.
    """
    attached: list[tuple[logging.Logger, _Capture, int]] = []

    def _attach(name: str, level: int | None = None) -> _Capture:
        logger = logging.getLogger(name)
        handler = _Capture()
        previous = logger.level
        logger.addHandler(handler)
        if level is not None:
            logger.setLevel(level)
        attached.append((logger, handler, previous))
        return handler

    yield _attach

    for logger, handler, previous in attached:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def test_formatter_emits_valid_json_with_extras() -> None:
    """A record renders as one JSON object carrying its ``extra=`` fields."""
    record = logging.LogRecord(
        name="redemption.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="coupon redeemed",
        args=None,
        exc_info=None,
    )
    record.coupon_code = "SAVE20"
    record.customer_id = 7

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "coupon redeemed"
    assert payload["level"] == "INFO"
    assert payload["coupon_code"] == "SAVE20"
    assert payload["customer_id"] == 7
    assert "timestamp" in payload


def test_formatter_includes_the_active_correlation_id() -> None:
    """The correlation id is stamped on every record without being passed in."""
    set_correlation_id("trace-xyz")
    record = logging.LogRecord(
        name="redemption.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="something happened",
        args=None,
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["correlation_id"] == "trace-xyz"
    set_correlation_id("")


def test_formatter_survives_unserialisable_extras() -> None:
    """A stray object in ``extra=`` must never take the request down with it."""
    record = logging.LogRecord(
        name="redemption.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="odd payload",
        args=None,
        exc_info=None,
    )
    record.weird = object()

    payload = json.loads(JsonFormatter().format(record))

    assert "weird" in payload


@pytest.mark.django_db
def test_a_failed_request_logs_exactly_one_record(api_client, capture_logs) -> None:
    """One failure produces one log line, not a duplicate without context.

    Django logs every 4xx a second time from ``BaseHandler.get_response``, which
    runs after the correlation-id middleware has unwound, so that duplicate
    carries an empty correlation id and cannot be traced. ``django.request`` is
    pinned to ERROR to suppress it.
    """
    ours = capture_logs("redemption", level=logging.DEBUG)
    djangos = capture_logs("django.request")

    response = api_client.post(
        reverse("redeem"),
        {
            "code": "NO-SUCH-CODE",
            "customer_id": make_user().pk,
            "order_id": str(uuid.uuid4()),
        },
        format="json",
        headers={CORRELATION_ID_HEADER: "trace-abc"},
    )

    assert response.status_code == 404
    assert len(ours.records) == 1
    assert not djangos.records


@pytest.mark.django_db
def test_a_failure_log_carries_everything_needed_to_act(
    api_client, capture_logs
) -> None:
    """The log line names the code, the coupon and the customer, not just a message."""
    handler = capture_logs("redemption", level=logging.DEBUG)
    user = make_user()
    other = make_user()
    coupon = make_coupon(
        coupon_type=CouponType.STACKABLE, max_redemptions=1
    )
    api_client.post(
        reverse("redeem"),
        {
            "code": coupon.code,
            "customer_id": user.pk,
            "order_id": str(make_order(user).pk),
        },
        format="json",
    )
    handler.records.clear()

    api_client.post(
        reverse("redeem"),
        {
            "code": coupon.code,
            "customer_id": other.pk,
            "order_id": str(make_order(other).pk),
        },
        format="json",
        headers={CORRELATION_ID_HEADER: "trace-exhausted"},
    )

    payload = json.loads(JsonFormatter().format(handler.records[-1]))
    assert payload["error_code"] == "COUPON_EXHAUSTED"
    assert payload["coupon_code"] == coupon.code
    assert payload["customer_id"] == other.pk
    assert payload["correlation_id"] == "trace-exhausted"


@pytest.mark.django_db
def test_a_successful_redemption_logs_the_resulting_counts(
    api_client, capture_logs
) -> None:
    """Success is logged too, with the counts needed to audit the invariant."""
    handler = capture_logs("redemption", level=logging.INFO)
    user = make_user()
    coupon = make_coupon(max_redemptions=3)

    api_client.post(
        reverse("redeem"),
        {
            "code": coupon.code,
            "customer_id": user.pk,
            "order_id": str(make_order(user).pk),
        },
        format="json",
    )

    redeemed = [r for r in handler.records if r.getMessage() == "coupon redeemed"]
    assert len(redeemed) == 1
    payload = json.loads(JsonFormatter().format(redeemed[0]))
    assert payload["redeemed_count"] == 1
    assert payload["remaining"] == 2


@pytest.mark.django_db
def test_correlation_id_is_generated_when_the_client_sends_none(api_client) -> None:
    """Every request is traceable even if the caller supplies no id."""
    response = api_client.get(reverse("coupon-detail", args=[make_coupon().code]))

    assert uuid.UUID(response.headers[CORRELATION_ID_HEADER])


def test_correlation_id_does_not_leak_between_requests() -> None:
    """The context variable is reset, so ids never bleed across requests."""
    set_correlation_id("")
    assert get_correlation_id() == ""
