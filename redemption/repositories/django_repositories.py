"""Django ORM implementations of the persistence interfaces."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from redemption.models import Coupon, CouponType, Order, OrderStatus, User
from redemption.repositories.interfaces import (
    CouponRepository,
    OrderRepository,
    UserRepository,
)


class DjangoUserRepository(UserRepository):
    """User persistence backed by the Django ORM."""

    def create(self, name: str, email_id: str) -> User:
        """Persist a new user.

        Args:
            name: Display name.
            email_id: Unique email address.

        Returns:
            The created user.
        """
        return User.objects.create(name=name, email_id=email_id)

    def exists(self, user_id: int) -> bool:
        """Report whether a user exists.

        Args:
            user_id: Candidate user primary key.

        Returns:
            True when a matching user row exists.
        """
        return User.objects.filter(pk=user_id).exists()


class DjangoCouponRepository(CouponRepository):
    """Coupon persistence backed by the Django ORM."""

    def create(
        self,
        code: str,
        expires_at: datetime,
        coupon_type: CouponType,
        discount_percent: Decimal,
        max_redemptions: int,
    ) -> Coupon:
        """Persist a new coupon.

        Args:
            code: Normalised, unique coupon code.
            expires_at: Timezone-aware expiry instant.
            coupon_type: STANDARD or STACKABLE.
            discount_percent: Percentage in (0, 100].
            max_redemptions: Hard redemption cap, at least 1.

        Returns:
            The created coupon.
        """
        return Coupon.objects.create(
            code=code,
            expires_at=expires_at,
            type=coupon_type,
            discount_percent=discount_percent,
            max_redemptions=max_redemptions,
        )

    def get_by_code(self, code: str) -> Coupon | None:
        """Read a coupon without locking it.

        Args:
            code: Normalised coupon code.

        Returns:
            The coupon, or None when no such code exists.
        """
        return Coupon.objects.filter(code=code).first()

    def lock_by_code(self, code: str) -> Coupon | None:
        """Read a coupon with ``SELECT ... FOR UPDATE``.

        Args:
            code: Normalised coupon code.

        Returns:
            The locked coupon, or None when no such code exists.
        """
        return Coupon.objects.select_for_update().filter(code=code).first()

    def lock_by_id(self, coupon_id: int) -> Coupon | None:
        """Read a coupon by primary key with ``SELECT ... FOR UPDATE``.

        Args:
            coupon_id: Coupon primary key.

        Returns:
            The locked coupon, or None when it no longer exists.
        """
        return Coupon.objects.select_for_update().filter(pk=coupon_id).first()

    def save_redeemed_count(self, coupon: Coupon) -> None:
        """Persist a mutated ``redeemed_count``.

        Args:
            coupon: Coupon whose counter has been adjusted in memory.
        """
        coupon.save(update_fields=["redeemed_count"])


class DjangoOrderRepository(OrderRepository):
    """Order persistence backed by the Django ORM."""

    def create(self, order_id: UUID, user: User, amount: Decimal) -> Order:
        """Persist a new order in the PLACED state with no coupon attached.

        Args:
            order_id: Client-supplied primary key, also the idempotency key.
            user: Owning customer.
            amount: Non-negative order total before any discount.

        Returns:
            The created order.
        """
        return Order.objects.create(
            id=order_id,
            user=user,
            amount=amount,
            status=OrderStatus.PLACED,
        )

    def lock_by_id(self, order_id: UUID) -> Order | None:
        """Read an order with ``SELECT ... FOR UPDATE``.

        ``select_related`` is deliberately not used here: Postgres rejects
        ``FOR UPDATE`` against the nullable side of an outer join, and the
        coupon is fetched separately under its own lock anyway.

        Args:
            order_id: Order primary key.

        Returns:
            The locked order, or None when no such order exists.
        """
        return Order.objects.select_for_update().filter(pk=order_id).first()

    def get_by_id(self, order_id: UUID) -> Order | None:
        """Read an order without locking it.

        Args:
            order_id: Order primary key.

        Returns:
            The order, or None when no such order exists.
        """
        return Order.objects.filter(pk=order_id).first()

    def has_active_redemption(self, coupon_id: int, user_id: int) -> bool:
        """Report whether a customer already holds this coupon on a live order.

        Args:
            coupon_id: Coupon primary key.
            user_id: Customer primary key.

        Returns:
            True when a PLACED order links this customer to this coupon.
        """
        return Order.objects.filter(
            coupon_id=coupon_id,
            user_id=user_id,
            status=OrderStatus.PLACED,
        ).exists()

    def attach_coupon(self, order: Order, coupon: Coupon) -> None:
        """Bind a coupon to an order, claiming the idempotency slot.

        Args:
            order: Locked order with no coupon attached.
            coupon: Coupon being redeemed.
        """
        order.coupon = coupon
        order.is_single_use = coupon.type == CouponType.STANDARD
        order.save(update_fields=["coupon", "is_single_use", "updated_at"])

    def mark_cancelled(self, order: Order) -> None:
        """Transition an order to CANCELLED.

        Args:
            order: Locked order currently in the PLACED state.
        """
        order.status = OrderStatus.CANCELLED
        order.save(update_fields=["status", "updated_at"])
