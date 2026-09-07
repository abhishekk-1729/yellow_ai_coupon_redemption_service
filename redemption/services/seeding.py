"""Seeding services for users, coupons and orders."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from redemption.errors import (
    CouponAlreadyExists,
    OrderAlreadyExists,
    UserAlreadyExists,
    UserNotFound,
)
from redemption.models import CouponType, User
from redemption.repositories.interfaces import (
    CouponRepository,
    OrderRepository,
    UserRepository,
)
from redemption.services.interfaces import (
    CouponCreationService,
    OrderCreationService,
    UserCreationService,
)

logger = logging.getLogger(__name__)


class DefaultUserCreationService(UserCreationService):
    """Creates customers."""

    def __init__(self, users: UserRepository) -> None:
        """Store injected collaborators.

        Args:
            users: User persistence.
        """
        self._users = users

    def create(self, name: str, email_id: str) -> dict[str, Any]:
        """Create a customer.

        Args:
            name: Display name.
            email_id: Unique email address.

        Returns:
            The created user as a response payload.

        Raises:
            UserAlreadyExists: The email address is already registered.
        """
        try:
            user = self._users.create(name=name, email_id=email_id)
        except IntegrityError as exc:
            raise UserAlreadyExists(
                "User not created because the email address is already registered.",
                email_id=email_id,
            ) from exc

        logger.info("user created", extra={"customer_id": user.pk})
        return {"id": user.pk, "name": user.name, "email_id": user.email_id}


class DefaultCouponCreationService(CouponCreationService):
    """Creates coupons."""

    def __init__(self, coupons: CouponRepository) -> None:
        """Store injected collaborators.

        Args:
            coupons: Coupon persistence.
        """
        self._coupons = coupons

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

        Raises:
            CouponAlreadyExists: The code has already been seeded.
        """
        try:
            coupon = self._coupons.create(
                code=code,
                expires_at=expires_at,
                coupon_type=coupon_type,
                discount_percent=discount_percent,
                max_redemptions=max_redemptions,
            )
        except IntegrityError as exc:
            raise CouponAlreadyExists(
                "Coupon not created because the code already exists.",
                coupon_code=code,
            ) from exc

        logger.info("coupon created", extra={"coupon_code": coupon.code})
        return {
            "id": coupon.pk,
            "code": coupon.code,
            "type": coupon.type,
            "discount_percent": coupon.discount_percent,
            "max_redemptions": coupon.max_redemptions,
            "redeemed_count": coupon.redeemed_count,
            "remaining": coupon.remaining,
            "expires_at": coupon.expires_at,
        }


class DefaultOrderCreationService(OrderCreationService):
    """Creates orders that coupons are later redeemed against."""

    def __init__(self, orders: OrderRepository, users: UserRepository) -> None:
        """Store injected collaborators.

        Args:
            orders: Order persistence.
            users: Used to verify the customer exists.
        """
        self._orders = orders
        self._users = users

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

        Raises:
            UserNotFound: No customer exists for ``customer_id``.
            OrderAlreadyExists: The order id is already taken.
        """
        if not self._users.exists(customer_id):
            raise UserNotFound(
                "Order not created because the customer does not exist.",
                customer_id=customer_id,
                order_id=str(order_id),
            )

        try:
            with transaction.atomic():
                order = self._orders.create(
                    order_id=order_id,
                    user=User(pk=customer_id),
                    amount=amount,
                )
        except IntegrityError as exc:
            raise OrderAlreadyExists(
                "Order not created because the order id is already in use.",
                order_id=str(order_id),
                customer_id=customer_id,
            ) from exc

        logger.info(
            "order created",
            extra={"order_id": str(order.pk), "customer_id": customer_id},
        )
        return {
            "id": str(order.pk),
            "customer_id": order.user_id,
            "amount": order.amount,
            "status": order.status,
            "coupon_code": None,
        }
