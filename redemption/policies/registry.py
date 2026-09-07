"""Maps a coupon type to the ordered rules that govern it."""

from redemption.models import CouponType
from redemption.policies.interfaces import RedemptionPolicy


class PolicyRegistry:
    """Resolves the ordered rule set applied to a given coupon type."""

    def __init__(self, by_type: dict[str, tuple[RedemptionPolicy, ...]]) -> None:
        """Store the rule sets.

        Args:
            by_type: Ordered rules keyed by :class:`CouponType` value.
        """
        self._by_type = by_type

    def for_type(self, coupon_type: str) -> tuple[RedemptionPolicy, ...]:
        """Return the rules to enforce for a coupon type.

        Args:
            coupon_type: A :class:`CouponType` value.

        Returns:
            Rules to enforce, in evaluation order.

        Raises:
            KeyError: The coupon type has no registered rule set, which would
                mean a type was added to the model without a redemption rule.
        """
        return self._by_type[coupon_type]


def build_policy_registry(
    expiry: RedemptionPolicy,
    capacity: RedemptionPolicy,
    single_use: RedemptionPolicy,
) -> PolicyRegistry:
    """Wire the coupon-type rule table.

    Rule order is deliberate and reported to the caller as the first failure:

    1. Expiry -- a dead coupon is dead for everyone, so it outranks the rest.
    2. Per-customer use -- more specific to this requester than the global cap.
       A customer who already holds the coupon should be told exactly that,
       not the misleading "no redemptions left" they would get if the cap were
       checked first on a fully subscribed coupon.
    3. Capacity -- the global cap, checked last.

    Args:
        expiry: Rejects coupons past their expiry instant.
        capacity: Rejects redemptions once the global cap is reached.
        single_use: Restricts a STANDARD coupon to one active use per customer.

    Returns:
        A registry mapping each coupon type to its ordered rules.
    """
    return PolicyRegistry(
        by_type={
            CouponType.STANDARD.value: (expiry, single_use, capacity),
            CouponType.STACKABLE.value: (expiry, capacity),
        }
    )
