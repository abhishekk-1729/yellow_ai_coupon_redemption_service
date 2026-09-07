"""Correlation id propagation across a request's log records."""

import uuid
from contextvars import ContextVar
from typing import Callable

from django.http import HttpRequest, HttpResponse

CORRELATION_ID_HEADER = "X-Correlation-Id"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the correlation id bound to the current execution context.

    Returns:
        The active correlation id, or an empty string outside a request.
    """
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id to the current execution context.

    Args:
        correlation_id: Identifier to associate with subsequent log records.
    """
    _correlation_id.set(correlation_id)


class CorrelationIdMiddleware:
    """Assigns every request a correlation id and echoes it on the response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Store the next handler in the middleware chain.

        Args:
            get_response: Next callable in the Django middleware chain.
        """
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Bind a correlation id for the duration of the request.

        Args:
            request: Incoming request; an inbound ``X-Correlation-Id`` is reused.

        Returns:
            The downstream response with the correlation id header set.
        """
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        token = _correlation_id.set(correlation_id)
        try:
            response = self._get_response(request)
            response[CORRELATION_ID_HEADER] = correlation_id
            return response
        finally:
            _correlation_id.reset(token)
