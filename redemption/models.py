"""Persistence entities.

The invariants this service exists to protect are enforced here as database
constraints, not only in the service layer: a row violating
``redeemed_count <= max_redemptions`` cannot be committed at all, and a second
active order holding the same STANDARD coupon for the same customer is rejected
by a partial unique index.
"""

import uuid
from decimal import Decimal

from django.db import models


class CouponType(models.TextChoices):
    """Redemption rules that apply on top of the global capacity cap."""

    STANDARD = "STANDARD", "Standard"
    STACKABLE = "STACKABLE", "Stackable"


class OrderStatus(models.TextChoices):
    """Lifecycle states of an order."""

    PLACED = "PLACED", "Placed"
    CANCELLED = "CANCELLED", "Cancelled"


class User(models.Model):
    """A customer who can redeem coupons."""

    name = models.CharField(max_length=255)
    email_id = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        """Return a readable identifier for logs and admin output.

        Returns:
            The user's email address.
        """
        return self.email_id


class Coupon(models.Model):
    """A discount coupon with a hard redemption cap."""

    code = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    type = models.CharField(max_length=16, choices=CouponType.choices)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    max_redemptions = models.PositiveIntegerField()
    redeemed_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "coupons"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(redeemed_count__lte=models.F("max_redemptions")),
                name="coupon_redeemed_within_cap",
            ),
            models.CheckConstraint(
                condition=models.Q(max_redemptions__gte=1),
                name="coupon_max_redemptions_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_percent__gt=0, discount_percent__lte=100),
                name="coupon_discount_percent_range",
            ),
        ]

    @property
    def remaining(self) -> int:
        """Return the redemption slots still available.

        Returns:
            ``max_redemptions - redeemed_count``.
        """
        return self.max_redemptions - self.redeemed_count

    def __str__(self) -> str:
        """Return a readable identifier for logs and admin output.

        Returns:
            The coupon code.
        """
        return self.code


class Order(models.Model):
    """A customer order that may have a coupon attached to it.

    ``id`` is supplied by the client and doubles as the idempotency key for both
    redemption and cancellation. ``is_single_use`` is denormalised from the
    coupon type so the partial unique index below can enforce the STANDARD rule
    without joining.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PLACED
    )
    is_single_use = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=Decimal("0")),
                name="order_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["coupon", "user"],
                condition=models.Q(status=OrderStatus.PLACED, is_single_use=True),
                name="uniq_standard_coupon_active_per_user",
            ),
        ]

    def __str__(self) -> str:
        """Return a readable identifier for logs and admin output.

        Returns:
            The order's primary key as a string.
        """
        return str(self.id)
