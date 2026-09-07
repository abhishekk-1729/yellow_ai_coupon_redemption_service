"""End-to-end load check against a running server.

The pytest suite exercises the service layer directly. This drives the same
invariant over real HTTP against gunicorn with multiple worker processes, which
is the closest stand-in for production traffic.

Usage::

    .venv/bin/gunicorn coupon_service.wsgi:application --workers 2 --bind 127.0.0.1:8000
    .venv/bin/python scripts/loadtest_http.py --base-url http://127.0.0.1:8000
"""

import argparse
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

REQUEST_TIMEOUT_SECONDS = 30


def _post(session: requests.Session, url: str, payload: dict[str, Any]) -> Any:
    """Send a JSON POST and return the decoded body.

    Args:
        session: Reusable HTTP session.
        url: Absolute URL to post to.
        payload: JSON-serialisable request body.

    Returns:
        The decoded response body.
    """
    response = session.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    return response.json()


def _seed(base_url: str, session: requests.Session, capacity: int, contenders: int):
    """Create a coupon plus one customer and order per contender.

    Args:
        base_url: Root URL of the running service.
        session: Reusable HTTP session.
        capacity: Redemption cap for the coupon.
        contenders: Number of customer/order pairs to create.

    Returns:
        The coupon code and the list of ``(customer_id, order_id)`` pairs.
    """
    code = f"LOAD{uuid.uuid4().hex[:8].upper()}"
    _post(
        session,
        f"{base_url}/coupons",
        {
            "code": code,
            "max_redemptions": capacity,
            "discount_percent": "10.00",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat(),
            "type": "STACKABLE",
        },
    )

    work = []
    for index in range(contenders):
        user = _post(
            session,
            f"{base_url}/users",
            {"name": f"Load {index}", "email_id": f"{uuid.uuid4().hex}@example.com"},
        )
        order_id = str(uuid.uuid4())
        _post(
            session,
            f"{base_url}/orders",
            {"order_id": order_id, "customer_id": user["id"], "amount": "100.00"},
        )
        work.append((user["id"], order_id))
    return code, work


def _redeem(base_url: str, code: str, customer_id: int, order_id: str) -> str:
    """Attempt one redemption over HTTP.

    Args:
        base_url: Root URL of the running service.
        code: Coupon code to redeem.
        customer_id: Redeeming customer.
        order_id: Order to redeem against.

    Returns:
        ``"ok"`` on success, otherwise the error code the service returned.
    """
    with requests.Session() as session:
        body = _post(
            session,
            f"{base_url}/redeem",
            {"code": code, "customer_id": customer_id, "order_id": order_id},
        )
    return "ok" if body.get("success") else body["error"]["code"]


def main() -> int:
    """Run the load check and report whether the invariant held.

    Returns:
        0 when the cap was respected, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--capacity", type=int, default=25)
    parser.add_argument("--contenders", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=32)
    args = parser.parse_args()

    with requests.Session() as session:
        code, work = _seed(args.base_url, session, args.capacity, args.contenders)

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            outcomes = list(
                pool.map(
                    lambda item: _redeem(args.base_url, code, item[0], item[1]), work
                )
            )

        detail = session.get(
            f"{args.base_url}/coupons/{code}", timeout=REQUEST_TIMEOUT_SECONDS
        ).json()

    successes = outcomes.count("ok")
    print(f"coupon             : {code}")
    print(f"cap                : {args.capacity}")
    print(f"attempts           : {len(outcomes)}")
    print(f"successful redeems : {successes}")
    print(f"reported count     : {detail['redeemed_count']}")
    print(f"reported remaining : {detail['remaining']}")

    if successes != args.capacity or detail["redeemed_count"] != args.capacity:
        print("FAIL: the redemption cap was not respected")
        return 1

    print("PASS: redeemed_count == max_redemptions, no oversell")
    return 0


if __name__ == "__main__":
    sys.exit(main())
