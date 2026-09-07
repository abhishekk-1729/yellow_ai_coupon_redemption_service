"""Live coupon redemption counts.

The count is read straight from the committed coupon row -- no cache, no
denormalised counter, no asynchronous projection. That is what makes this
endpoint exactly correct at every instant rather than eventually correct.
"""

from typing import Any

from redemption.errors import CouponNotFound
from redemption.repositories.interfaces import CouponRepository
from redemption.services.interfaces import CouponQueryService


class DefaultCouponQueryService(CouponQueryService):
    """Reports a coupon's current redemption state."""

    def __init__(self, coupons: CouponRepository) -> None:
        """Store injected collaborators.

        Args:
            coupons: Coupon persistence.
        """
        self._coupons = coupons

    def get_by_code(self, code: str) -> dict[str, Any]:
        """Read a coupon's current redemption state.

        Args:
            code: Normalised coupon code.

        Returns:
            The coupon's code, redeemed count, cap and remaining slots.

        Raises:
            CouponNotFound: No coupon exists for ``code``.
        """
        coupon = self._coupons.get_by_code(code)
        if coupon is None:
            raise CouponNotFound(
                "Coupon not found for the requested code.",
                coupon_code=code,
            )

        return {
            "code": coupon.code,
            "redeemed_count": coupon.redeemed_count,
            "max_redemptions": coupon.max_redemptions,
            "remaining": coupon.remaining,
            "type": coupon.type,
            "discount_percent": coupon.discount_percent,
            "expires_at": coupon.expires_at,
        }
