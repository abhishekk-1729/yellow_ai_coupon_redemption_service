"""Global redemption cap rule."""

from redemption.errors import CouponExhausted
from redemption.models import Coupon
from redemption.policies.interfaces import RedemptionPolicy


class CapacityPolicy(RedemptionPolicy):
    """Rejects redemptions once ``redeemed_count`` has reached the cap.

    Correctness depends on the caller holding a row lock on the coupon: the
    read below and the subsequent increment must be atomic with respect to
    other redemptions of the same coupon.
    """

    def enforce(self, coupon: Coupon, customer_id: int) -> None:
        """Validate that a redemption slot is still available.

        Args:
            coupon: Locked coupon being redeemed.
            customer_id: Customer attempting the redemption.

        Raises:
            CouponExhausted: When no redemption slots remain.
        """
        if coupon.redeemed_count >= coupon.max_redemptions:
            raise CouponExhausted(
                "Coupon is not redeemable because no redemptions are left.",
                coupon_code=coupon.code,
                customer_id=customer_id,
                redeemed_count=coupon.redeemed_count,
                max_redemptions=coupon.max_redemptions,
            )
