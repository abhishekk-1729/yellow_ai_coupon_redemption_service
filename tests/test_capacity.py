"""The global redemption cap, and the database constraint beneath it."""

import pytest
from django.db import IntegrityError, transaction

from redemption.errors import CouponExhausted, CouponNotFound
from redemption.models import Coupon, CouponType
from tests.factories import make_coupon, make_order, make_user

pytestmark = pytest.mark.django_db


def test_redemption_consumes_one_slot(redemption_service) -> None:
    """Each successful redemption decrements the remaining count by one."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=3)

    result = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
    )

    assert result["remaining"] == 2
    assert result["redeemed_count"] == 1


def test_redemption_fails_once_the_cap_is_reached(redemption_service) -> None:
    """The redemption after the last slot is rejected as exhausted."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=1)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
    )

    with pytest.raises(CouponExhausted) as excinfo:
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
        )

    assert excinfo.value.code == "COUPON_EXHAUSTED"
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1


def test_unknown_code_is_rejected(redemption_service) -> None:
    """An unrecognised coupon code produces a distinct error."""
    user = make_user()

    with pytest.raises(CouponNotFound) as excinfo:
        redemption_service.redeem(
            code="NO-SUCH-CODE", customer_id=user.pk, order_id=make_order(user).pk
        )

    assert excinfo.value.code == "COUPON_NOT_FOUND"


def test_database_rejects_a_count_above_the_cap() -> None:
    """The check constraint makes the headline invariant unbreakable.

    Even a write that bypasses the service layer entirely cannot commit a row
    where ``redeemed_count`` exceeds ``max_redemptions``.
    """
    coupon = make_coupon(max_redemptions=2)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Coupon.objects.filter(pk=coupon.pk).update(redeemed_count=3)


def test_database_allows_a_count_exactly_at_the_cap() -> None:
    """Reaching the cap is legal; only exceeding it is not."""
    coupon = make_coupon(max_redemptions=2)

    Coupon.objects.filter(pk=coupon.pk).update(redeemed_count=2)

    coupon.refresh_from_db()
    assert coupon.redeemed_count == 2
    assert coupon.remaining == 0


def test_database_rejects_a_negative_count() -> None:
    """The counter cannot be refunded below zero."""
    coupon = make_coupon(max_redemptions=2)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Coupon.objects.filter(pk=coupon.pk).update(redeemed_count=-1)
