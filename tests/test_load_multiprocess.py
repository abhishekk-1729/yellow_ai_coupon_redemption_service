"""Load: two OS processes redeeming concurrently must obey the cap.

Threads share a process and, with it, the GIL and Django's connection handling.
Separate processes share nothing but Postgres, so these tests exercise the only
thing actually enforcing the invariant: row locks and check constraints in the
database.

The suite runs with ``transaction=True`` because the seed data must be
committed before the children are spawned -- inside pytest-django's default
wrapping transaction the children would see an empty database.
"""

import multiprocessing
from typing import Any, Callable

import pytest

from redemption.models import Coupon, CouponType, Order, OrderStatus
from tests.factories import make_coupon, make_order, make_user
from tests.workers import cancel_worker, redeem_worker, sampling_worker

pytestmark = pytest.mark.django_db(transaction=True)

SPAWN = multiprocessing.get_context("spawn")
WORKER_TIMEOUT_SECONDS = 120

WorkerSpec = tuple[str, Callable[..., None], tuple[Any, ...]]


def _run(specs: list[WorkerSpec]) -> dict[str, list[Any]]:
    """Run worker callables in separate processes and collect their results.

    The queue is drained before joining: a child blocking on a full pipe while
    the parent blocks in ``join`` would deadlock the test. Results are keyed by
    label because processes finish in whatever order the race produces.

    Args:
        specs: ``(label, callable, args)`` triples. The label, a barrier and a
            results queue are supplied to each worker automatically.

    Returns:
        Each worker's result list, keyed by its label.

    Raises:
        AssertionError: A worker exited non-zero or produced no result.
    """
    barrier = SPAWN.Barrier(len(specs))
    results: Any = SPAWN.Queue()
    processes = [
        SPAWN.Process(target=target, args=(label, *args, barrier, results))
        for label, target, args in specs
    ]

    try:
        for process in processes:
            process.start()

        collected: dict[str, list[Any]] = {}
        for _ in processes:
            label, outcomes = results.get(timeout=WORKER_TIMEOUT_SECONDS)
            collected[label] = outcomes

        for process in processes:
            process.join(timeout=WORKER_TIMEOUT_SECONDS)
            assert process.exitcode == 0, f"worker failed with {process.exitcode}"

        assert set(collected) == {label for label, _, _ in specs}
        return collected
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=WORKER_TIMEOUT_SECONDS)
        results.close()


def _seed_work(count: int) -> list[tuple[int, str]]:
    """Create distinct customers, each with one order, to compete for a coupon.

    Args:
        count: Number of customer/order pairs to create.

    Returns:
        ``(customer_id, order_id)`` pairs ready to hand to a worker.
    """
    work = []
    for _ in range(count):
        user = make_user()
        work.append((user.pk, str(make_order(user).pk)))
    return work


def test_two_processes_cannot_oversell_a_coupon(test_db_name: str) -> None:
    """Two processes racing for 10 slots redeem exactly 10 times."""
    capacity = 10
    per_process = 15
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)

    outcomes = _run(
        [
            ("a", redeem_worker, (test_db_name, coupon.code, _seed_work(per_process))),
            ("b", redeem_worker, (test_db_name, coupon.code, _seed_work(per_process))),
        ]
    )

    flat = outcomes["a"] + outcomes["b"]
    coupon.refresh_from_db()

    assert len(flat) == per_process * 2
    assert flat.count("ok") == capacity
    assert flat.count("COUPON_EXHAUSTED") == per_process * 2 - capacity
    assert coupon.redeemed_count == capacity
    assert coupon.redeemed_count <= coupon.max_redemptions


def test_both_processes_win_some_slots(test_db_name: str) -> None:
    """The two processes genuinely interleave rather than running in sequence.

    Without this, the cap assertion above could pass simply because one process
    finished before the other started, which would not test concurrency at all.
    """
    capacity = 20
    per_process = 40
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)

    outcomes = _run(
        [
            ("a", redeem_worker, (test_db_name, coupon.code, _seed_work(per_process))),
            ("b", redeem_worker, (test_db_name, coupon.code, _seed_work(per_process))),
        ]
    )

    wins = {label: batch.count("ok") for label, batch in outcomes.items()}
    coupon.refresh_from_db()

    assert sum(wins.values()) == capacity
    assert all(count > 0 for count in wins.values()), (
        f"one process took every slot, so they did not overlap: {wins}"
    )
    assert coupon.redeemed_count == capacity


def test_count_equals_the_orders_holding_the_coupon(test_db_name: str) -> None:
    """The counter is not merely capped; it matches reality row for row."""
    capacity = 12
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)

    _run(
        [
            ("a", redeem_worker, (test_db_name, coupon.code, _seed_work(20))),
            ("b", redeem_worker, (test_db_name, coupon.code, _seed_work(20))),
        ]
    )

    coupon.refresh_from_db()
    holders = Order.objects.filter(coupon=coupon, status=OrderStatus.PLACED).count()
    assert coupon.redeemed_count == holders == capacity


def test_concurrent_redeem_and_cancel_processes_stay_consistent(
    test_db_name: str,
) -> None:
    """One process redeeming while another cancels never breaks the invariant.

    Both operations take the order lock before the coupon lock, so this is the
    scenario in which an inconsistent lock order would surface as a deadlock.
    Cancellation frees slots as redemption consumes them, so the exact final
    count depends on the interleaving; what must hold is that the counter stays
    in range and agrees with the orders that actually hold the coupon.
    """
    capacity = 20
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)

    redeemed_orders = []
    for _ in range(capacity):
        order = make_order(make_user())
        Order.objects.filter(pk=order.pk).update(coupon=coupon)
        redeemed_orders.append(str(order.pk))
    Coupon.objects.filter(pk=coupon.pk).update(redeemed_count=capacity)

    outcomes = _run(
        [
            (
                "redeem",
                redeem_worker,
                (test_db_name, coupon.code, _seed_work(capacity)),
            ),
            ("cancel", cancel_worker, (test_db_name, redeemed_orders)),
        ]
    )

    coupon.refresh_from_db()
    holders = Order.objects.filter(coupon=coupon, status=OrderStatus.PLACED).count()

    assert outcomes["cancel"] == ["ok"] * capacity
    assert set(outcomes["redeem"]) <= {"ok", "COUPON_EXHAUSTED"}
    assert 0 <= coupon.redeemed_count <= capacity
    assert coupon.redeemed_count == holders


def test_a_reader_process_never_observes_an_illegal_count(test_db_name: str) -> None:
    """A third process polling the count sees only legal values, always.

    This is the cross-process form of the "correct at all times, not eventually
    correct" requirement: the reader shares nothing with the writers but the
    database itself.
    """
    capacity = 10
    coupon = make_coupon(coupon_type=CouponType.STACKABLE, max_redemptions=capacity)

    outcomes = _run(
        [
            ("a", redeem_worker, (test_db_name, coupon.code, _seed_work(20))),
            ("b", redeem_worker, (test_db_name, coupon.code, _seed_work(20))),
            ("reader", sampling_worker, (test_db_name, coupon.code, 200)),
        ]
    )

    samples = outcomes["reader"]
    coupon.refresh_from_db()

    assert len(samples) == 200
    assert all(0 <= count <= cap for count, cap in samples)
    assert coupon.redeemed_count == capacity
