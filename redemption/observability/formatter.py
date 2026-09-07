"""JSON log formatting for stdlib logging."""

import json
import logging
from datetime import datetime, timezone

from redemption.observability.correlation import get_correlation_id

_RESERVED_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Renders log records as single-line JSON with correlation id and extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record to a JSON string.

        Args:
            record: Record to serialise; any ``extra=`` fields are merged in.

        Returns:
            A single-line JSON document.
        """
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            # Stamped by CorrelationIdFilter when the record was emitted. The
            # context variable is only a fallback, for records logged outside a
            # request or by a handler with no filter attached.
            "correlation_id": getattr(record, "correlation_id", "")
            or get_correlation_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and key != "correlation_id":
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)
