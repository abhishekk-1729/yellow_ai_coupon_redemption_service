"""Time source abstraction.

Injecting the clock lets expiry tests sit exactly on the ``expires_at``
boundary instead of sleeping.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from django.utils import timezone


class Clock(ABC):
    """Supplies the current instant."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            A timezone-aware datetime.
        """
        raise NotImplementedError


class SystemClock(Clock):
    """Clock backed by the configured Django timezone."""

    def now(self) -> datetime:
        """Return the current instant from the system clock.

        Returns:
            A timezone-aware datetime in UTC.
        """
        return timezone.now()
