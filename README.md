# Coupon Redemption Service

A Django/DRF service that redeems coupons against orders, built around one
requirement: `redeemed_count <= max_redemptions` must hold at **every instant**,
under concurrent load, across separate processes.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env          # then edit DB_USER / DB_PASSWORD for your Postgres
createdb coupons
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Nothing is hardcoded: `settings.py` reads every environment-dependent value from
the environment and raises `ImproperlyConfigured` at import time if a required
one is missing.

## Tests

```bash
.venv/bin/pytest                                        # full suite
.venv/bin/pytest tests/test_load_multiprocess.py -v      # the two-process load test
```

Tests run against **real Postgres**. SQLite cannot model `SELECT ... FOR UPDATE`,
so running them on it would make the concurrency suite pass vacuously.

An end-to-end load check over real HTTP, against multiple worker processes:

```bash
.venv/bin/gunicorn coupon_service.wsgi:application --workers 2 --bind 127.0.0.1:8000
.venv/bin/python scripts/loadtest_http.py --base-url http://127.0.0.1:8000
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/users` | Seed a customer |
| POST | `/coupons` | Seed a coupon |
| GET | `/coupons/:code` | Live redemption counts |
| POST | `/orders` | Seed an order (PLACED, no coupon) |
| POST | `/redeem` | Attach a coupon to an order |
| POST | `/orders/:order_id/cancel` | Cancel, releasing any coupon slot |

`POST /redeem` accepts an optional `Idempotency-Key` header. Errors all render as:

```json
{"success": false,
 "error": {"code": "COUPON_EXHAUSTED", "message": "...", "correlation_id": "...",
           "context": {"coupon_code": "SAVE20", "customer_id": 12}}}
```

| Code | HTTP | Meaning |
|---|---|---|
| `COUPON_NOT_FOUND` | 404 | Unknown code |
| `COUPON_EXPIRED` | 409 | Past `expires_at` |
| `COUPON_EXHAUSTED` | 409 | No redemptions left |
| `CUSTOMER_ALREADY_REDEEMED` | 409 | STANDARD, already held by this customer |
| `ORDER_NOT_FOUND` | 404 | Unknown `order_id` |
| `ORDER_NOT_PLACED` | 409 | Order already cancelled |
| `ORDER_ALREADY_HAS_COUPON` | 409 | Same order, *different* coupon |
| `ORDER_OWNERSHIP_MISMATCH` | 403 | `customer_id` does not own the order |
| `IDEMPOTENCY_KEY_MISMATCH` | 400 | Header names a different order |
| `VALIDATION_ERROR` | 400 | Rejected at the boundary |

A **replay** is not an error. Repeating a redemption returns `200` with
`"replayed": true` and `"reason": "IDEMPOTENT_REPLAY"` — a retry that succeeded is
a success — but it stays machine-distinguishable from a first-time redemption.

## How the invariant is actually held

Three independent layers, so that no single mistake can breach the cap.

**1. Row locks.** Redemption runs in one transaction at Postgres' default READ
COMMITTED isolation and takes two locks, always in the same global order:

> **order row first, coupon row second** — in redemption *and* cancellation.

Because the order is fixed, two concurrent requests can never wait on each other
in opposite directions, so a deadlock cycle is impossible and no retry loop is
needed. Locks block rather than using `NOWAIT`/`SKIP LOCKED`: under contention
the right answer is to wait and be correct.

- The **order** lock is what makes redemption idempotent. Concurrent requests
  carrying the same `order_id` serialise on it; the loser finds `coupon_id`
  already set and replays instead of redeeming twice.
- The **coupon** lock makes the capacity check and the increment atomic. This is
  what stops the classic lost update where two readers both see `9 < 10`.

`SERIALIZABLE` isolation was considered and rejected: it would force
serialization-failure retry loops throughout the service for no guarantee that
`FOR UPDATE` does not already provide here.

**2. Database check constraints.** `coupon_redeemed_within_cap` enforces
`redeemed_count <= max_redemptions` in Postgres itself. A row violating the
invariant cannot be committed *at all* — not by this service, not by a future
caller, not by a hand-written `UPDATE`. A load test proving the code is correct
is strictly weaker than a schema in which the violation is unrepresentable.

**3. A partial unique index** enforces the STANDARD rule:

```sql
CREATE UNIQUE INDEX uniq_standard_coupon_active_per_user ON orders (coupon_id, user_id)
WHERE (is_single_use AND status = 'PLACED');
```

`Order.is_single_use` is denormalised from the coupon type at redemption time,
because Django cannot reference `coupon__type` in a constraint condition.
Cancelled rows drop out of the index, which is exactly the "cancelling frees the
customer" semantics below.

### Verifying the tests have teeth

A concurrency test that always passes proves nothing. Removing the
`select_for_update()` from `lock_by_code` and re-running makes **8 of the 10**
concurrency tests fail, with the lost updates visible in the logs (several
redemptions all reporting the same `redeemed_count`). The suite detects the bug
it exists to detect.

### Rule ordering is deliberate

Rules run **expiry → per-customer → capacity**. A dead coupon is dead for
everyone, so expiry outranks the rest. The per-customer rule comes before the
global cap because it is more specific to the requester: a customer who already
holds the coupon should be told exactly that, not the misleading "no redemptions
left" they would get from a fully subscribed coupon.

### `GET /coupons/:code` is correct, not eventually correct

It is a plain `SELECT` of the committed row. No cache, no denormalised counter,
no asynchronous projection — nothing that could lag. `tests/` includes a reader
process that polls the count during a two-process redemption burst and asserts
every sampled value is legal, not just the final one.

### Money

Every monetary value is a `Decimal`, rounded `ROUND_HALF_UP` to two places, and
rendered to JSON **as a string** (`"800.00"`, not `800.0`) — emitting it as a JSON
number would convert it to a binary float at the last step and reintroduce
exactly the rounding error the service avoids everywhere else.

`Order.amount` is the original amount and is never mutated. The discounted total
is *derived* from it and the coupon percentage, so the two cannot drift apart and
cancellation needs no monetary reversal.

## Architecture

```
redemption/
  models.py        entities + the check constraints and partial index
  errors.py        AppError hierarchy: code, message, correlation_id, context
  clock.py         Clock ABC - lets expiry tests sit exactly on the boundary
  pricing.py       DiscountCalculator ABC
  repositories/    persistence ABCs + Django implementations
  policies/        one rule per class, composed per coupon type
  services/        one service per endpoint; owns the transaction boundaries
  api/             serializers (boundary validation), views, error rendering
  observability/   correlation-id contextvar + JSON log formatter
  container.py     composition root - the only place concretes are named
```

Dependencies are injected at URL-binding time, since DRF constructs views itself:

```python
path("redeem", RedeemView.as_view(service=build_redemption_service()), name="redeem")
```

No service resolves its own collaborators, and no module-level singletons are
used. Injecting the `Clock` is what lets the expiry suite test the exact
`expires_at` instant without sleeping.

## Deviations from the brief, and why

These are judgement calls; all are reversible.

1. **Cancellation decrements `redeemed_count`.** The brief says "incremented",
   but also "reverses the coupon redemption" and "not a double refund of the
   slot". Refunding a slot means returning it to the pool, so `-1`.

2. **`GET /coupons/:code` returns `remaining = max_redemptions - redeemed_count`.**
   The brief writes `remaining: max_redemptions`; both fields are returned so the
   response is unambiguous either way.

3. **Two endpoints were added.** The brief defines a `User` entity with no way to
   create one, and `POST /redeem` carries no amount while `Order` has an `amount`
   field and the sanity test requires a real discount. So `POST /users` and
   `POST /orders` seed those, and redemption attaches a coupon to an existing
   order.

4. **STANDARD means "once among *active* orders".** Cancelling frees both the
   global slot and that customer's personal use. The alternative — one lifetime
   use per customer — would need the partial index's `status = 'PLACED'`
   predicate dropped.

5. **`order_id` is the only idempotency key.** The `Idempotency-Key` header is
   accepted and validated to match `order_id`, but the `Order` row *is* the
   claim. One consequence, by design: a replay recomputes `remaining` from the
   coupon's live state, so it can differ from the original response if other
   redemptions landed in between. The monetary fields do not change.

6. **A repository layer was added**, which the project's layering note does not
   list. Without it "constructor injection only" would be vacuous — services
   would reach for `Coupon.objects` directly and the locking would not be
   substitutable. The interfaces are deliberately narrow.

7. **Business failures roll the transaction back entirely** rather than
   persisting a failed-attempt record. A retry therefore re-evaluates from
   scratch, which is what you want: "no redemptions left" should be allowed to
   become "redeemed" once somebody cancels.

## Test coverage

68 tests, every invariant covered in both its happy and failing direction.

- **Sanity** — discount arithmetic, half-up rounding, parts reconciling against
  the original, money never a float.
- **Expiry** — before, **exactly at** `expires_at` (allowed), one microsecond
  after (rejected), via an injected clock.
- **Types** — STANDARD once per customer; a different customer unaffected;
  STACKABLE unrestricted; cancel frees the customer; the partial index rejecting
  a duplicate written directly to the database.
- **Idempotency** — repeat redeems, replays reporting the same discount, a
  different coupon on a taken order, cancelled orders not replaying as success,
  and 10 concurrent retries of one key producing exactly one redemption.
- **Cancellation** — the slot released, a second cancel a no-op, repeated
  cancels never going negative, the freed slot genuinely reusable.
- **Load, threads** — 50 threads chasing 10 slots; a reader sampling throughout;
  interleaved redeem/cancel traffic.
- **Load, processes** — two spawned OS processes racing for a fixed cap, an
  assertion that **both** processes win slots (otherwise they never overlapped
  and the test proved nothing), a redeem process racing a cancel process, and a
  third reader process that never observes an illegal count.
