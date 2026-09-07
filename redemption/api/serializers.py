"""Request validation and normalisation at the API boundary.

Input is normalised and rejected here, before any service or query runs.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from redemption.models import CouponType

MAX_COUPON_CODE_LENGTH = 64


def normalise_code(code: str) -> str:
    """Normalise a coupon code to its canonical stored form.

    Args:
        code: Raw code from a request path or body.

    Returns:
        The code trimmed of surrounding whitespace and upper-cased.
    """
    return code.strip().upper()


class AwareDateTimeField(serializers.DateTimeField):
    """A datetime field that refuses input without a timezone offset.

    ``DateTimeField`` silently stamps the project timezone onto a naive value,
    which would let an ambiguous expiry through and shift a coupon's lifetime by
    the server's offset. The raw value is inspected before that happens.
    """

    default_error_messages = {
        "naive": "Datetime must include a timezone offset.",
    }

    def to_internal_value(self, value: Any) -> datetime:
        """Parse a datetime, rejecting naive input.

        Args:
            value: Raw value from the request body.

        Returns:
            The parsed, timezone-aware datetime.

        Raises:
            serializers.ValidationError: The value is naive or unparseable.
        """
        if isinstance(value, datetime) and timezone.is_naive(value):
            self.fail("naive")

        if isinstance(value, str):
            try:
                parsed = parse_datetime(value)
            except ValueError:
                # Well-formed but out of range; the parent renders the message.
                return super().to_internal_value(value)
            if parsed is not None and timezone.is_naive(parsed):
                self.fail("naive")

        return super().to_internal_value(value)


class CouponCreateSerializer(serializers.Serializer):
    """Validates the coupon seeding payload."""

    code = serializers.CharField(max_length=MAX_COUPON_CODE_LENGTH)
    max_redemptions = serializers.IntegerField(min_value=1)
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("100.00"),
    )
    expires_at = AwareDateTimeField()
    type = serializers.ChoiceField(choices=CouponType.choices)

    def validate_code(self, value: str) -> str:
        """Normalise and reject empty coupon codes.

        Args:
            value: Raw coupon code.

        Returns:
            The normalised code.

        Raises:
            serializers.ValidationError: The code is blank after trimming.
        """
        normalised = normalise_code(value)
        if not normalised:
            raise serializers.ValidationError("Coupon code must not be blank.")
        return normalised

class UserCreateSerializer(serializers.Serializer):
    """Validates the user seeding payload."""

    name = serializers.CharField(max_length=255)
    email_id = serializers.EmailField()

    def validate_email_id(self, value: str) -> str:
        """Normalise the email address to lower case.

        Args:
            value: Raw email address.

        Returns:
            The lower-cased address.
        """
        return value.strip().lower()


class OrderCreateSerializer(serializers.Serializer):
    """Validates the order seeding payload."""

    order_id = serializers.UUIDField()
    customer_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00")
    )


class RedeemSerializer(serializers.Serializer):
    """Validates the redemption payload."""

    code = serializers.CharField(max_length=MAX_COUPON_CODE_LENGTH)
    customer_id = serializers.IntegerField(min_value=1)
    order_id = serializers.UUIDField()

    def validate_code(self, value: str) -> str:
        """Normalise and reject empty coupon codes.

        Args:
            value: Raw coupon code.

        Returns:
            The normalised code.

        Raises:
            serializers.ValidationError: The code is blank after trimming.
        """
        normalised = normalise_code(value)
        if not normalised:
            raise serializers.ValidationError("Coupon code must not be blank.")
        return normalised
