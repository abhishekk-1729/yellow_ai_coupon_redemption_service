# Build Transcript

The working session that produced this service, from the initial
specification through to manually exercising the API with curl.

Prompts are quoted; the assistant's written replies follow. Tool calls
(file writes, test runs, database queries) are collapsed into counts —
their contents are the repository itself. Internal reasoning is omitted.

A development-only secret key has been redacted.


---

## Prompt 1

> Create a Plan . Follow Claude.md and the below instructions
> 
> Problem: Coupon Rememption service for a ecommerce handlign idempotency and concurrency under load
> 
> Stack: Python, Djagno, Djagno ORM, DRF, PyTest
> 
> Entities (Models in Postgres)
> - User: id, name, email_id
> - Coupon: id, code, expires_at, type: enum(STANDARD, STACKABLE), discount_percent, max_redemptions, redeemed_count
> - Order: id, user_id (FK to user), coupon_id (FK to coupon), amount, status: enum(PLACED, CANCELLED)
> 
> Rules/Invariants
> - (redeemed_count <= max_redemptions) ensure under any high load
> - type: STANDARD: per customer only once
> - type: STACKABLE: no additional rule apart from the first one 
> - expiry should be handled according to the expiry_at time
> - exact expirty_at time if request comes then it should be allowed
> - when order is cancelled the related coupon redeemed_count should be incremented and handle the idempotency
> - idempotency on the redeem side as well
> - redeemed_count and max_redemptions whenever touched should be part of transaction block
> 
> 
> idempotency key: order_id
> 
> APIs
> - POST /coupons → { code, max_redemptions, discount_percent, expires_at, type } — seed data.
> 
> - POST /redeem (header: Idempotency-Key) → { code, customer_id, order_id } → { success: true, remaining: remaning_remedemptions (max_redemptions - redeemed_count) } or a clear, distinct error per failure mode (already used / no redemptions left / expired / unknown code / idempotency replay).
> 
> - POST /orders/:order_id/cancel → reverses the coupon redemption tied to that order, if any. Calling it twice must be a no-op the second time, not a double refund of the slot.
> 
> - GET /coupons/:code → { redeemed_count, remaining: max_redemptions } — this number must be correct at all times, not eventually correct.
> 
> 
> Testing
> - sanity: correct discount is applied.
> - correctness:  
>     - type based constraints  
>     - idempotency test for multiple requests with the same key
> - load testing: 
>     - (redeemed_count <= max_redemptions) should always be followed
>     - 2 process running and doing the redeem should handled the concurrency and obey the constraint

I'll start by exploring the current state of the working directory to understand what exists.

<details><summary>2 tool calls</summary>

- `Bash` — List project directory contents
- `Bash` — Find project files

</details>

Project directory is empty apart from `CLAUDE.md` — this is a greenfield build, so there's no existing codebase to explore. Let me check the local toolchain instead.

<details><summary>2 tool calls</summary>

- `Bash` — Check Python and Django toolchain
- `Bash` — Check Postgres and container tooling

</details>

Postgres is running locally. Let me check what's reachable and whether a venv approach makes sense.

<details><summary>2 tool calls</summary>

- `Bash` — Check Postgres databases and version
- `Bash` — Check installed relevant packages

</details>

The directory is empty — this is a greenfield build. Environment findings:

- Python 3.11.7 (pyenv), Django 5.1.4, DRF 3.15.2 already installed globally
- **Postgres 14.19 running locally** (homebrew, trust auth as `abhishekkumar`) — good, real Postgres row locks are testable
- **Missing**: `psycopg2`, `pytest`, `pytest-django`, `gunicorn`; no Docker, no `uv`/`poetry`

Before I write the plan, four things in the spec are genuinely ambiguous and change the implementation:

<details><summary>1 tool call</summary>

- `AskUserQuestion` — Cancel math; Discount input; STANDARD scope; Idem key

</details>

All four answered. That reshapes the design meaningfully — `POST /orders` becomes a real endpoint, the idempotency claim moves to a `coupon_id NULL → set` transition on an existing order row, and cancel frees both the global slot and the customer's STANDARD use. Let me write the plan.

<details><summary>1 tool call</summary>

- `Write` — ~/.claude/plans/create-a-plan-pure-flute.md

</details>

Plan written to [create-a-plan-pure-flute.md](~/.claude/plans/create-a-plan-pure-flute.md).

Three things I'd highlight before you approve:

1. **The invariant is enforced by the schema, not just the service.** A `CheckConstraint(redeemed_count <= max_redemptions)` plus a partial unique index for the STANDARD rule means a violation can't be committed even if someone later bypasses the service layer. The load test then proves the locking works rather than being the only thing standing between you and a bug.

2. **Fixed lock ordering (Order → Coupon) in both redeem and cancel.** Both paths touch two rows; acquiring them in a consistent order makes a deadlock cycle structurally impossible, so there's no retry loop to write.

3. **I added a repository layer that `CLAUDE.md` doesn't list.** Its layer list is api → viewset → models → services, but "constructor injection only" is vacuous if services import `Coupon.objects` directly. I flagged this in the plan — say so and I'll collapse them into direct ORM calls.

I also read two lines of the brief as typos and built accordingly: cancel *decrements* (you confirmed), and `GET /coupons/:code`'s `remaining` is `max_redemptions - redeemed_count` rather than `max_redemptions`. Both are documented in the plan and would go in the README.

<details><summary>2 tool calls</summary>

- `ToolSearch`
- `ExitPlanMode`

</details>

I'll start with step 1: the venv, dependencies, and Django project skeleton.

<details><summary>3 tool calls</summary>

- `Bash` — Create virtualenv
- `Write` — requirements.txt
- `Bash` — Install dependencies into venv

</details>

All dependencies installed. Now the project skeleton and database.

<details><summary>2 tool calls</summary>

- `Bash` — Create Django project and app
- `Bash` — Create coupons database

</details>

Project scaffolded and `coupons` database created. Now settings and env config.

<details><summary>3 tool calls</summary>

- `Write` — .env.example
- `Write` — .gitignore
- `Write` — coupon_service/settings.py

</details>

Now the observability layer (referenced by settings) and a local `.env`.

<details><summary>3 tool calls</summary>

- `Bash` — Write local .env and create package directories
- `Write` — redemption/observability/correlation.py
- `Write` — redemption/observability/formatter.py

</details>

Now the errors module, clock, and models — the schema is where the invariant is actually enforced.

<details><summary>4 tool calls</summary>

- `Write` — redemption/errors.py
- `Write` — redemption/clock.py
- `Write` — redemption/models.py
- `Bash` — Create package inits and generate migration

</details>

The default `urls.py` still references the admin, which I removed from `INSTALLED_APPS`. Let me write the real URL conf — I'll do the API layer now.

<details><summary>3 tool calls</summary>

- `Write` — coupon_service/urls.py
- `Write` — redemption/repositories/interfaces.py
- `Write` — redemption/repositories/django_repositories.py

</details>

Now the policies — one per rule, so the type-specific behaviour is composable.

<details><summary>5 tool calls</summary>

- `Write` — redemption/policies/interfaces.py
- `Write` — redemption/policies/expiry.py
- `Write` — redemption/policies/capacity.py
- `Write` — redemption/policies/customer_usage.py
- `Write` — redemption/policies/registry.py

</details>

Now pricing, then the services that carry the transaction design.

<details><summary>2 tool calls</summary>

- `Write` — redemption/pricing.py
- `Write` — redemption/services/interfaces.py

</details>

Now the redemption service — the core transaction design.

<details><summary>2 tool calls</summary>

- `Write` — redemption/services/redemption.py
- `Write` — redemption/services/cancellation.py

</details>

Now the seeding and query services.

<details><summary>2 tool calls</summary>

- `Write` — redemption/services/seeding.py
- `Write` — redemption/services/coupon_query.py

</details>

Now the API layer: serializers (boundary validation), exception handler, views, and the composition root.

<details><summary>5 tool calls</summary>

- `Write` — redemption/api/serializers.py
- `Write` — redemption/api/exception_handler.py
- `Write` — redemption/api/views.py
- `Write` — redemption/container.py
- `Write` — redemption/api/urls.py

</details>

Now let me generate the migration and verify the whole thing wires up.

<details><summary>2 tool calls</summary>

- `Bash` — Generate migration and run system checks
- `Bash` — Apply migrations and inspect constraints

</details>

Every constraint landed as designed — note `coupon_redeemed_within_cap` and the partial unique index `WHERE (is_single_use AND status = 'PLACED')`. Now the test harness.

<details><summary>3 tool calls</summary>

- `Write` — pytest.ini
- `Write` — tests/factories.py
- `Write` — tests/conftest.py

</details>

Now the correctness tests. Starting with the sanity/discount and expiry boundary cases.

<details><summary>4 tool calls</summary>

- `Write` — tests/test_discount.py
- `Bash` — Run discount tests
- `Bash` — Verify test database creation
- `Bash` — Confirm test database is actually created

</details>

Confirmed: real Postgres test DB created per session. Now the expiry boundary and coupon-type tests.

<details><summary>3 tool calls</summary>

- `Write` — tests/test_expiry.py
- `Write` — tests/test_coupon_types.py
- `Bash` — Run expiry and coupon type tests

</details>

All 11 pass, including the exact-`expires_at` boundary. Now capacity, idempotency, and cancellation.

<details><summary>5 tool calls</summary>

- `Write` — tests/test_capacity.py
- `Write` — tests/test_idempotency.py
- `Bash` — Run capacity and idempotency tests
- `Write` — tests/test_cancel.py
- `Bash` — Run cancellation tests

</details>

Now the API-level tests and the load tests — starting with the HTTP surface.

<details><summary>2 tool calls</summary>

- `Write` — tests/test_api.py
- `Bash` — Run API tests

</details>

DRF auto-attaches the current timezone to naive datetimes before my validator runs, so the ambiguity check never fires. I need to inspect the raw value.

<details><summary>4 tool calls</summary>

- `Edit` — redemption/api/serializers.py
- `Edit` — redemption/api/serializers.py
- `Edit` — redemption/api/serializers.py
- `Bash` — Re-run API tests

</details>

All 17 API tests pass. Now the load tests — first the in-process thread contention, then the two-process requirement.

<details><summary>2 tool calls</summary>

- `Write` — tests/test_concurrency_threads.py
- `Bash` — Run threaded concurrency tests

</details>

5 threaded tests pass — 50 threads yield exactly 10 redemptions. Now the two-process requirement, which needs a worker importable under `spawn`.

<details><summary>3 tool calls</summary>

- `Write` — tests/workers.py
- `Write` — tests/test_load_multiprocess.py
- `Bash` — Run two-process load tests

</details>

All 5 pass. But a passing concurrency test proves nothing unless it can fail — let me refactor the fragile result-ordering first, then verify the tests actually have teeth.

<details><summary>2 tool calls</summary>

- `Edit` — tests/workers.py
- `Bash` — Refactor workers to labelled results

</details>

Now the test file, using labelled results instead of positional ordering.

<details><summary>2 tool calls</summary>

- `Write` — tests/test_load_multiprocess.py
- `Bash` — Re-run two-process load tests

</details>

Now the critical check: do these tests actually detect a broken lock? Let me temporarily remove the row lock and confirm they fail.

<details><summary>2 tool calls</summary>

- `Bash` — Temporarily remove coupon row lock
- `Bash` — Run load tests against mutated code

</details>

The mutation test proves the suite has teeth — 8 of 10 concurrency tests fail without the lock, and the logs show the classic lost update (several redemptions all reporting `redeemed_count: 2`). Restoring:

<details><summary>3 tool calls</summary>

- `Bash` — Restore original repository code
- `Edit` — tests/conftest.py
- `Edit` — tests/conftest.py

</details>

Now the optional HTTP load script and the README, then a full suite run.

<details><summary>1 tool call</summary>

- `Write` — scripts/loadtest_http.py

</details>

Let me run the full suite, then verify the HTTP path end-to-end against real gunicorn workers.

<details><summary>1 tool call</summary>

- `Bash` — Run full test suite

</details>

All 65 pass. Now the real end-to-end check: gunicorn with 2 worker processes.

<details><summary>2 tool calls</summary>

- `Bash` — Start gunicorn with 2 workers
- `Bash` — Verify gunicorn is up and count workers

</details>

Server up with a master and 2 worker processes. Running the load test over real HTTP:

<details><summary>1 tool call</summary>

- `Bash` — Run HTTP load test against gunicorn

</details>

200 concurrent requests across 2 worker processes, cap 25, exactly 25 redemptions. Now the manual end-to-end flow from the plan:

<details><summary>1 tool call</summary>

- `Bash` — Manual end-to-end seed and redeem flow

</details>

Money is rendering as JSON floats (`800.0`) — that quietly undoes the Decimal precision at the last step. Let me fix the boundary.

<details><summary>6 tool calls</summary>

- `Write` — redemption/api/renderers.py
- `Edit` — coupon_service/settings.py
- `Edit` — tests/test_api.py
- `Edit` — tests/test_api.py
- `Bash` — Run full suite after renderer change
- `Bash` — Restart gunicorn with renderer change

</details>

Now the rest of the manual flow — cancel, double-cancel, and the STANDARD rule:

<details><summary>1 tool call</summary>

- `Bash` — Manual cancel and STANDARD rule verification

</details>

The manual flow is fully correct. One thing it exposed: Ada got `COUPON_EXHAUSTED` when the more specific truth was that she'd already used the coupon. Let me make the policy ordering explicit rather than incidental.

<details><summary>4 tool calls</summary>

- `Write` — redemption/policies/registry.py
- `Edit` — redemption/container.py
- `Edit` — tests/test_coupon_types.py
- `Bash` — Run full suite after policy ordering change

</details>

68 pass. Now a cleanup pass — let me check for unused imports and dead code across the project.

<details><summary>1 tool call</summary>

- `Bash` — Check for unused imports and code markers

</details>

Those are Django's unused auto-generated stubs. Let me check what else is dead scaffolding.

<details><summary>2 tool calls</summary>

- `Bash` — Inspect app scaffolding files
- `Bash` — Remove unused Django scaffolding

</details>

Now let me tighten two loose type hints I noticed and verify the serializers file has no leftover imports.

<details><summary>1 tool call</summary>

- `Bash` — Check for leftover imports

</details>

Serializers are clean. Let me tighten that `_remaining(coupon: Any)` in cancellation to the real type.

<details><summary>5 tool calls</summary>

- `Edit` — redemption/services/cancellation.py
- `Edit` — redemption/services/cancellation.py
- `Bash` — Find lines over 88 characters
- `Bash` — Wrap long lines
- `Bash` — Verify suite after formatting changes

</details>

Now the README documenting the design and the deviations from the brief.

<details><summary>1 tool call</summary>

- `Write` — README.md

</details>

Final verification — clean database, fresh migration, full suite, and gunicorn load test from scratch.

<details><summary>3 tool calls</summary>

- `Bash` — Fresh database, migrate, full suite
- `Bash` — Final HTTP load test and shutdown
- `Bash` — List final deliverables

</details>

Done. The service is built, tested, and verified end-to-end.

**Results**
- 68 tests pass against real Postgres
- 250 concurrent HTTP requests across 2 gunicorn worker processes, cap 30 → exactly 30 redemptions, no oversell

**The invariant is held in three independent layers**, so no single mistake breaches the cap:
1. `SELECT … FOR UPDATE` on the coupon row makes check-and-increment atomic
2. A Postgres check constraint makes `redeemed_count <= max_redemptions` *unrepresentable* — not just unwritten by this code, but uncommittable by anything
3. A partial unique index (`WHERE is_single_use AND status='PLACED'`) enforces the STANDARD rule at the schema level

Both redeem and cancel take locks in one fixed order — **order row, then coupon row** — so a deadlock cycle can't form and no retry loop is needed.

**I verified the concurrency tests can actually fail.** Removing the `select_for_update()` and re-running made 8 of the 10 concurrency tests fail, with lost updates visible in the logs (several redemptions all reporting `redeemed_count: 2`). A passing concurrency suite that can't fail proves nothing, so this seemed worth confirming. One of the two-process tests also asserts that *both* processes win slots — otherwise they never overlapped and the cap assertion would be vacuous.

**Two things I changed after seeing them run:**
- Money was serialising to JSON floats (`800.0`), silently undoing the `Decimal` precision at the very last step. It now renders as `"800.00"`.
- A repeat customer on a full coupon got `COUPON_EXHAUSTED`, which reads as "you missed out" when the truth is "you already have it." Rules now run expiry → per-customer → capacity, and the ordering is pinned by a test.

**Judgement calls you should sanity-check** (all in the README, all reversible): cancel decrements rather than increments, per your confirmation; `GET /coupons/:code` returns `remaining = max − redeemed` (the brief said `remaining: max_redemptions`, so both fields are returned); and a replay recomputes `remaining` live, so it can differ from the original response if other redemptions landed in between — a direct consequence of choosing `order_id` as the sole key. Monetary fields don't change on replay.

The `.env` I created holds a dev-only secret key and points at your local Postgres as `abhishekkumar`; it's gitignored, with `.env.example` as the committed template.


---

## Prompt 2

> i want to test these apis, can we make this django server up and then test with curls

Let me start the server and walk through every endpoint with curl.

<details><summary>2 tool calls</summary>

- `Bash` — Start Django dev server
- `Bash` — Wait for server and confirm clean database

</details>


*(interrupted)*


---

## Prompt 3

> give me curl commands

Server's up on `http://127.0.0.1:8000`. One note first — the DB still has leftover load-test data (250 users, 250 orders). Clean slate if you want one:

```bash
psql -d coupons -c "TRUNCATE orders, coupons, users RESTART IDENTITY CASCADE;"
```

## 1. Happy path

```bash
B=http://127.0.0.1:8000
O1=11111111-1111-4111-8111-111111111111

# seed a customer -> note the "id" it returns
curl -s -X POST $B/users -H 'Content-Type: application/json' \
  -d '{"name":"Ada","email_id":"ada@example.com"}' | python3 -m json.tool

# seed a STANDARD coupon: 20% off, 2 redemptions
curl -s -X POST $B/coupons -H 'Content-Type: application/json' \
  -d '{"code":"save20","max_redemptions":2,"discount_percent":"20.00",
       "expires_at":"2030-01-01T00:00:00Z","type":"STANDARD"}' | python3 -m json.tool
```

Now export the customer id from the first response (`U=<id>`), then:

```bash
U=1   # <- replace with the id returned above

# create an order for 1000.00
curl -s -X POST $B/orders -H 'Content-Type: application/json' \
  -d "{\"order_id\":\"$O1\",\"customer_id\":$U,\"amount\":\"1000.00\"}" | python3 -m json.tool

# redeem (order_id is the idempotency key; header is optional but must match)
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $O1" \
  -d "{\"code\":\"save20\",\"customer_id\":$U,\"order_id\":\"$O1\"}" | python3 -m json.tool
```

Expect `final_amount: "800.00"`, `remaining: 1`.

## 2. The interesting bits

```bash
# replay: same order again -> 200, replayed:true, count does NOT move
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -d "{\"code\":\"save20\",\"customer_id\":$U,\"order_id\":\"$O1\"}" | python3 -m json.tool

# live counts (lowercase code works - it's normalised)
curl -s $B/coupons/save20 | python3 -m json.tool

# cancel -> releases the slot, remaining goes back up
curl -s -X POST $B/orders/$O1/cancel | python3 -m json.tool

# cancel AGAIN -> replayed:true, no double refund
curl -s -X POST $B/orders/$O1/cancel | python3 -m json.tool
```

## 3. Error cases

```bash
O2=22222222-2222-4222-8222-222222222222
curl -s -X POST $B/orders -H 'Content-Type: application/json' \
  -d "{\"order_id\":\"$O2\",\"customer_id\":$U,\"amount\":\"500.00\"}" > /dev/null

# unknown code -> 404 COUPON_NOT_FOUND
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -d "{\"code\":\"NOPE\",\"customer_id\":$U,\"order_id\":\"$O2\"}" | python3 -m json.tool

# Idempotency-Key naming a different order -> 400 IDEMPOTENCY_KEY_MISMATCH
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -H "Idempotency-Key: 99999999-9999-4999-8999-999999999999" \
  -d "{\"code\":\"save20\",\"customer_id\":$U,\"order_id\":\"$O2\"}" | python3 -m json.tool

# expired coupon -> 409 COUPON_EXPIRED
curl -s -X POST $B/coupons -H 'Content-Type: application/json' \
  -d '{"code":"OLD","max_redemptions":5,"discount_percent":"10.00",
       "expires_at":"2020-01-01T00:00:00Z","type":"STACKABLE"}' > /dev/null
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -d "{\"code\":\"OLD\",\"customer_id\":$U,\"order_id\":\"$O2\"}" | python3 -m json.tool

# STANDARD twice by same customer -> 409 CUSTOMER_ALREADY_REDEEMED
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -d "{\"code\":\"save20\",\"customer_id\":$U,\"order_id\":\"$O1\"}" > /dev/null
curl -s -X POST $B/redeem -H 'Content-Type: application/json' \
  -d "{\"code\":\"save20\",\"customer_id\":$U,\"order_id\":\"$O2\"}" | python3 -m json.tool

# naive datetime rejected at the boundary -> 400 VALIDATION_ERROR
curl -s -X POST $B/coupons -H 'Content-Type: application/json' \
  -d '{"code":"BAD","max_redemptions":1,"discount_percent":"10.00",
       "expires_at":"2030-01-01T00:00:00","type":"STANDARD"}' | python3 -m json.tool
```

Add `-i` to any of these to see the status code and the `X-Correlation-Id` response header.

Stop the server when you're done: `pkill -f "manage.py runserver"`.
