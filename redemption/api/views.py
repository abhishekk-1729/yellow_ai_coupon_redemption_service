"""HTTP handlers.

Views stay thin: validate at the boundary, delegate to an injected service,
serialise the result. Dependencies arrive through ``as_view(**initkwargs)``
from the composition root in :mod:`redemption.api.urls`, so no view constructs
its own collaborators.
"""

from typing import Any
from uuid import UUID

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from redemption.api.serializers import (
    CouponCreateSerializer,
    OrderCreateSerializer,
    RedeemSerializer,
    UserCreateSerializer,
    normalise_code,
)
from redemption.errors import IdempotencyKeyMismatch
from redemption.services.interfaces import (
    CancellationService,
    CouponCreationService,
    CouponQueryService,
    OrderCreationService,
    RedemptionService,
    UserCreationService,
)

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


class UserCreateView(APIView):
    """Seeds customers."""

    service: UserCreationService = None

    def post(self, request: Request) -> Response:
        """Create a customer.

        Args:
            request: Request carrying ``{name, email_id}``.

        Returns:
            201 with the created user.
        """
        payload = UserCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = self.service.create(**payload.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class CouponCreateView(APIView):
    """Seeds coupons."""

    service: CouponCreationService = None

    def post(self, request: Request) -> Response:
        """Create a coupon.

        Args:
            request: Request carrying
                ``{code, max_redemptions, discount_percent, expires_at, type}``.

        Returns:
            201 with the created coupon.
        """
        payload = CouponCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        result = self.service.create(
            code=data["code"],
            expires_at=data["expires_at"],
            coupon_type=data["type"],
            discount_percent=data["discount_percent"],
            max_redemptions=data["max_redemptions"],
        )
        return Response(result, status=status.HTTP_201_CREATED)


class CouponDetailView(APIView):
    """Reports a coupon's live redemption counts."""

    service: CouponQueryService = None

    def get(self, request: Request, code: str) -> Response:
        """Read a coupon's current redemption state.

        Args:
            request: Unused; present for the DRF handler signature.
            code: Coupon code from the URL path.

        Returns:
            200 with the coupon's redeemed count and remaining slots.
        """
        result = self.service.get_by_code(normalise_code(code))
        return Response(result, status=status.HTTP_200_OK)


class OrderCreateView(APIView):
    """Seeds orders."""

    service: OrderCreationService = None

    def post(self, request: Request) -> Response:
        """Create an order in the PLACED state with no coupon attached.

        Args:
            request: Request carrying ``{order_id, customer_id, amount}``.

        Returns:
            201 with the created order.
        """
        payload = OrderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = self.service.create(**payload.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class RedeemView(APIView):
    """Redeems a coupon against an existing order."""

    service: RedemptionService = None

    def post(self, request: Request) -> Response:
        """Redeem a coupon.

        ``order_id`` is the idempotency key. An ``Idempotency-Key`` header is
        optional but, when supplied, must name the same order so a client
        cannot believe it scoped the retry differently than the server did.

        Args:
            request: Request carrying ``{code, customer_id, order_id}`` and an
                optional ``Idempotency-Key`` header.

        Returns:
            200 with the redemption outcome; replays are flagged ``replayed``.
        """
        payload = RedeemSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        self._assert_key_matches_order(request, data["order_id"])

        result = self.service.redeem(
            code=data["code"],
            customer_id=data["customer_id"],
            order_id=data["order_id"],
        )
        return Response(result, status=status.HTTP_200_OK)

    @staticmethod
    def _assert_key_matches_order(request: Request, order_id: UUID) -> None:
        """Reject an ``Idempotency-Key`` that names a different order.

        Args:
            request: Incoming request.
            order_id: Order id from the validated body.

        Raises:
            IdempotencyKeyMismatch: The header is present and does not match.
        """
        supplied: Any = request.headers.get(IDEMPOTENCY_KEY_HEADER)
        if supplied is None:
            return

        try:
            supplied_uuid = UUID(str(supplied).strip())
        except ValueError as exc:
            raise IdempotencyKeyMismatch(
                "Coupon not redeemed because the Idempotency-Key is not a valid "
                "order id.",
                idempotency_key=str(supplied),
                order_id=str(order_id),
            ) from exc

        if supplied_uuid != order_id:
            raise IdempotencyKeyMismatch(
                "Coupon not redeemed because the Idempotency-Key does not match "
                "the order id it scopes.",
                idempotency_key=str(supplied),
                order_id=str(order_id),
            )


class OrderCancelView(APIView):
    """Cancels an order and reverses any redemption tied to it."""

    service: CancellationService = None

    def post(self, request: Request, order_id: UUID) -> Response:
        """Cancel an order.

        Args:
            request: Unused; present for the DRF handler signature.
            order_id: Order to cancel, from the URL path.

        Returns:
            200 with the cancellation outcome; a repeat call is flagged
            ``replayed`` and does not refund the slot again.
        """
        result = self.service.cancel(order_id=order_id)
        return Response(result, status=status.HTTP_200_OK)
