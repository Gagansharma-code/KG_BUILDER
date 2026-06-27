"""Daily DigiKey API request budget tracker."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

DIGIKEY_DAILY_BUDGET = 8_500
TRACKER_PATH = Path("data/population_run/digikey_request_count.json")


class RequestTracker:
    """Daily request budget tracker for DigiKey API.

    Persists {date: str, count: int} to disk.
    Resets automatically when the date changes.
    Thread-safe for single-process use (no locks needed — sequential runner).
    """

    def __init__(self, path: Path = TRACKER_PATH) -> None:
        self.path = path
        self._date: str = ""
        self._count: int = 0
        self._load()

    def _load(self) -> None:
        """Load count from disk. Reset if date has changed."""
        today = date.today().isoformat()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                stored_date = data.get("date", "")
                if stored_date == today:
                    self._date = today
                    self._count = int(data.get("count", 0))
                    return
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                logger.debug("RequestTracker load failed: %s", exc)
        self._date = today
        self._count = 0
        self._save()

    def _save(self) -> None:
        """Persist current date and count to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"date": self._date, "count": self._count}),
            encoding="utf-8",
        )

    def can_request(self) -> bool:
        """True if count < DIGIKEY_DAILY_BUDGET."""
        return self._count < DIGIKEY_DAILY_BUDGET

    def increment(self) -> None:
        """Increment count and save. Call after every DigiKey API request."""
        self._count += 1
        self._save()

    @property
    def remaining(self) -> int:
        """Requests remaining today."""
        return max(0, DIGIKEY_DAILY_BUDGET - self._count)

    @property
    def count(self) -> int:
        return self._count
