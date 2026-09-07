"""Discount arithmetic.

All money is :class:`~decimal.Decimal`; floats are never used. The discounted
total is always derived from ``Order.amount`` and the coupon percentage rather
than stored, so the two can never drift apart and cancellation needs no
monetary reversal.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONETARY_QUANTUM = Decimal("0.01")
_PERCENT_BASE = Decimal("100")


@dataclass(frozen=True)
class DiscountBreakdown:
    """The monetary outcome of applying a coupon to an order."""

    original_amount: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    final_amount: Decimal


class DiscountCalculator(ABC):
    """Computes the monetary effect of a coupon on an order."""

    @abstractmethod
    def apply(self, amount: Decimal, discount_percent: Decimal) -> DiscountBreakdown:
        """Apply a discount to an order amount.

        Args:
            amount: Original order total, non-negative.
            discount_percent: Percentage to deduct, in (0, 100].

        Returns:
            The full breakdown of the discount.
        """
        raise NotImplementedError


class PercentageDiscountCalculator(DiscountCalculator):
    """Percentage-off calculator rounding half-up to two decimal places."""

    def apply(self, amount: Decimal, discount_percent: Decimal) -> DiscountBreakdown:
        """Apply a percentage discount to an order amount.

        The discount is rounded half-up to two places and the final amount is
        the exact difference, so the two always reconcile against the original.

        Args:
            amount: Original order total, non-negative.
            discount_percent: Percentage to deduct, in (0, 100].

        Returns:
            The full breakdown of the discount.
        """
        original = amount.quantize(MONETARY_QUANTUM, rounding=ROUND_HALF_UP)
        discount = (original * discount_percent / _PERCENT_BASE).quantize(
            MONETARY_QUANTUM, rounding=ROUND_HALF_UP
        )
        return DiscountBreakdown(
            original_amount=original,
            discount_percent=discount_percent,
            discount_amount=discount,
            final_amount=original - discount,
        )
