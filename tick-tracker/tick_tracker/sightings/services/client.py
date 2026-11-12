import logging

import requests
from django.conf import settings
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_WAIT = 60  # seconds; the API says "wait a minute"


class TickAPIError(Exception):
    """The source API could not give us usable data."""


class RetryableAPIError(TickAPIError):
    """A temporary failure worth retrying (429, 5xx, timeout, connection error)."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


_backoff = wait_exponential(multiplier=2, min=2, max=60)  # 2s, 4s, 8s, ... capped at 60s


def _wait_strategy(retry_state):
    """Respect the server's Retry-After if it gave one, otherwise back off exponentially."""
    exc = retry_state.outcome.exception()
    if isinstance(exc, RetryableAPIError) and exc.retry_after:
        return exc.retry_after
    return _backoff(retry_state)


class TickAPIClient:
    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or settings.TICK_API_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.TICK_API_TIMEOUT
        self.session = requests.Session()  # reuses the connection between calls
        self.session.headers.update({"Accept": "application/json"})

    # ---- public methods ----------------------------------------------------

    def get_all_sightings(self):
        data = self._get("/tick-sightings")
        if not isinstance(data, list):
            raise TickAPIError(f"Expected a list of sightings, got {type(data).__name__}")
        logger.info("Fetched %d sightings from source API", len(data))
        return data

    def get_stats(self):
        return self._get("/stats")

    def is_healthy(self):
        try:
            self._get("/health")
            return True
        except TickAPIError:
            return False

    # ---- internals ---------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(RetryableAPIError),
        stop=stop_after_attempt(settings.TICK_API_MAX_RETRIES),
        wait=_wait_strategy,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, path):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise RetryableAPIError(f"Network error calling {url}: {exc}") from exc

        if response.status_code == 429:
            raise RetryableAPIError(
                f"Rate limited by {url}",
                retry_after=self._parse_retry_after(response),
            )
        if response.status_code >= 500:
            raise RetryableAPIError(f"Server error {response.status_code} from {url}")
        if response.status_code != 200:
            # 4xx other than 429: our request is wrong, retrying won't help
            raise TickAPIError(f"Unexpected status {response.status_code} from {url}")

        try:
            return response.json()
        except ValueError as exc:
            raise TickAPIError(f"Invalid JSON from {url}") from exc

    @staticmethod
    def _parse_retry_after(response):
        value = response.headers.get("Retry-After", "")
        return int(value) if value.isdigit() else DEFAULT_RATE_LIMIT_WAIT

    def ping(self, timeout=5):
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False