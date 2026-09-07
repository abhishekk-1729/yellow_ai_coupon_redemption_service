"""JSON rendering that preserves decimal precision.

Every monetary value is a :class:`~decimal.Decimal` internally. DRF's default
encoder emits decimals as JSON numbers, which converts them to binary floats and
reintroduces exactly the rounding error the service avoids everywhere else.
Money is rendered as a string instead, so ``"800.00"`` reaches the client
unchanged.
"""

from decimal import Decimal
from typing import Any

from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder


class DecimalPreservingJSONEncoder(JSONEncoder):
    """Encodes decimals as strings rather than floats."""

    def default(self, obj: Any) -> Any:
        """Serialise values the base encoder cannot handle natively.

        Args:
            obj: Value being encoded.

        Returns:
            A JSON-serialisable representation of ``obj``.
        """
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class DecimalPreservingJSONRenderer(JSONRenderer):
    """JSON renderer that keeps decimals exact."""

    encoder_class = DecimalPreservingJSONEncoder
