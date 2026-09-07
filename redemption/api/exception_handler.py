"""Maps exceptions to the service's single error response shape."""

import logging
from typing import Any

from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from redemption.errors import AppError, ValidationError

logger = logging.getLogger(__name__)


def app_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Render domain and framework errors as ``{success, error}`` payloads.

    Args:
        exc: The raised exception.
        context: DRF handler context, containing the view and request.

    Returns:
        A rendered error response, or None to let Django handle the exception
        as an unhandled server error.
    """
    if isinstance(exc, drf_exceptions.ValidationError):
        exc = ValidationError(
            "Request rejected because the payload is invalid.",
            fields=exc.detail,
        )

    if isinstance(exc, AppError):
        payload = exc.to_dict()
        logger.warning(
            "request failed: %s",
            exc.message,
            extra={"error_code": exc.code, **exc.context},
        )
        return Response(
            {"success": False, "error": payload},
            status=exc.http_status,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = getattr(exc, "detail", str(exc))
    wrapped = AppError(str(detail))
    wrapped.code = getattr(exc, "default_code", "APP_ERROR").upper()
    wrapped.http_status = response.status_code
    logger.warning(
        "request failed: %s", detail, extra={"error_code": wrapped.code}
    )
    response.data = {"success": False, "error": wrapped.to_dict()}
    return response
