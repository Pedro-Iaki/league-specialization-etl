import time
from threading import RLock
import requests
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type, before_sleep_log
from loguru import logger

class RiotAPIClient:
    def __init__(self, api_key: str):
        self.buckets: list['TokenBucket'] = []
        self.session = requests.Session()
        self.session.headers.update({"X-Riot-Token": api_key})

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        before_sleep=before_sleep_log(logger, "WARNING")
    )
    def get(self, url: str, **kwargs) -> requests.Response:
        if self.buckets:
            for b in self.buckets:
                while not b.peek():  # We don't consume yet, in case one is valid and the other holds us up.
                    sleep_time = b.period / b.rate_limit
                    time.sleep(sleep_time)
            for b in self.buckets:
                b.consume()

        response = self.session.get(url, timeout=30, **kwargs)

        if not self.buckets:
            rate_limit_header = response.headers.get("X-App-Rate-Limit")
            if rate_limit_header:
                self.buckets = self.setup_buckets(rate_limit_header)
                for b in self.buckets:
                    b.consume()  # Consume a token for the current request to ensure we start it right
        
        if response.status_code == 429:
            logger.warning("429 Too Many Requests received, rate limited")

        response.raise_for_status()
        return response

    def setup_buckets(self, rate_limit_header: str) -> list['TokenBucket']:
        limits = []
        for limit_pair in rate_limit_header.split(','):
            limit, period = limit_pair.strip().split(':')
            limits.append((int(limit), int(period)))

        buckets = []
        for limit, period in limits:
            buckets.append(TokenBucket(limit, period))
        
        return buckets


class TokenBucket:
    def __init__(self, rate_limit: int, period: int):
        self.rate_limit = rate_limit
        self.period = period
        self.tokens = float(rate_limit)
        self.last_checked = time.monotonic()
        self.lock = RLock()  # prevents freeze when consume() calls peek()

    def peek(self) -> bool:
        with self.lock:
            current_time = time.monotonic()
            elapsed = current_time - self.last_checked

            refill_tokens = (elapsed / self.period) * self.rate_limit
            self.tokens = min(float(self.rate_limit), self.tokens + refill_tokens)
            self.last_checked = current_time

            return self.tokens >= 1

    def consume(self) -> bool:
        with self.lock:
            if self.peek():
                self.tokens -= 1
                return True
            else:
                return False