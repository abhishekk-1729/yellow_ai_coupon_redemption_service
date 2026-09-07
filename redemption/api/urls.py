"""URL wiring.

Dependencies are injected here, at the composition root's edge: each view is
bound to its service via ``as_view()`` so no view builds its own collaborators.
"""

from django.urls import path

from redemption.api.views import (
    CouponCreateView,
    CouponDetailView,
    OrderCancelView,
    OrderCreateView,
    RedeemView,
    UserCreateView,
)
from redemption.container import (
    build_cancellation_service,
    build_coupon_creation_service,
    build_coupon_query_service,
    build_order_creation_service,
    build_redemption_service,
    build_user_creation_service,
)

urlpatterns = [
    path(
        "users",
        UserCreateView.as_view(service=build_user_creation_service()),
        name="user-create",
    ),
    path(
        "coupons",
        CouponCreateView.as_view(service=build_coupon_creation_service()),
        name="coupon-create",
    ),
    path(
        "coupons/<str:code>",
        CouponDetailView.as_view(service=build_coupon_query_service()),
        name="coupon-detail",
    ),
    path(
        "orders",
        OrderCreateView.as_view(service=build_order_creation_service()),
        name="order-create",
    ),
    path(
        "redeem",
        RedeemView.as_view(service=build_redemption_service()),
        name="redeem",
    ),
    path(
        "orders/<uuid:order_id>/cancel",
        OrderCancelView.as_view(service=build_cancellation_service()),
        name="order-cancel",
    ),
]
