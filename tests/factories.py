"""Shared construction helpers for tests."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from redemption.clock import Clock
from redemption.models import Coupon, CouponType, Order, OrderStatus, User


class FixedClock(Clock):
    """Clock returning a caller-controlled instant.

    Lets expiry tests sit exactly on ``expires_at`` instead of sleeping.
    """

    def __init__(self, instant: datetime) -> None:
        """Store the instant to report.

        Args:
            instant: Timezone-aware datetime to return from :meth:`now`.
        """
        self._instant = instant

    def now(self) -> datetime:
        """Return the configured instant.

        Returns:
            The timezone-aware datetime supplied at construction.
        """
        return self._instant


def make_user(email_id: str | None = None, name: str = "Test Customer") -> User:
    """Create a persisted user.

    Args:
        email_id: Email address; a unique one is generated when omitted.
        name: Display name.

    Returns:
        The created user.
    """
    return User.objects.create(
        name=name,
        email_id=email_id or f"user-{uuid.uuid4().hex[:12]}@example.com",
    )


def make_coupon(
    code: str | None = None,
    coupon_type: CouponType = CouponType.STANDARD,
    discount_percent: str = "10.00",
    max_redemptions: int = 5,
    expires_in: timedelta = timedelta(days=1),
    expires_at: datetime | None = None,
) -> Coupon:
    """Create a persisted coupon.

    Args:
        code: Coupon code; a unique one is generated when omitted.
        coupon_type: STANDARD or STACKABLE.
        discount_percent: Percentage as a decimal string.
        max_redemptions: Hard redemption cap.
        expires_in: Offset from now used when ``expires_at`` is omitted.
        expires_at: Explicit expiry instant.

    Returns:
        The created coupon.
    """
    return Coupon.objects.create(
        code=code or f"CODE{uuid.uuid4().hex[:8].upper()}",
        type=coupon_type,
        discount_percent=Decimal(discount_percent),
        max_redemptions=max_redemptions,
        expires_at=expires_at or (timezone.now() + expires_in),
    )


def make_order(
    user: User, amount: str = "1000.00", order_id: uuid.UUID | None = None
) -> Order:
    """Create a persisted order in the PLACED state with no coupon.

    Args:
        user: Owning customer.
        amount: Order total as a decimal string.
        order_id: Explicit primary key; generated when omitted.

    Returns:
        The created order.
    """
    return Order.objects.create(
        id=order_id or uuid.uuid4(),
        user=user,
        amount=Decimal(amount),
        status=OrderStatus.PLACED,
    )
