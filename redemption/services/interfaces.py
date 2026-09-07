"""Service abstractions, one per endpoint."""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from redemption.models import CouponType


class UserCreationService(ABC):
    """Seeds customers."""

    @abstractmethod
    def create(self, name: str, email_id: str) -> dict[str, Any]:
        """Create a customer.

        Args:
            name: Display name.
            email_id: Unique email address.

        Returns:
            The created user as a response payload.
        """
        raise NotImplementedError


class CouponCreationService(ABC):
    """Seeds coupons."""

    @abstractmethod
    def create(
        self,
        code: str,
        expires_at: datetime,
        coupon_type: CouponType,
        discount_percent: Decimal,
        max_redemptions: int,
    ) -> dict[str, Any]:
        """Create a coupon.

        Args:
            code: Normalised, unique coupon code.
            expires_at: Timezone-aware expiry instant.
            coupon_type: STANDARD or STACKABLE.
            discount_percent: Percentage in (0, 100].
            max_redemptions: Hard redemption cap, at least 1.

        Returns:
            The created coupon as a response payload.
        """
        raise NotImplementedError


class OrderCreationService(ABC):
    """Seeds orders that coupons are later redeemed against."""

    @abstractmethod
    def create(
        self, order_id: UUID, customer_id: int, amount: Decimal
    ) -> dict[str, Any]:
        """Create an order in the PLACED state with no coupon attached.

        Args:
            order_id: Client-supplied identifier, also the idempotency key.
            customer_id: Owning customer.
            amount: Non-negative order total before any discount.

        Returns:
            The created order as a response payload.
        """
        raise NotImplementedError


class RedemptionService(ABC):
    """Applies a coupon to an existing order."""

    @abstractmethod
    def redeem(self, code: str, customer_id: int, order_id: UUID) -> dict[str, Any]:
        """Redeem a coupon against an order.

        Args:
            code: Normalised coupon code.
            customer_id: Customer that must own the order.
            order_id: Order to attach the coupon to; the idempotency key.

        Returns:
            The redemption outcome, including remaining slots and the discount.
        """
        raise NotImplementedError


class CancellationService(ABC):
    """Cancels an order and reverses any redemption tied to it."""

    @abstractmethod
    def cancel(self, order_id: UUID) -> dict[str, Any]:
        """Cancel an order, releasing its coupon slot if one is held.

        Args:
            order_id: Order to cancel.

        Returns:
            The cancellation outcome; repeat calls report ``replayed``.
        """
        raise NotImplementedError


class CouponQueryService(ABC):
    """Reports live coupon redemption counts."""

    @abstractmethod
    def get_by_code(self, code: str) -> dict[str, Any]:
        """Read a coupon's current redemption state.

        Args:
            code: Normalised coupon code.

        Returns:
            The coupon's counts as a response payload.
        """
        raise NotImplementedError
