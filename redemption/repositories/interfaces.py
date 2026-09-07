"""Persistence abstractions consumed by the service layer.

Interfaces are kept narrow (ISP): each exposes only the operations its
collaborating services actually call. Services depend on these rather than on
Django managers so the transaction and locking behaviour is substitutable.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from datetime import datetime
from uuid import UUID

from redemption.models import Coupon, CouponType, Order, User


class UserRepository(ABC):
    """Read and write access to users."""

    @abstractmethod
    def create(self, name: str, email_id: str) -> User:
        """Persist a new user.

        Args:
            name: Display name.
            email_id: Unique email address.

        Returns:
            The created user.
        """
        raise NotImplementedError

    @abstractmethod
    def exists(self, user_id: int) -> bool:
        """Report whether a user exists.

        Args:
            user_id: Candidate user primary key.

        Returns:
            True when a matching user row exists.
        """
        raise NotImplementedError


class CouponRepository(ABC):
    """Read and write access to coupons."""

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def get_by_code(self, code: str) -> Coupon | None:
        """Read a coupon without locking it.

        Args:
            code: Normalised coupon code.

        Returns:
            The coupon, or None when no such code exists.
        """
        raise NotImplementedError

    @abstractmethod
    def lock_by_code(self, code: str) -> Coupon | None:
        """Read a coupon with ``SELECT ... FOR UPDATE``.

        Must be called inside an open transaction. This is the serialisation
        point that makes the capacity check and increment atomic.

        Args:
            code: Normalised coupon code.

        Returns:
            The locked coupon, or None when no such code exists.
        """
        raise NotImplementedError

    @abstractmethod
    def lock_by_id(self, coupon_id: int) -> Coupon | None:
        """Read a coupon by primary key with ``SELECT ... FOR UPDATE``.

        Args:
            coupon_id: Coupon primary key.

        Returns:
            The locked coupon, or None when it no longer exists.
        """
        raise NotImplementedError

    @abstractmethod
    def save_redeemed_count(self, coupon: Coupon) -> None:
        """Persist a mutated ``redeemed_count``.

        Args:
            coupon: Coupon whose counter has been adjusted in memory.
        """
        raise NotImplementedError


class OrderRepository(ABC):
    """Read and write access to orders."""

    @abstractmethod
    def create(self, order_id: UUID, user: User, amount: Decimal) -> Order:
        """Persist a new order in the PLACED state with no coupon attached.

        Args:
            order_id: Client-supplied primary key, also the idempotency key.
            user: Owning customer.
            amount: Non-negative order total before any discount.

        Returns:
            The created order.
        """
        raise NotImplementedError

    @abstractmethod
    def lock_by_id(self, order_id: UUID) -> Order | None:
        """Read an order with ``SELECT ... FOR UPDATE``.

        Must be called inside an open transaction. Acquired before any coupon
        lock to keep a single global lock order and rule out deadlocks.

        Args:
            order_id: Order primary key.

        Returns:
            The locked order, or None when no such order exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, order_id: UUID) -> Order | None:
        """Read an order without locking it.

        Args:
            order_id: Order primary key.

        Returns:
            The order, or None when no such order exists.
        """
        raise NotImplementedError

    @abstractmethod
    def has_active_redemption(self, coupon_id: int, user_id: int) -> bool:
        """Report whether a customer already holds this coupon on a live order.

        Args:
            coupon_id: Coupon primary key.
            user_id: Customer primary key.

        Returns:
            True when a PLACED order links this customer to this coupon.
        """
        raise NotImplementedError

    @abstractmethod
    def attach_coupon(self, order: Order, coupon: Coupon) -> None:
        """Bind a coupon to an order, claiming the idempotency slot.

        Args:
            order: Locked order with no coupon attached.
            coupon: Coupon being redeemed.
        """
        raise NotImplementedError

    @abstractmethod
    def mark_cancelled(self, order: Order) -> None:
        """Transition an order to CANCELLED.

        Args:
            order: Locked order currently in the PLACED state.
        """
        raise NotImplementedError
