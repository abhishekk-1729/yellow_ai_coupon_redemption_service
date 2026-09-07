"""Composition root.

The only place concrete implementations are named. Every service receives its
collaborators through its constructor, so nothing below the API layer resolves
its own dependencies.
"""

from redemption.clock import Clock, SystemClock
from redemption.policies.capacity import CapacityPolicy
from redemption.policies.customer_usage import SingleUsePerCustomerPolicy
from redemption.policies.expiry import ExpiryPolicy
from redemption.policies.registry import PolicyRegistry, build_policy_registry
from redemption.pricing import PercentageDiscountCalculator
from redemption.repositories.django_repositories import (
    DjangoCouponRepository,
    DjangoOrderRepository,
    DjangoUserRepository,
)
from redemption.repositories.interfaces import OrderRepository
from redemption.services.cancellation import OrderCancellationService
from redemption.services.coupon_query import DefaultCouponQueryService
from redemption.services.interfaces import (
    CancellationService,
    CouponCreationService,
    CouponQueryService,
    OrderCreationService,
    RedemptionService,
    UserCreationService,
)
from redemption.services.redemption import CouponRedemptionService
from redemption.services.seeding import (
    DefaultCouponCreationService,
    DefaultOrderCreationService,
    DefaultUserCreationService,
)


def build_policy_registry_for(orders: OrderRepository, clock: Clock) -> PolicyRegistry:
    """Wire the redemption rule table.

    Args:
        orders: Order persistence used by the per-customer rule.
        clock: Time source used by the expiry rule.

    Returns:
        A registry resolving each coupon type to its ordered rules.
    """
    return build_policy_registry(
        expiry=ExpiryPolicy(clock=clock),
        capacity=CapacityPolicy(),
        single_use=SingleUsePerCustomerPolicy(orders=orders),
    )


def build_redemption_service(clock: Clock | None = None) -> RedemptionService:
    """Assemble the coupon redemption service.

    Args:
        clock: Time source; defaults to the system clock. Tests inject a fixed
            clock to sit exactly on the expiry boundary.

    Returns:
        A fully wired redemption service.
    """
    orders = DjangoOrderRepository()
    return CouponRedemptionService(
        orders=orders,
        coupons=DjangoCouponRepository(),
        policies=build_policy_registry_for(orders=orders, clock=clock or SystemClock()),
        discount_calculator=PercentageDiscountCalculator(),
    )


def build_cancellation_service() -> CancellationService:
    """Assemble the order cancellation service.

    Returns:
        A fully wired cancellation service.
    """
    return OrderCancellationService(
        orders=DjangoOrderRepository(),
        coupons=DjangoCouponRepository(),
    )


def build_coupon_query_service() -> CouponQueryService:
    """Assemble the coupon query service.

    Returns:
        A fully wired coupon query service.
    """
    return DefaultCouponQueryService(coupons=DjangoCouponRepository())


def build_coupon_creation_service() -> CouponCreationService:
    """Assemble the coupon seeding service.

    Returns:
        A fully wired coupon creation service.
    """
    return DefaultCouponCreationService(coupons=DjangoCouponRepository())


def build_user_creation_service() -> UserCreationService:
    """Assemble the user seeding service.

    Returns:
        A fully wired user creation service.
    """
    return DefaultUserCreationService(users=DjangoUserRepository())


def build_order_creation_service() -> OrderCreationService:
    """Assemble the order seeding service.

    Returns:
        A fully wired order creation service.
    """
    return DefaultOrderCreationService(
        orders=DjangoOrderRepository(),
        users=DjangoUserRepository(),
    )
