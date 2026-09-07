"""Per-customer usage rule for STANDARD coupons."""

from redemption.errors import CustomerAlreadyRedeemed
from redemption.models import Coupon
from redemption.policies.interfaces import RedemptionPolicy
from redemption.repositories.interfaces import OrderRepository


class SingleUsePerCustomerPolicy(RedemptionPolicy):
    """Allows a customer at most one active order per STANDARD coupon.

    Only PLACED orders count, so cancelling frees the customer to redeem the
    coupon again. The caller's lock on the coupon row serialises every
    redemption of that coupon, which is what makes this read-then-act check
    safe; the partial unique index on ``orders`` is the database-level backstop.
    """

    def __init__(self, orders: OrderRepository) -> None:
        """Store the injected order repository.

        Args:
            orders: Used to test for an existing active redemption.
        """
        self._orders = orders

    def enforce(self, coupon: Coupon, customer_id: int) -> None:
        """Validate that the customer has no active order for this coupon.

        Args:
            coupon: Locked coupon being redeemed.
            customer_id: Customer attempting the redemption.

        Raises:
            CustomerAlreadyRedeemed: When the customer already holds this coupon
                on a PLACED order.
        """
        if self._orders.has_active_redemption(coupon.pk, customer_id):
            raise CustomerAlreadyRedeemed(
                "Coupon is not redeemable because this customer already used it.",
                coupon_code=coupon.code,
                customer_id=customer_id,
                coupon_type=coupon.type,
            )
