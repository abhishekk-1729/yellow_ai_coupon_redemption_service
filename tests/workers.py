"""Worker entry points for the multi-process load tests.

These live at module scope because macOS spawns rather than forks child
processes: the child re-imports this module and must be able to find the
callable by name. Each child bootstraps Django from scratch, so it is handed
the test database name explicitly -- deriving it would silently point the
worker at the development database.
"""

import os
from typing import Any
from uuid import UUID

WorkItem = tuple[int, str]


def _bootstrap(db_name: str) -> None:
    """Initialise Django in a freshly spawned process.

    Args:
        db_name: Database the worker must connect to, normally the test
            database created by pytest-django in the parent process.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "coupon_service.settings")

    import django

    django.setup()

    from django.conf import settings
    from django.db import connections

    settings.DATABASES["default"]["NAME"] = db_name
    connections.databases["default"]["NAME"] = db_name
    # Drop anything inherited from the parent so the worker opens its own socket.
    connections.close_all()


def redeem_worker(
    label: str,
    db_name: str,
    coupon_code: str,
    work: list[WorkItem],
    barrier: Any,
    results: Any,
) -> None:
    """Redeem a batch of orders against one coupon and report the outcomes.

    Args:
        label: Name the parent uses to identify this worker's results.
        db_name: Test database to connect to.
        coupon_code: Coupon every item in ``work`` competes for.
        work: ``(customer_id, order_id)`` pairs to redeem, one per attempt.
        barrier: Synchronisation point so every process starts together.
        results: Queue the outcome list is published on.
    """
    _bootstrap(db_name)

    from django.db import connections

    from redemption.container import build_redemption_service
    from redemption.errors import AppError

    outcomes: list[str] = []
    try:
        service = build_redemption_service()
        barrier.wait()
        for customer_id, order_id in work:
            try:
                service.redeem(
                    code=coupon_code,
                    customer_id=customer_id,
                    order_id=UUID(order_id),
                )
                outcomes.append("ok")
            except AppError as exc:
                outcomes.append(exc.code)
        results.put((label, outcomes))
    finally:
        connections.close_all()


def cancel_worker(
    label: str,
    db_name: str,
    order_ids: list[str],
    barrier: Any,
    results: Any,
) -> None:
    """Cancel a batch of orders and report the outcomes.

    Args:
        label: Name the parent uses to identify this worker's results.
        db_name: Test database to connect to.
        order_ids: Orders to cancel, one per attempt.
        barrier: Synchronisation point so every process starts together.
        results: Queue the outcome list is published on.
    """
    _bootstrap(db_name)

    from django.db import connections

    from redemption.container import build_cancellation_service
    from redemption.errors import AppError

    outcomes: list[str] = []
    try:
        service = build_cancellation_service()
        barrier.wait()
        for order_id in order_ids:
            try:
                service.cancel(order_id=UUID(order_id))
                outcomes.append("ok")
            except AppError as exc:
                outcomes.append(exc.code)
        results.put((label, outcomes))
    finally:
        connections.close_all()


def sampling_worker(
    label: str,
    db_name: str,
    coupon_code: str,
    samples: int,
    barrier: Any,
    results: Any,
) -> None:
    """Poll a coupon's live count while other processes redeem it.

    Args:
        label: Name the parent uses to identify this worker's results.
        db_name: Test database to connect to.
        coupon_code: Coupon to sample.
        samples: Number of reads to take.
        barrier: Synchronisation point so every process starts together.
        results: Queue the observed counts are published on.
    """
    _bootstrap(db_name)

    from django.db import connections

    from redemption.models import Coupon

    observed: list[tuple[int, int]] = []
    try:
        barrier.wait()
        for _ in range(samples):
            row = Coupon.objects.values("redeemed_count", "max_redemptions").get(
                code=coupon_code
            )
            observed.append((row["redeemed_count"], row["max_redemptions"]))
        results.put((label, observed))
    finally:
        connections.close_all()
