"""End-to-end HTTP behaviour: status codes, error shape and live counts."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from redemption.models import CouponType
from tests.factories import make_coupon, make_order, make_user

pytestmark = pytest.mark.django_db


def _seed_coupon_payload(**overrides) -> dict:
    """Build a valid coupon creation payload.

    Args:
        **overrides: Fields to replace in the default payload.

    Returns:
        A payload suitable for POST /coupons.
    """
    payload = {
        "code": "save20",
        "max_redemptions": 5,
        "discount_percent": "20.00",
        "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "type": CouponType.STANDARD.value,
    }
    payload.update(overrides)
    return payload


def test_seed_coupon_normalises_the_code(api_client) -> None:
    """Codes are upper-cased and trimmed at the boundary before storage."""
    response = api_client.post(
        reverse("coupon-create"), _seed_coupon_payload(code="  save20  "), format="json"
    )

    assert response.status_code == 201
    assert response.data["code"] == "SAVE20"


def test_seed_coupon_rejects_a_naive_expiry(api_client) -> None:
    """An expiry without a timezone offset is ambiguous and is rejected."""
    response = api_client.post(
        reverse("coupon-create"),
        _seed_coupon_payload(expires_at="2030-01-01T00:00:00"),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "VALIDATION_ERROR"


def test_seed_coupon_rejects_an_out_of_range_discount(api_client) -> None:
    """A discount above 100 percent is refused before reaching the database."""
    response = api_client.post(
        reverse("coupon-create"),
        _seed_coupon_payload(discount_percent="120.00"),
        format="json",
    )

    assert response.status_code == 400


def test_duplicate_coupon_code_is_rejected(api_client) -> None:
    """Seeding the same code twice is a distinct conflict, not a crash."""
    api_client.post(reverse("coupon-create"), _seed_coupon_payload(), format="json")

    response = api_client.post(
        reverse("coupon-create"), _seed_coupon_payload(), format="json"
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "COUPON_ALREADY_EXISTS"


def test_redeem_returns_remaining_and_discount(api_client) -> None:
    """A successful redemption reports remaining slots and the discount."""
    user = make_user()
    coupon = make_coupon(discount_percent="20.00", max_redemptions=5)
    order = make_order(user, amount="1000.00")

    response = api_client.post(
        reverse("redeem"),
        {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["success"] is True
    assert response.data["remaining"] == 4
    assert Decimal(str(response.data["final_amount"])) == Decimal("800.00")


def test_money_is_rendered_exactly_not_as_a_float(api_client) -> None:
    """Rendered money keeps two decimal places and never becomes a JSON float.

    Emitting a decimal as a JSON number would convert it to a binary float and
    reintroduce the rounding error the service avoids everywhere else.
    """
    user = make_user()
    coupon = make_coupon(discount_percent="33.33")
    order = make_order(user, amount="1000.00")

    response = api_client.post(
        reverse("redeem"),
        {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)},
        format="json",
    )
    body = json.loads(response.rendered_content)

    assert body["final_amount"] == "666.70"
    assert body["discount_amount"] == "333.30"
    assert body["original_amount"] == "1000.00"


def test_error_payload_carries_code_message_and_correlation_id(api_client) -> None:
    """Every error renders the same actionable shape."""
    user = make_user()

    response = api_client.post(
        reverse("redeem"),
        {"code": "UNKNOWN", "customer_id": user.pk, "order_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 404
    error = response.data["error"]
    assert error["code"] == "ORDER_NOT_FOUND"
    assert error["message"]
    assert error["correlation_id"]


def test_correlation_id_from_the_request_is_echoed(api_client) -> None:
    """An inbound correlation id is reused rather than replaced."""
    response = api_client.get(
        reverse("coupon-detail", args=[make_coupon().code]),
        headers={"X-Correlation-Id": "trace-abc-123"},
    )

    assert response.headers["X-Correlation-Id"] == "trace-abc-123"


def test_idempotency_key_matching_the_order_is_accepted(api_client) -> None:
    """The header is allowed when it names the order it scopes."""
    user = make_user()
    coupon = make_coupon()
    order = make_order(user)

    response = api_client.post(
        reverse("redeem"),
        {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)},
        format="json",
        headers={"Idempotency-Key": str(order.pk)},
    )

    assert response.status_code == 200


def test_idempotency_key_naming_another_order_is_rejected(api_client) -> None:
    """A key scoping a different order would silently mislead the client."""
    user = make_user()
    coupon = make_coupon()
    order = make_order(user)

    response = api_client.post(
        reverse("redeem"),
        {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)},
        format="json",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "IDEMPOTENCY_KEY_MISMATCH"


def test_replayed_redemption_returns_two_hundred_with_a_marker(api_client) -> None:
    """A retry is a success, but stays machine-distinguishable."""
    user = make_user()
    coupon = make_coupon()
    order = make_order(user)
    body = {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)}

    api_client.post(reverse("redeem"), body, format="json")
    response = api_client.post(reverse("redeem"), body, format="json")

    assert response.status_code == 200
    assert response.data["replayed"] is True
    assert response.data["reason"] == "IDEMPOTENT_REPLAY"


def test_coupon_detail_reports_live_counts(api_client) -> None:
    """The read endpoint reflects redemptions the instant they commit."""
    user = make_user()
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=5)
    url = reverse("coupon-detail", args=[coupon.code])

    before = api_client.get(url)
    api_client.post(
        reverse("redeem"),
        {
            "code": coupon.code,
            "customer_id": user.pk,
            "order_id": str(make_order(user).pk),
        },
        format="json",
    )
    after = api_client.get(url)

    assert before.data["redeemed_count"] == 0
    assert before.data["remaining"] == 5
    assert after.data["redeemed_count"] == 1
    assert after.data["remaining"] == 4


def test_coupon_detail_lookup_is_case_insensitive(api_client) -> None:
    """The path code is normalised the same way the stored code was."""
    coupon = make_coupon(code="SUMMER50")

    response = api_client.get(reverse("coupon-detail", args=["summer50"]))

    assert response.status_code == 200
    assert response.data["code"] == coupon.code


def test_unknown_coupon_detail_is_a_not_found(api_client) -> None:
    """Reading a code that was never seeded is a distinct 404."""
    response = api_client.get(reverse("coupon-detail", args=["NOPE"]))

    assert response.status_code == 404
    assert response.data["error"]["code"] == "COUPON_NOT_FOUND"


def test_cancel_endpoint_is_idempotent(api_client) -> None:
    """Cancelling twice over HTTP refunds the slot once."""
    user = make_user()
    coupon = make_coupon(max_redemptions=2)
    order = make_order(user)
    api_client.post(
        reverse("redeem"),
        {"code": coupon.code, "customer_id": user.pk, "order_id": str(order.pk)},
        format="json",
    )
    url = reverse("order-cancel", args=[str(order.pk)])

    first = api_client.post(url, format="json")
    second = api_client.post(url, format="json")

    assert first.status_code == 200 and first.data["replayed"] is False
    assert second.status_code == 200 and second.data["replayed"] is True
    coupon.refresh_from_db()
    assert coupon.redeemed_count == 0


def test_order_creation_requires_an_existing_customer(api_client) -> None:
    """An order cannot be seeded against a customer that does not exist."""
    response = api_client.post(
        reverse("order-create"),
        {"order_id": str(uuid.uuid4()), "customer_id": 999999, "amount": "10.00"},
        format="json",
    )

    assert response.status_code == 404
    assert response.data["error"]["code"] == "USER_NOT_FOUND"


def test_duplicate_order_id_is_rejected(api_client) -> None:
    """Reusing an order id would silently alias two different orders."""
    user = make_user()
    payload = {
        "order_id": str(uuid.uuid4()),
        "customer_id": user.pk,
        "amount": "10.00",
    }
    api_client.post(reverse("order-create"), payload, format="json")

    response = api_client.post(reverse("order-create"), payload, format="json")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "ORDER_ALREADY_EXISTS"


def test_full_seed_to_cancel_flow(api_client) -> None:
    """The documented happy path works end to end over HTTP."""
    user_response = api_client.post(
        reverse("user-create"),
        {"name": "Ada", "email_id": "ada@example.com"},
        format="json",
    )
    customer_id = user_response.data["id"]

    api_client.post(
        reverse("coupon-create"),
        _seed_coupon_payload(
            code="FLOW10", max_redemptions=2, discount_percent="10.00"
        ),
        format="json",
    )

    order_id = str(uuid.uuid4())
    api_client.post(
        reverse("order-create"),
        {"order_id": order_id, "customer_id": customer_id, "amount": "500.00"},
        format="json",
    )

    redeem = api_client.post(
        reverse("redeem"),
        {"code": "FLOW10", "customer_id": customer_id, "order_id": order_id},
        format="json",
        headers={"Idempotency-Key": order_id},
    )
    assert Decimal(str(redeem.data["final_amount"])) == Decimal("450.00")
    assert redeem.data["remaining"] == 1

    api_client.post(reverse("order-cancel", args=[order_id]), format="json")
    detail = api_client.get(reverse("coupon-detail", args=["FLOW10"]))

    assert detail.data["redeemed_count"] == 0
    assert detail.data["remaining"] == 2
