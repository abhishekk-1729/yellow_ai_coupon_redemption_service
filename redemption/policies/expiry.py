"""Expiry rule."""

from redemption.clock import Clock
from redemption.errors import CouponExpired
from redemption.models import Coupon
from redemption.policies.interfaces import RedemptionPolicy


class ExpiryPolicy(RedemptionPolicy):
    """Rejects coupons whose expiry instant has already passed.

    A request arriving exactly at ``expires_at`` is allowed; only ``now``
    strictly after ``expires_at`` is expired.
    """

    def __init__(self, clock: Clock) -> None:
        """Store the injected time source.

        Args:
            clock: Supplies the instant the request is evaluated against.
        """
        self._clock = clock

    def enforce(self, coupon: Coupon, customer_id: int) -> None:
        """Validate that the coupon has not expired.

        Args:
            coupon: Coupon being redeemed.
            customer_id: Customer attempting the redemption, unused by this rule.

        Raises:
            CouponExpired: When the current instant is past ``expires_at``.
        """
        now = self._clock.now()
        if now > coupon.expires_at:
            raise CouponExpired(
                "Coupon is not redeemable because it expired.",
                coupon_code=coupon.code,
                customer_id=customer_id,
                expires_at=coupon.expires_at.isoformat(),
                evaluated_at=now.isoformat(),
            )
