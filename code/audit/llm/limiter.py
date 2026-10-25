"""Token-bucket rate limiter and persisted per-day budgets (Phase 4 E4).

TokenBucket enforces requests-per-minute and tokens-per-minute within
one process's lifetime (sliding 60s window); it does not need to
persist across runs since RPM/TPM reset every minute regardless.

DailyBudget is the opposite: it MUST persist across runs (a process
restart must not reset today's quota), so it reads and writes a small
JSON file under `.cache/` keyed by today's UTC date. Used for
`gemini-3.8-flash`'s small daily request budget (D9, D11); every other
provider/model here is comfortably under its own RPM-derived daily
ceiling and does not need a persisted counter.
"""

import json
import sys
import time
from collections import deque
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import config  # noqa: E402

_WINDOW_S = 60.0


class TokenBucket:
    def __init__(self, requests_per_minute: int, tokens_per_minute: int):
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._request_times: deque = deque()
        self._token_events: deque = deque()  # (timestamp, tokens)

    def _evict(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] > _WINDOW_S:
            self._request_times.popleft()
        while self._token_events and now - self._token_events[0][0] > _WINDOW_S:
            self._token_events.popleft()

    def acquire(self, tokens_estimate: int, sleep=time.sleep, now_fn=time.monotonic) -> float:
        """Blocks (via `sleep`) until a call of this size is allowed,
        then records it. Returns total seconds slept, for the caller's
        own latency accounting."""
        slept = 0.0
        now = now_fn()
        self._evict(now)
        while len(self._request_times) >= self.rpm or (
            sum(t for _, t in self._token_events) + tokens_estimate > self.tpm
        ):
            sleep(0.2)
            slept += 0.2
            now = now_fn()
            self._evict(now)
        self._request_times.append(now)
        self._token_events.append((now, tokens_estimate))
        return slept


class DailyBudget:
    """Persisted per-day request counter for one named budget (e.g.
    "gemini-3.8-flash"). `consume()` is atomic read-check-write within
    one process (no cross-process locking -- this pipeline never runs
    two instances against the same .cache/ concurrently)."""

    def __init__(self, name: str, daily_limit: int, path: Path = config.GEMINI_FLASH_DAILY_BUDGET_PATH):
        self.name = name
        self.daily_limit = daily_limit
        self.path = path

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _today_key(self) -> str:
        return date.today().isoformat()

    def used_today(self) -> int:
        return self._load().get(self.name, {}).get(self._today_key(), 0)

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.used_today())

    def consume(self, n: int = 1) -> bool:
        """Returns True and records n requests if today's budget allows
        it; returns False (and records nothing) otherwise."""
        data = self._load()
        today = self._today_key()
        bucket = data.setdefault(self.name, {})
        used = bucket.get(today, 0)
        if used + n > self.daily_limit:
            return False
        bucket[today] = used + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        return True
