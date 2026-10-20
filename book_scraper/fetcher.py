"""A polite HTTP client for scraping.

"Polite" means three things:

1. robots.txt is checked before every request (the site owner's rules).
2. There is a fixed pause between requests, so we never hammer a server.
3. Temporary errors (timeouts, 429, 5xx) are retried automatically with
   increasing wait times ("exponential backoff").

This module knows nothing about books. You can reuse it unchanged for any
other scraping job.
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# Identify yourself honestly. Many sites block the default "python-requests" agent.
DEFAULT_USER_AGENT = (
    "book-price-scraper/1.0 (+https://github.com/Sossa300/book-price-scraper)"
)

# HTTP status codes that are usually temporary and worth retrying.
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL."""


def build_session(retries: int = 3, user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    """Create a requests.Session that retries temporary errors by itself."""
    retry = Retry(
        total=retries,
        backoff_factor=1.0,  # waits roughly 1s, 2s, 4s ... between attempts
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=("GET",),
        respect_retry_after_header=True,  # honour "Retry-After" on 429/503
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = user_agent
    return session


class PoliteSession:
    """Fetches HTML pages while respecting robots.txt and a request delay."""

    def __init__(
        self,
        delay: float = 1.0,
        retries: int = 3,
        timeout: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        respect_robots: bool = True,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.session = session or build_session(retries, user_agent)
        # Injected so tests can run without really waiting.
        self._sleep = sleep
        self._last_request: float | None = None
        self._robots: dict[str, RobotFileParser] = {}

    # ------------------------------------------------------------------ public

    def get_html(self, url: str) -> str:
        """Download a page and return its HTML as text.

        Raises RobotsDisallowed if robots.txt forbids the URL and
        requests.HTTPError for 4xx/5xx answers that survived all retries.
        """
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt does not allow {url}")
        log.debug("GET %s", url)
        response = self._get(url)
        response.raise_for_status()
        # Without a charset in the Content-Type header, requests falls back to
        # ISO-8859-1 and "£" turns into "Â£". Let it detect the real encoding.
        if "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = response.apparent_encoding
        return response.text

    def allowed(self, url: str) -> bool:
        """Return True if robots.txt allows our user agent to fetch the URL."""
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:  # load robots.txt only once per site
            self._robots[root] = self._load_robots(root)
        return self._robots[root].can_fetch(self.user_agent, url)

    # ----------------------------------------------------------------- helpers

    def _load_robots(self, root: str) -> RobotFileParser:
        robots_url = f"{root}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            response = self._get(robots_url)
        except requests.RequestException as exc:
            log.warning("Could not load %s (%s), assuming everything is allowed", robots_url, exc)
            parser.allow_all = True
            return parser

        # Same rules as Python's own RobotFileParser.read():
        # 401/403 = we are not welcome at all, other 4xx = no rules = allowed.
        if response.status_code in (401, 403):
            log.warning("%s answered %s, treating the whole site as disallowed",
                        robots_url, response.status_code)
            parser.disallow_all = True
        elif response.status_code >= 400:
            log.info("No robots.txt at %s (HTTP %s), everything allowed",
                     root, response.status_code)
            parser.allow_all = True
        else:
            parser.parse(response.text.splitlines())
            log.info("Loaded robots.txt from %s", root)
        return parser

    def _get(self, url: str) -> requests.Response:
        """GET a URL, waiting first if the previous request was too recent."""
        if self._last_request is not None:
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        try:
            return self.session.get(url, timeout=self.timeout)
        finally:
            self._last_request = time.monotonic()
