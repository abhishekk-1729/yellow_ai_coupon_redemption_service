"""Sanity: the correct discount is applied."""

from decimal import Decimal

import pytest

from redemption.pricing import PercentageDiscountCalculator
from tests.factories import make_coupon, make_order, make_user


@pytest.fixture
def calculator() -> PercentageDiscountCalculator:
    """Provide the percentage discount calculator.

    Returns:
        A calculator rounding half-up to two decimal places.
    """
    return PercentageDiscountCalculator()


def test_applies_flat_percentage(calculator: PercentageDiscountCalculator) -> None:
    """20% off 1000.00 leaves 800.00."""
    result = calculator.apply(Decimal("1000.00"), Decimal("20.00"))

    assert result.discount_amount == Decimal("100.00") * 2
    assert result.final_amount == Decimal("800.00")
    assert result.original_amount == Decimal("1000.00")


def test_rounds_half_up_to_two_places(
    calculator: PercentageDiscountCalculator,
) -> None:
    """15% of 99.99 is 14.9985 and rounds up to 15.00, leaving 84.99."""
    result = calculator.apply(Decimal("99.99"), Decimal("15.00"))

    assert result.discount_amount == Decimal("15.00")
    assert result.final_amount == Decimal("84.99")


def test_discount_and_final_reconcile_against_original(
    calculator: PercentageDiscountCalculator,
) -> None:
    """The parts always sum back to the original amount, whatever the rounding."""
    for amount, percent in [
        ("0.01", "50.00"),
        ("33.33", "33.33"),
        ("1.05", "7.50"),
        ("999999.99", "99.99"),
    ]:
        result = calculator.apply(Decimal(amount), Decimal(percent))
        assert result.discount_amount + result.final_amount == result.original_amount


def test_full_discount_leaves_nothing_to_pay(
    calculator: PercentageDiscountCalculator,
) -> None:
    """A 100% coupon reduces the payable amount to zero."""
    result = calculator.apply(Decimal("250.00"), Decimal("100.00"))

    assert result.final_amount == Decimal("0.00")


def test_money_is_never_a_float(calculator: PercentageDiscountCalculator) -> None:
    """Every monetary field is a Decimal, so no binary rounding error creeps in."""
    result = calculator.apply(Decimal("0.10"), Decimal("30.00"))

    assert isinstance(result.discount_amount, Decimal)
    assert isinstance(result.final_amount, Decimal)
    assert isinstance(result.original_amount, Decimal)


@pytest.mark.django_db
def test_redeem_returns_the_discounted_total(redemption_service) -> None:
    """Redeeming applies the coupon percentage to the order's amount."""
    user = make_user()
    coupon = make_coupon(discount_percent="25.00", max_redemptions=1)
    order = make_order(user, amount="400.00")

    result = redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    assert result["original_amount"] == Decimal("400.00")
    assert result["discount_amount"] == Decimal("100.00")
    assert result["final_amount"] == Decimal("300.00")


@pytest.mark.django_db
def test_order_amount_is_not_mutated_by_redemption(redemption_service) -> None:
    """The stored order keeps its original amount; the total is derived."""
    user = make_user()
    coupon = make_coupon(discount_percent="25.00")
    order = make_order(user, amount="400.00")

    redemption_service.redeem(
        code=coupon.code, customer_id=user.pk, order_id=order.pk
    )

    order.refresh_from_db()
    assert order.amount == Decimal("400.00")
