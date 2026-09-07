"""Coupon redemption.

Concurrency design
------------------
The whole operation runs in one transaction at Postgres' default READ
COMMITTED isolation. Two row locks are taken, always in the same global order
-- **order row first, coupon row second** -- so no two concurrent requests can
wait on each other in opposite directions and a deadlock cycle is impossible.

* The **order** lock makes redemption idempotent. Concurrent requests carrying
  the same ``order_id`` serialise on it; the loser observes ``coupon_id``
  already set and replays instead of redeeming twice.
* The **coupon** lock makes the capacity check and the increment atomic, which
  is what holds ``redeemed_count <= max_redemptions`` under load. The database
  check constraint of the same name is the backstop beneath it.
"""

import logging
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from redemption.errors import (
    CouponNotFound,
    CustomerAlreadyRedeemed,
    OrderAlreadyHasCoupon,
    OrderNotFound,
    OrderNotPlaced,
    OrderOwnershipMismatch,
)
from redemption.models import Coupon, Order, OrderStatus
from redemption.policies.registry import PolicyRegistry
from redemption.pricing import DiscountCalculator
from redemption.repositories.interfaces import CouponRepository, OrderRepository
from redemption.services.interfaces import RedemptionService

logger = logging.getLogger(__name__)

REPLAY_CODE = "IDEMPOTENT_REPLAY"


class CouponRedemptionService(RedemptionService):
    """Redeems a coupon against an existing order, exactly once per order."""

    def __init__(
        self,
        orders: OrderRepository,
        coupons: CouponRepository,
        policies: PolicyRegistry,
        discount_calculator: DiscountCalculator,
    ) -> None:
        """Store injected collaborators.

        Args:
            orders: Order persistence, providing the idempotency lock.
            coupons: Coupon persistence, providing the capacity lock.
            policies: Resolves the rules applying to a coupon type.
            discount_calculator: Computes the monetary outcome.
        """
        self._orders = orders
        self._coupons = coupons
        self._policies = policies
        self._discounts = discount_calculator

    def redeem(self, code: str, customer_id: int, order_id: UUID) -> dict[str, Any]:
        """Redeem a coupon against an order.

        Args:
            code: Normalised coupon code.
            customer_id: Customer that must own the order.
            order_id: Order to attach the coupon to; the idempotency key.

        Returns:
            The redemption outcome with remaining slots and the discount
            breakdown. A repeat call for the same order and coupon returns the
            same shape flagged with ``replayed`` and code ``IDEMPOTENT_REPLAY``.

        Raises:
            OrderNotFound: No order exists for ``order_id``.
            OrderOwnershipMismatch: ``customer_id`` does not own the order.
            OrderNotPlaced: The order has been cancelled.
            OrderAlreadyHasCoupon: The order already carries a different coupon.
            CouponNotFound: No coupon exists for ``code``.
            CouponExpired: The coupon's expiry instant has passed.
            CouponExhausted: No redemption slots remain.
            CustomerAlreadyRedeemed: STANDARD coupon already active for this
                customer.
        """
        with transaction.atomic():
            order = self._orders.lock_by_id(order_id)
            if order is None:
                raise OrderNotFound(
                    "Coupon not redeemed because the order does not exist.",
                    order_id=str(order_id),
                    coupon_code=code,
                    customer_id=customer_id,
                )

            if order.user_id != customer_id:
                raise OrderOwnershipMismatch(
                    "Coupon not redeemed because the order belongs to another "
                    "customer.",
                    order_id=str(order_id),
                    coupon_code=code,
                    customer_id=customer_id,
                )

            if order.status != OrderStatus.PLACED:
                raise OrderNotPlaced(
                    "Coupon not redeemed because the order is not active.",
                    order_id=str(order_id),
                    coupon_code=code,
                    customer_id=customer_id,
                    status=order.status,
                )

            if order.coupon_id is not None:
                return self._replay(order, code, customer_id)

            coupon = self._coupons.lock_by_code(code)
            if coupon is None:
                raise CouponNotFound(
                    "Coupon not redeemed because the code is unknown.",
                    order_id=str(order_id),
                    coupon_code=code,
                    customer_id=customer_id,
                )

            for policy in self._policies.for_type(coupon.type):
                policy.enforce(coupon, customer_id)

            coupon.redeemed_count += 1
            self._coupons.save_redeemed_count(coupon)

            try:
                self._orders.attach_coupon(order, coupon)
            except IntegrityError as exc:
                # Unreachable while the coupon lock is held: the policy check
                # above already rejects a second active use. Translated rather
                # than surfaced raw so the partial unique index backstop still
                # produces an actionable error, and the transaction unwinds.
                raise CustomerAlreadyRedeemed(
                    "Coupon not redeemed because this customer already used it.",
                    order_id=str(order_id),
                    coupon_code=code,
                    customer_id=customer_id,
                ) from exc

            logger.info(
                "coupon redeemed",
                extra={
                    "order_id": str(order_id),
                    "coupon_code": coupon.code,
                    "customer_id": customer_id,
                    "redeemed_count": coupon.redeemed_count,
                    "remaining": coupon.remaining,
                },
            )
            return self._success(coupon, order, replayed=False)

    def _replay(self, order: Order, code: str, customer_id: int) -> dict[str, Any]:
        """Return the outcome of an already-completed redemption.

        ``remaining`` is recomputed from the coupon's current state rather than
        stored, so a replay reports the live count and may legitimately differ
        from the original response.

        Args:
            order: Locked order that already carries a coupon.
            code: Coupon code from the replayed request.
            customer_id: Customer from the replayed request.

        Returns:
            The original redemption's outcome, flagged as a replay.

        Raises:
            OrderAlreadyHasCoupon: The order carries a different coupon.
        """
        coupon = self._coupons.lock_by_id(order.coupon_id)
        if coupon is None or coupon.code != code:
            raise OrderAlreadyHasCoupon(
                "Coupon not redeemed because the order already carries another coupon.",
                order_id=str(order.pk),
                coupon_code=code,
                customer_id=customer_id,
                existing_coupon_code=coupon.code if coupon else None,
            )

        logger.info(
            "coupon redemption replayed",
            extra={
                "order_id": str(order.pk),
                "coupon_code": coupon.code,
                "customer_id": customer_id,
                "remaining": coupon.remaining,
            },
        )
        return self._success(coupon, order, replayed=True)

    def _success(self, coupon: Coupon, order: Order, replayed: bool) -> dict[str, Any]:
        """Build the success payload for a redemption.

        Args:
            coupon: Coupon that is now attached to the order.
            order: Order the coupon was applied to.
            replayed: True when this is a repeat of an earlier redemption.

        Returns:
            The redemption response payload.
        """
        breakdown = self._discounts.apply(order.amount, coupon.discount_percent)
        payload: dict[str, Any] = {
            "success": True,
            "remaining": coupon.remaining,
            "redeemed_count": coupon.redeemed_count,
            "order_id": str(order.pk),
            "code": coupon.code,
            "discount_percent": breakdown.discount_percent,
            "original_amount": breakdown.original_amount,
            "discount_amount": breakdown.discount_amount,
            "final_amount": breakdown.final_amount,
            "replayed": replayed,
        }
        if replayed:
            payload["reason"] = REPLAY_CODE
        return payload
