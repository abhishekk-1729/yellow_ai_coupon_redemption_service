"""Load: the cap holds when many threads redeem the same coupon at once."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from redemption.container import build_cancellation_service, build_redemption_service
from redemption.errors import AppError
from redemption.models import Coupon, CouponType, Order, OrderStatus
from tests.factories import make_coupon, make_order, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def _redeem(code: str, customer_id: int, order_id: uuid.UUID) -> str:
    """Redeem in a worker thread on its own connection.

    Args:
        code: Coupon code to redeem.
        customer_id: Redeeming customer.
        order_id: Order to redeem against.

    Returns:
        ``"ok"`` on success, otherwise the failing error code.
    """
    try:
        build_redemption_service().redeem(
            code=code, customer_id=customer_id, order_id=order_id
        )
        return "ok"
    except AppError as exc:
        return exc.code
    finally:
        connections.close_all()


def _cancel(order_id: uuid.UUID) -> str:
    """Cancel in a worker thread on its own connection.

    Args:
        order_id: Order to cancel.

    Returns:
        ``"ok"`` on success, otherwise the failing error code.
    """
    try:
        build_cancellation_service().cancel(order_id=order_id)
        return "ok"
    except AppError as exc:
        return exc.code
    finally:
        connections.close_all()


def test_oversubscribed_coupon_never_exceeds_its_cap() -> None:
    """50 threads chasing 10 slots produce exactly 10 redemptions."""
    capacity = 10
    contenders = 50
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)
    orders = [(make_user(), None) for _ in range(contenders)]
    work = [(user, make_order(user).pk) for user, _ in orders]

    with ThreadPoolExecutor(max_workers=contenders) as pool:
        outcomes = list(
            pool.map(lambda item: _redeem(coupon.code, item[0].pk, item[1]), work)
        )

    coupon.refresh_from_db()
    assert outcomes.count("ok") == capacity
    assert outcomes.count("COUPON_EXHAUSTED") == contenders - capacity
    assert coupon.redeemed_count == capacity
    assert coupon.redeemed_count <= coupon.max_redemptions


def test_count_matches_the_orders_that_actually_hold_the_coupon() -> None:
    """The counter is not merely capped, it equals the live redemptions."""
    capacity = 8
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)
    work = [(user := make_user(), make_order(user).pk) for _ in range(40)]

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda item: _redeem(coupon.code, item[0].pk, item[1]), work))

    coupon.refresh_from_db()
    holders = Order.objects.filter(
        coupon=coupon, status=OrderStatus.PLACED
    ).count()
    assert coupon.redeemed_count == holders == capacity


def test_standard_coupon_admits_each_customer_once_under_contention() -> None:
    """Concurrent attempts by one customer on a STANDARD coupon yield one use."""
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=20)
    user = make_user()
    orders = [make_order(user).pk for _ in range(15)]

    with ThreadPoolExecutor(max_workers=15) as pool:
        outcomes = list(
            pool.map(lambda oid: _redeem(coupon.code, user.pk, oid), orders)
        )

    coupon.refresh_from_db()
    assert outcomes.count("ok") == 1
    assert outcomes.count("CUSTOMER_ALREADY_REDEEMED") == len(orders) - 1
    assert coupon.redeemed_count == 1


def test_interleaved_redeem_and_cancel_keeps_the_invariant() -> None:
    """Mixed traffic never drives the counter out of its legal range.

    Redemptions and cancellations take the two row locks in the same order, so
    this exercises the path where a deadlock would appear if they did not.
    """
    capacity = 5
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)
    users = [make_user() for _ in range(30)]
    order_ids = [make_order(user).pk for user in users]

    def redeem_then_cancel(index: int) -> None:
        """Redeem an order and immediately cancel every third one.

        Args:
            index: Position of the order in the prepared list.
        """
        outcome = _redeem(coupon.code, users[index].pk, order_ids[index])
        if outcome == "ok" and index % 3 == 0:
            _cancel(order_ids[index])

    with ThreadPoolExecutor(max_workers=30) as pool:
        list(pool.map(redeem_then_cancel, range(len(users))))

    coupon.refresh_from_db()
    holders = Order.objects.filter(coupon=coupon, status=OrderStatus.PLACED).count()
    assert 0 <= coupon.redeemed_count <= capacity
    assert coupon.redeemed_count == holders


def test_no_intermediate_read_ever_observes_an_illegal_count() -> None:
    """A reader sampling throughout the burst never sees the cap breached.

    ``GET /coupons/:code`` must be correct at all times, not eventually, so the
    sampled values are asserted as they are read rather than only at the end.
    """
    capacity = 6
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)
    work = [(user := make_user(), make_order(user).pk) for _ in range(30)]
    samples: list[int] = []

    def sample() -> None:
        """Read the live count repeatedly while redemptions are in flight."""
        try:
            for _ in range(60):
                samples.append(
                    Coupon.objects.values_list("redeemed_count", flat=True).get(
                        pk=coupon.pk
                    )
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(sample) for _ in range(2)]
        futures += [
            pool.submit(_redeem, coupon.code, user.pk, order_id)
            for user, order_id in work
        ]
        for future in futures:
            future.result()

    assert samples, "the sampler never observed the coupon"
    assert all(0 <= value <= capacity for value in samples)
    coupon.refresh_from_db()
    assert coupon.redeemed_count == capacity
