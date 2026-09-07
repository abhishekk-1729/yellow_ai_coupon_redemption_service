"""Cancellation reverses a redemption exactly once."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from redemption.container import build_cancellation_service
from redemption.errors import OrderNotFound
from redemption.models import CouponType, OrderStatus
from tests.factories import make_coupon, make_order, make_user


@pytest.mark.django_db
def test_cancelling_releases_the_coupon_slot(
    redemption_service, cancellation_service
) -> None:
    """Cancelling an order returns its slot to the pool."""
    user = make_user()
    coupon = make_coupon(max_redemptions=3)
    order = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    result = cancellation_service.cancel(order_id=order.pk)

    assert result["success"] is True
    assert result["replayed"] is False
    assert result["remaining"] == 3
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0
    order.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED


@pytest.mark.django_db
def test_cancelling_twice_does_not_refund_the_slot_twice(
    redemption_service, cancellation_service
) -> None:
    """The second cancellation is a no-op, not a double refund."""
    user = make_user()
    coupon = make_coupon(max_redemptions=3)
    order = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    cancellation_service.cancel(order_id=order.pk)
    coupon.refresh_from_db()
    count_after_first = coupon.redeemed_count

    second = cancellation_service.cancel(order_id=order.pk)

    assert second["success"] is True
    assert second["replayed"] is True
    coupon.refresh_from_db()
    assert coupon.redeemed_count == count_after_first == 0


@pytest.mark.django_db
def test_cancelling_repeatedly_never_drives_the_count_negative(
    redemption_service, cancellation_service
) -> None:
    """Repeated cancellation is stable, and the counter never goes below zero."""
    user = make_user()
    coupon = make_coupon(max_redemptions=3)
    order = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    for _ in range(5):
        cancellation_service.cancel(order_id=order.pk)

    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0


@pytest.mark.django_db
def test_cancelling_an_order_without_a_coupon_succeeds(cancellation_service) -> None:
    """An order that never redeemed anything still cancels cleanly."""
    order = make_order(make_user())

    result = cancellation_service.cancel(order_id=order.pk)

    assert result["success"] is True
    assert result["remaining"] is None
    order.refresh_from_db()
    assert order.status == OrderStatus.CANCELLED


@pytest.mark.django_db
def test_cancelling_an_unknown_order_is_rejected(cancellation_service) -> None:
    """A cancellation for an order that does not exist is a distinct error."""
    with pytest.raises(OrderNotFound) as excinfo:
        cancellation_service.cancel(order_id=uuid.uuid4())

    assert excinfo.value.code == "ORDER_NOT_FOUND"


@pytest.mark.django_db
def test_released_slot_is_available_to_another_customer(
    redemption_service, cancellation_service
) -> None:
    """A freed slot really is usable, not merely reflected in the count."""
    first_user, second_user = make_user(), make_user()
    coupon = make_coupon(max_redemptions=1)
    first_order = make_order(first_user)

    redemption_service.redeem(
        code=coupon.code, customer_id=first_user.pk, order_id=first_order.pk
    )
    cancellation_service.cancel(order_id=first_order.pk)

    result = redemption_service.redeem(
        code=coupon.code,
        customer_id=second_user.pk,
        order_id=make_order(second_user).pk,
    )

    assert result["success"] is True
    assert result["remaining"] == 0


def _cancel_once(order_id: uuid.UUID) -> bool:
    """Cancel in a worker thread and report whether it was the effective call.

    Args:
        order_id: Order to cancel.

    Returns:
        True when this call performed the cancellation rather than replaying it.
    """
    try:
        return not build_cancellation_service().cancel(order_id=order_id)["replayed"]
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancellations_refund_exactly_one_slot(
    redemption_service,
) -> None:
    """Simultaneous cancellations of one order refund the slot only once."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=5)
    order = make_order(user)
    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    attempts = 10

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        effective = list(pool.map(lambda _: _cancel_once(order.pk), range(attempts)))

    assert effective.count(True) == 1
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0
