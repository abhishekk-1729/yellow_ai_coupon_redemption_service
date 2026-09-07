"""Order cancellation.

Reverses the redemption tied to an order, if any, and returns the coupon slot
to the pool. Locks are acquired in the same global order as redemption --
**order row first, coupon row second** -- so the two operations can run
concurrently without deadlocking.

Idempotency needs no separate key here: the order's own status transition is
the guard. A second cancellation observes CANCELLED under the row lock and
returns without touching the counter, so the slot is never refunded twice.
"""

import logging
from typing import Any
from uuid import UUID

from django.db import transaction

from redemption.errors import CouponNotFound, OrderNotFound
from redemption.models import Coupon, Order, OrderStatus
from redemption.repositories.interfaces import CouponRepository, OrderRepository
from redemption.services.interfaces import CancellationService

logger = logging.getLogger(__name__)


class OrderCancellationService(CancellationService):
    """Cancels an order at most once, releasing any coupon slot it holds."""

    def __init__(self, orders: OrderRepository, coupons: CouponRepository) -> None:
        """Store injected collaborators.

        Args:
            orders: Order persistence, providing the idempotency lock.
            coupons: Coupon persistence, providing the counter lock.
        """
        self._orders = orders
        self._coupons = coupons

    def cancel(self, order_id: UUID) -> dict[str, Any]:
        """Cancel an order and release its coupon slot.

        Calling this a second time is a no-op: the order is already CANCELLED,
        so the coupon counter is left untouched and the response is flagged
        ``replayed``.

        Args:
            order_id: Order to cancel.

        Returns:
            The cancellation outcome, including the coupon's remaining slots
            when a coupon was attached.

        Raises:
            OrderNotFound: No order exists for ``order_id``.
            CouponNotFound: The attached coupon has disappeared, which would
                mean the order's foreign key was violated.
        """
        with transaction.atomic():
            order = self._orders.lock_by_id(order_id)
            if order is None:
                raise OrderNotFound(
                    "Order not cancelled because it does not exist.",
                    order_id=str(order_id),
                )

            if order.status == OrderStatus.CANCELLED:
                return self._already_cancelled(order)

            coupon = None
            if order.coupon_id is not None:
                coupon = self._coupons.lock_by_id(order.coupon_id)
                if coupon is None:
                    raise CouponNotFound(
                        "Order not cancelled because its coupon no longer exists.",
                        order_id=str(order_id),
                        coupon_id=order.coupon_id,
                    )
                coupon.redeemed_count -= 1
                self._coupons.save_redeemed_count(coupon)

            self._orders.mark_cancelled(order)

            logger.info(
                "order cancelled",
                extra={
                    "order_id": str(order_id),
                    "coupon_code": coupon.code if coupon else None,
                    "customer_id": order.user_id,
                    "redeemed_count": coupon.redeemed_count if coupon else None,
                },
            )
            return self._payload(
                order, coupon_remaining=self._remaining(coupon), replayed=False
            )

    def _already_cancelled(self, order: Order) -> dict[str, Any]:
        """Build the no-op response for an order that is already cancelled.

        Args:
            order: Locked order already in the CANCELLED state.

        Returns:
            The cancellation response, flagged as a replay.
        """
        coupon = (
            self._coupons.lock_by_id(order.coupon_id)
            if order.coupon_id is not None
            else None
        )
        logger.info(
            "order cancellation replayed",
            extra={
                "order_id": str(order.pk),
                "coupon_code": coupon.code if coupon else None,
                "customer_id": order.user_id,
            },
        )
        return self._payload(
            order, coupon_remaining=self._remaining(coupon), replayed=True
        )

    @staticmethod
    def _remaining(coupon: Coupon | None) -> int | None:
        """Return a coupon's remaining slots, tolerating a coupon-less order.

        Args:
            coupon: Coupon attached to the order, or None.

        Returns:
            Remaining redemption slots, or None when no coupon was attached.
        """
        return coupon.remaining if coupon else None

    @staticmethod
    def _payload(
        order: Order, coupon_remaining: int | None, replayed: bool
    ) -> dict[str, Any]:
        """Build the cancellation response payload.

        Args:
            order: Order that is now cancelled.
            coupon_remaining: Remaining slots on the released coupon, if any.
            replayed: True when the order was already cancelled.

        Returns:
            The cancellation response payload.
        """
        return {
            "success": True,
            "order_id": str(order.pk),
            "status": OrderStatus.CANCELLED.value,
            "remaining": coupon_remaining,
            "replayed": replayed,
        }
