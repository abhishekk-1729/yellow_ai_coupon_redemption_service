"""Idempotency on the redeem side, keyed on order_id."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from redemption.container import build_redemption_service
from redemption.errors import (
    AppError,
    OrderAlreadyHasCoupon,
    OrderNotFound,
    OrderNotPlaced,
    OrderOwnershipMismatch,
)
from redemption.models import CouponType
from redemption.services.redemption import REPLAY_CODE
from tests.factories import make_coupon, make_order, make_user


@pytest.mark.django_db
def test_repeating_a_redemption_does_not_consume_a_second_slot(
    redemption_service,
) -> None:
    """The same order redeemed twice consumes exactly one slot."""
    user = make_user()
    coupon = make_coupon(max_redemptions=5)
    order = make_order(user)

    first = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    second = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["reason"] == REPLAY_CODE
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1


@pytest.mark.django_db
def test_replay_reports_the_same_discount(redemption_service) -> None:
    """A replay returns the same monetary outcome as the original call."""
    user = make_user()
    coupon = make_coupon(discount_percent="30.00")
    order = make_order(user, amount="200.00")

    first = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    second = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert second["discount_amount"] == first["discount_amount"]
    assert second["final_amount"] == first["final_amount"]


@pytest.mark.django_db
def test_reusing_an_order_with_a_different_coupon_is_rejected(
    redemption_service,
) -> None:
    """The idempotency key is scoped to the order, not to the request body."""
    user = make_user()
    first_coupon = make_coupon()
    second_coupon = make_coupon()
    order = make_order(user)

    redemption_service.redeem(
        code=first_coupon.code, customer_id=user.pk, order_id=order.pk
    )

    with pytest.raises(OrderAlreadyHasCoupon) as excinfo:
        redemption_service.redeem(
            code=second_coupon.code, customer_id=user.pk, order_id=order.pk
        )

    assert excinfo.value.code == "ORDER_ALREADY_HAS_COUPON"
    second_coupon.refresh_from_db()
    assert second_coupon.redeemed_count == 0


@pytest.mark.django_db
def test_redeeming_an_unknown_order_is_rejected(redemption_service) -> None:
    """An order that was never seeded cannot be redeemed against."""
    user = make_user()
    coupon = make_coupon()

    with pytest.raises(OrderNotFound) as excinfo:
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=uuid.uuid4()
        )

    assert excinfo.value.code == "ORDER_NOT_FOUND"


@pytest.mark.django_db
def test_redeeming_another_customers_order_is_rejected(redemption_service) -> None:
    """Ownership is checked before anything about the order is revealed."""
    owner, intruder = make_user(), make_user()
    coupon = make_coupon()
    order = make_order(owner)

    with pytest.raises(OrderOwnershipMismatch) as excinfo:
        redemption_service.redeem(
            code=coupon.code, customer_id=intruder.pk, order_id=order.pk
        )

    assert excinfo.value.code == "ORDER_OWNERSHIP_MISMATCH"


@pytest.mark.django_db
def test_cancelled_order_cannot_be_redeemed_again(
    redemption_service, cancellation_service
) -> None:
    """A cancelled order is not replayed as a success: its slot was released."""
    user = make_user()
    coupon = make_coupon()
    order = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )
    cancellation_service.cancel(order_id=order.pk)

    with pytest.raises(OrderNotPlaced) as excinfo:
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=order.pk
        )

    assert excinfo.value.code == "ORDER_NOT_PLACED"
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0


def _redeem_once(code: str, customer_id: int, order_id: uuid.UUID) -> str:
    """Redeem in a worker thread and report the outcome.

    Args:
        code: Coupon code to redeem.
        customer_id: Redeeming customer.
        order_id: Order to redeem against.

    Returns:
        ``"replayed"``, ``"redeemed"`` or the failing error code.
    """
    try:
        result = build_redemption_service().redeem(
            code=code, customer_id=customer_id, order_id=order_id
        )
        return "replayed" if result["replayed"] else "redeemed"
    except AppError as exc:
        return exc.code
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_with_one_key_produce_one_redemption() -> None:
    """Ten simultaneous retries of the same order redeem exactly once."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=10)
    order = make_order(user)
    attempts = 10

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(
            pool.map(
                lambda _: _redeem_once(coupon.code, user.pk, order.pk),
                range(attempts),
            )
        )

    assert outcomes.count("redeemed") == 1
    assert outcomes.count("replayed") == attempts - 1
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1
