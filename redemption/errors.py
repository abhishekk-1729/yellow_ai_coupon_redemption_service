"""Application error hierarchy.

Every error carries a stable machine-readable ``code``, a human-readable
message, the HTTP status it renders as, and actionable context describing the
entities involved. The correlation id is attached at render time.
"""

from typing import Any

from redemption.observability.correlation import get_correlation_id


class AppError(Exception):
    """Base class for all domain errors raised by the service layer."""

    code: str = "APP_ERROR"
    http_status: int = 500

    def __init__(self, message: str, **context: Any) -> None:
        """Create an error carrying actionable context.

        Args:
            message: Human-readable description of what failed and why.
            **context: Identifying fields (coupon_code, order_id, ...) that make
                the error actionable in logs and API responses.
        """
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        """Render the error as an API-safe payload.

        Returns:
            A mapping with ``code``, ``message``, ``correlation_id`` and ``context``.
        """
        return {
            "code": self.code,
            "message": self.message,
            "correlation_id": get_correlation_id(),
            "context": self.context,
        }


class ValidationError(AppError):
    """Input rejected at the API boundary."""

    code = "VALIDATION_ERROR"
    http_status = 400


class CouponNotFound(AppError):
    """No coupon exists for the supplied code."""

    code = "COUPON_NOT_FOUND"
    http_status = 404


class CouponAlreadyExists(AppError):
    """A coupon with the supplied code has already been seeded."""

    code = "COUPON_ALREADY_EXISTS"
    http_status = 409


class CouponExpired(AppError):
    """The coupon's ``expires_at`` instant has already passed."""

    code = "COUPON_EXPIRED"
    http_status = 409


class CouponExhausted(AppError):
    """The coupon has no redemption slots left."""

    code = "COUPON_EXHAUSTED"
    http_status = 409


class CustomerAlreadyRedeemed(AppError):
    """A STANDARD coupon is already held by an active order for this customer."""

    code = "CUSTOMER_ALREADY_REDEEMED"
    http_status = 409


class UserNotFound(AppError):
    """No user exists for the supplied customer id."""

    code = "USER_NOT_FOUND"
    http_status = 404


class UserAlreadyExists(AppError):
    """A user with the supplied email address already exists."""

    code = "USER_ALREADY_EXISTS"
    http_status = 409


class OrderNotFound(AppError):
    """No order exists for the supplied order id."""

    code = "ORDER_NOT_FOUND"
    http_status = 404


class OrderAlreadyExists(AppError):
    """An order with the supplied order id has already been created."""

    code = "ORDER_ALREADY_EXISTS"
    http_status = 409


class OrderNotPlaced(AppError):
    """The order is not in the PLACED state and cannot be redeemed against."""

    code = "ORDER_NOT_PLACED"
    http_status = 409


class OrderAlreadyHasCoupon(AppError):
    """The order already carries a different coupon than the one requested."""

    code = "ORDER_ALREADY_HAS_COUPON"
    http_status = 409


class OrderOwnershipMismatch(AppError):
    """The supplied customer does not own the order."""

    code = "ORDER_OWNERSHIP_MISMATCH"
    http_status = 403


class IdempotencyKeyMismatch(AppError):
    """The Idempotency-Key header does not match the order id it scopes."""

    code = "IDEMPOTENCY_KEY_MISMATCH"
    http_status = 400
