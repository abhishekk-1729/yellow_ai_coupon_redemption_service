"""Type-based constraints: STANDARD is once per customer, STACKABLE is not."""

import pytest
from django.db import IntegrityError, transaction

from redemption.errors import CustomerAlreadyRedeemed
from redemption.models import CouponType, Order, OrderStatus
from tests.factories import make_coupon, make_order, make_user

pytestmark = pytest.mark.django_db


def test_standard_allows_a_customer_one_redemption(redemption_service) -> None:
    """The first redemption of a STANDARD coupon succeeds."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=5)
    order = make_order(user)

    result = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert result["success"] is True


def test_standard_rejects_a_second_redemption_by_the_same_customer(
    redemption_service,
) -> None:
    """A STANDARD coupon cannot be used twice by one customer."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=5)
    first = make_order(user)
    second = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=first.pk
    )

    with pytest.raises(CustomerAlreadyRedeemed) as excinfo:
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=second.pk
        )

    assert excinfo.value.code == "CUSTOMER_ALREADY_REDEEMED"
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1


def test_standard_allows_a_different_customer(redemption_service) -> None:
    """The per-customer rule is scoped to the customer, not the coupon."""
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=5)
    first_user, second_user = make_user(), make_user()

    redemption_service.redeem(
        code=coupon.code, customer_id=first_user.pk, order_id=make_order(first_user).pk
    )
    result = redemption_service.redeem(
        code=coupon.code,
        customer_id=second_user.pk,
        order_id=make_order(second_user).pk,
    )

    assert result["success"] is True
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 2


def test_stackable_allows_the_same_customer_repeatedly(redemption_service) -> None:
    """STACKABLE carries no per-customer rule beyond the global cap."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=3)

    for _ in range(3):
        result = redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
        )
        assert result["success"] is True

    coupon.refresh_from_db()
    assert coupon.redeemed_count == 3


def test_cancelling_frees_the_customer_to_redeem_standard_again(
    redemption_service, cancellation_service
) -> None:
    """The STANDARD rule counts active orders, so cancelling releases it."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=5)
    first = make_order(user)

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=first.pk
    )
    cancellation_service.cancel(order_id=first.pk)

    result = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
    )

    assert result["success"] is True
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 1


def test_a_repeat_customer_is_told_so_even_when_the_coupon_is_full(
    redemption_service,
) -> None:
    """The per-customer rule outranks the cap, because it is more specific.

    Telling a customer who already holds the coupon that there are "no
    redemptions left" would send them away believing they missed out.
    """
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STANDARD, max_redemptions=1)
    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
    )

    with pytest.raises(CustomerAlreadyRedeemed):
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
        )


def test_expiry_outranks_every_other_rule(redemption_service) -> None:
    """An expired coupon reports expiry, not exhaustion, even when full."""
    from datetime import timedelta

    from redemption.errors import CouponExpired

    user = make_user()
    coupon = make_coupon(
        coupon_type=CouponType.STACKABLE,
        max_redemptions=1,
        expires_in=-timedelta(days=1),
    )

    with pytest.raises(CouponExpired):
        redemption_service.redeem(
            code=coupon.code, customer_id=user.pk, order_id=make_order(user).pk
        )


def test_partial_unique_index_rejects_a_duplicate_active_standard_order() -> None:
    """The database refuses a second active STANDARD row even without the service.

    This is the backstop beneath the policy check: were the coupon row lock
    ever bypassed, the invariant would still hold.
    """
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STANDARD)

    Order.objects.create(
        user=user, coupon=coupon, amount="10.00", is_single_use=True,
        status=OrderStatus.PLACED,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Order.objects.create(
                user=user, coupon=coupon, amount="10.00", is_single_use=True,
                status=OrderStatus.PLACED,
            )


def test_partial_unique_index_ignores_cancelled_and_stackable_rows() -> None:
    """Only active single-use rows participate in the uniqueness constraint."""
    user = make_user()
    standard = make_coupon(coupon_type=CouponType.STANDARD)
    stackable = make_coupon(coupon_type=CouponType.STACKABLE)

    Order.objects.create(
        user=user, coupon=standard, amount="10.00", is_single_use=True,
        status=OrderStatus.CANCELLED,
    )
    Order.objects.create(
        user=user, coupon=standard, amount="10.00", is_single_use=True,
        status=OrderStatus.CANCELLED,
    )
    Order.objects.create(
        user=user, coupon=stackable, amount="10.00", is_single_use=False,
        status=OrderStatus.PLACED,
    )
    Order.objects.create(
        user=user, coupon=stackable, amount="10.00", is_single_use=False,
        status=OrderStatus.PLACED,
    )

    assert Order.objects.filter(user=user).count() == 4
