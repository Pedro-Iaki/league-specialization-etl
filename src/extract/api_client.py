import time
from threading import Lock, RLock

import requests
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _log_retry(retry_state) -> None:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(f"Retrying request after attempt {retry_state.attempt_number}: {exception}")


class RiotAPIClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({"X-Riot-Token": api_key})

        self.buckets: list[TokenBucket] = []

        self._setup_lock = Lock()

        self._rate_limit_lock = Lock()

    @retry(
        wait=wait_exponential(multiplier=6, min=1, max=90),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        before_sleep=_log_retry,
    )
    def get_patch(self) -> str:
        latest_patch = "https://ddragon.leagueoflegends.com/api/versions.json"

        response = self.session.get(latest_patch, timeout=30)
        response.raise_for_status()

        patch = response.json()[0]

        if patch is None:
            logger.error("Failed to fetch the latest patch version.")

        return str(patch)

    @retry(
        wait=wait_exponential(multiplier=6, min=1, max=90),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        before_sleep=_log_retry,
    )
    def get(self, url: str, **kwargs) -> requests.Response:
        self._acquire()

        response = self.session.get(url, timeout=30, **kwargs)

        if not self.buckets:
            self._initialize_buckets_from_response(response)

        if response.status_code == 429:
            logger.warning("429 Too Many Requests received, rate limited")

        elif response.status_code == 401:
            logger.error(
                "401 Unauthorized received, invalid API key. Please check your RIOT_API_KEY environment variable."
            )

        response.raise_for_status()
        return response

    def _initialize_buckets_from_response(
        self,
        response: requests.Response,
    ) -> None:
        rate_limit_header = response.headers.get("X-App-Rate-Limit")

        if not rate_limit_header:
            logger.warning("API response did not contain X-App-Rate-Limit. ")
            return

        with self._setup_lock:
            if self.buckets:  # Another thread may have initialized them while this one waited.
                return

            self.buckets = self.setup_buckets(rate_limit_header)

            with self._rate_limit_lock:  # Consume a token for the first request
                for bucket in self.buckets:
                    consumed = bucket.consume()

                    if not consumed:
                        logger.warning(f"Couldn't consume initial token in rate-limit bucket: {bucket}")

            logger.debug(f"Initialized Riot rate limits: {rate_limit_header}")

    def _acquire(self) -> None:
        while True:
            with self._rate_limit_lock:
                if not self.buckets:
                    return

                available = all(bucket.peek() for bucket in self.buckets)

                if available:
                    for bucket in self.buckets:
                        if not bucket.consume():
                            raise RuntimeError("Couldn't consume token from bucket.")
                    return

                # Every rate-limit window must permit the next request.
                wait_time = max(bucket.time_until_available() for bucket in self.buckets)

            # Sleep outside the lock to avoid blocking others.
            if wait_time > 0:
                time.sleep(wait_time)

    @staticmethod
    def setup_buckets(rate_limit_header: str) -> list["TokenBucket"]:
        buckets: list[TokenBucket] = []

        for limit_pair in rate_limit_header.split(","):
            limit, period = limit_pair.strip().split(":")

            rate_limit = int(limit)
            period_seconds = int(period)

            if rate_limit <= 0:
                raise ValueError(f"Invalid rate limit: {rate_limit}")

            if period_seconds <= 0:
                raise ValueError(f"Invalid rate-limit period: {period_seconds}")

            buckets.append(
                TokenBucket(
                    rate_limit=rate_limit,
                    period=period_seconds,
                )
            )

        return buckets


class TokenBucket:
    EPSILON = 1e-12  # Small value to handle floating-point precision issues

    def __init__(self, rate_limit: int, period: int):
        # Apply a safety margin to the rate limit to avoid hitting the exact limit
        self.rate_limit = round(rate_limit * 0.99)
        self.period = period
        self.capacity = float(rate_limit)

        self.tokens = 1.0
        self.last_checked = time.monotonic()

        self.lock = RLock()

    @property
    def refill_rate(self) -> float:
        return self.rate_limit / self.period

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_checked

        if elapsed <= 0:
            return

        self.tokens += elapsed * self.refill_rate

        self.tokens = min(self.capacity, self.tokens)

        # Eliminate microscopic floating-point residue around zero.
        if abs(self.tokens) < self.EPSILON:
            self.tokens = 0.0

        self.last_checked = now

    def peek(self) -> bool:
        with self.lock:
            self._refill()
            return self.tokens >= 1.0

    def consume(self) -> bool:
        with self.lock:
            self._refill()

            if self.tokens < 1.0:
                return False

            self.tokens -= 1.0

            # Protect against tiny floating-point residue.
            if abs(self.tokens) < self.EPSILON:
                self.tokens = 0.0

            if self.tokens < 0:
                self.tokens = 0.0

            return True

    def time_until_available(self) -> float:
        with self.lock:
            self._refill()

            if self.tokens >= 1.0:
                return 0.0

            missing_tokens = 1.0 - self.tokens

            return missing_tokens / self.refill_rate

    def get_state(self) -> dict:
        with self.lock:
            self._refill()

            return {
                "rate_limit": self.rate_limit,
                "period": self.period,
                "capacity": self.capacity,
                "tokens": self.tokens,
                "refill_rate": self.refill_rate,
            }

    def __repr__(self) -> str:
        state = self.get_state()

        return f"TokenBucket(rate_limit={state['rate_limit']}, period={state['period']}, tokens={state['tokens']:.12f})"
