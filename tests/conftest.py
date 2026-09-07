"""Shared pytest fixtures.

Tests run against real Postgres. SQLite cannot model ``SELECT ... FOR UPDATE``,
so it would make the concurrency suite vacuous.
"""

import logging

import pytest
from django.db import connection
from rest_framework.test import APIClient

from redemption.container import (
    build_cancellation_service,
    build_coupon_query_service,
    build_redemption_service,
)
from redemption.services.interfaces import (
    CancellationService,
    CouponQueryService,
    RedemptionService,
)


def pytest_configure() -> None:
    """Quieten per-redemption info logging so failure output stays readable.

    The load suites emit one record per redemption; at 40-plus redemptions a
    single failure would otherwise bury its own assertion in captured output.
    """
    logging.getLogger("redemption").setLevel(logging.WARNING)


@pytest.fixture
def api_client() -> APIClient:
    """Provide a DRF test client.

    Returns:
        An unauthenticated API client.
    """
    return APIClient()


@pytest.fixture
def redemption_service() -> RedemptionService:
    """Provide a redemption service wired with the system clock.

    Returns:
        A fully wired redemption service.
    """
    return build_redemption_service()


@pytest.fixture
def cancellation_service() -> CancellationService:
    """Provide a cancellation service.

    Returns:
        A fully wired cancellation service.
    """
    return build_cancellation_service()


@pytest.fixture
def coupon_query_service() -> CouponQueryService:
    """Provide a coupon query service.

    Returns:
        A fully wired coupon query service.
    """
    return build_coupon_query_service()


@pytest.fixture
def test_db_name() -> str:
    """Expose the active test database name.

    Child processes in the multi-process load tests are given this explicitly
    rather than deriving it, since they bootstrap Django from scratch and would
    otherwise connect to the development database.

    Returns:
        The name of the database the current connection is using.
    """
    return connection.settings_dict["NAME"]
