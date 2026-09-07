"""Expiry is evaluated against expires_at, inclusive of the exact instant."""

from datetime import timedelta

import pytest
from django.utils import timezone

from redemption.container import build_redemption_service
from redemption.errors import CouponExpired
from tests.factories import FixedClock, make_coupon, make_order, make_user

pytestmark = pytest.mark.django_db


def _service_at(instant):
    """Build a redemption service whose clock is pinned to an instant.

    Args:
        instant: Timezone-aware datetime the service should treat as "now".

    Returns:
        A redemption service using a fixed clock.
    """
    return build_redemption_service(clock=FixedClock(instant))


def test_redeem_succeeds_before_expiry() -> None:
    """A coupon is redeemable at any instant before it expires."""
    expires_at = timezone.now() + timedelta(hours=1)
    user = make_user()
    coupon = make_coupon(expires_at=expires_at)
    order = make_order(user)

    result = _service_at(expires_at - timedelta(minutes=1)).redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert result["success"] is True


def test_redeem_succeeds_at_the_exact_expiry_instant() -> None:
    """A request arriving exactly at expires_at is allowed, not rejected."""
    expires_at = timezone.now() + timedelta(hours=1)
    user = make_user()
    coupon = make_coupon(expires_at=expires_at)
    order = make_order(user)

    result = _service_at(expires_at).redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert result["success"] is True
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1


def test_redeem_fails_one_microsecond_after_expiry() -> None:
    """The very next representable instant after expires_at is already expired."""
    expires_at = timezone.now() + timedelta(hours=1)
    user = make_user()
    coupon = make_coupon(expires_at=expires_at)
    order = make_order(user)

    with pytest.raises(CouponExpired) as excinfo:
        _service_at(expires_at + timedelta(microseconds=1)).redeem(
            code=coupon.code, customer_id=user.pk, order_id=order.pk
        )

    assert excinfo.value.code == "COUPON_EXPIRED"
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0


def test_expired_redemption_leaves_no_trace_on_the_order() -> None:
    """A rejected redemption rolls back entirely, leaving the order unclaimed."""
    expires_at = timezone.now() - timedelta(days=1)
    user = make_user()
    coupon = make_coupon(expires_at=expires_at)
    order = make_order(user)

    with pytest.raises(CouponExpired):
        _service_at(timezone.now()).redeem(
            code=coupon.code, customer_id=user.pk, order_id=order.pk
        )

    order.refresh_from_db()
    assert order.coupon_id is None
