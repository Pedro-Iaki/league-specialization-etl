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
		before_sleep=before_sleep_log(logger, "WARNING") # type: ignore
	)
	def get_patch(self):
		latest_patch = "https://ddragon.leagueoflegends.com/api/versions.json"
		patch = self.session.get(latest_patch).json()[0]
		if patch is None:
			logger.error("Failed to fetch the latest patch version.")
		return patch
	
	@retry(
		wait=wait_exponential(multiplier=1, min=2, max=30),
		stop=stop_after_attempt(5),
		retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
		before_sleep=before_sleep_log(logger, "WARNING") # type: ignore
	)
	def get(self, url: str, **kwargs) -> requests.Response:
		if self.buckets:
			for b in self.buckets:
				while not all(b.peek() for b in self.buckets): # We dont consume yet to avoid wasting tokens if we have to wait
					longest_sleep = max(b.period / b.rate_limit for b in self.buckets if not b.peek())
					time.sleep(longest_sleep)
			for b in self.buckets:
				b.consume()
			logger.info(f"Efficiency at {max(b.calculate_efficiency() for b in self.buckets):.2f}%")

		response = self.session.get(url, timeout=30, **kwargs)

		if not self.buckets:
			rate_limit_header = response.headers.get("X-App-Rate-Limit")
			if rate_limit_header:
				self.buckets = self.setup_buckets(rate_limit_header)
				for b in self.buckets:
					b.consume()  # Consume a token for the current request to ensure we start it right away
		
		if response.status_code == 429:
			logger.warning("429 Too Many Requests received, rate limited")
		elif response.status_code == 401:
			logger.error("401 Unauthorized received, invalid API key. Please check your RIOT_API_KEY environment variable.")

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
		self.tokens = 0
		self.last_checked = time.monotonic()
		self.lock = RLock()  # prevents freeze when consume() calls peek()
		self.successes = 0
		self.total_time = 0.0

	def peek(self) -> bool:
		with self.lock:
			current_time = time.monotonic()
			elapsed = current_time - self.last_checked
			self.total_time = self.total_time + elapsed

			refill_tokens = (elapsed / self.period) * self.rate_limit
			self.tokens = min(float(self.rate_limit), self.tokens + refill_tokens)
			self.last_checked = current_time

			return self.tokens >= 1
			
	def consume(self) -> bool:
		with self.lock:
			if self.peek():
				self.successes = self.successes + 1
				self.tokens -= 1
				return True
			else:
				return False
	
	def calculate_efficiency(self) -> float:
		ideal_throughput = (self.rate_limit / self.period)
		actual_throughput = (self.successes / self.total_time) if self.total_time > 0 else 0
		efficiency = (actual_throughput / ideal_throughput) * 100 if ideal_throughput > 0 else 0
		return efficiency