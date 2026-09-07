"""Redemption rule abstraction."""

from abc import ABC, abstractmethod

from redemption.models import Coupon


class RedemptionPolicy(ABC):
    """A single rule that must hold for a redemption to proceed."""

    @abstractmethod
    def enforce(self, coupon: Coupon, customer_id: int) -> None:
        """Validate one redemption rule.

        Args:
            coupon: Coupon being redeemed, already locked by the caller.
            customer_id: Customer attempting the redemption.

        Raises:
            AppError: A subclass identifying the specific rule that failed.
        """
        raise NotImplementedError
