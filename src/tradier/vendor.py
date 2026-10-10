"""Tradier's market data API: the one module that speaks to it.

REST at api.tradier.com/v1 (or its sandbox, sandbox.tradier.com/v1, delayed
15 minutes, for a developer's own check): `/markets/history` (one symbol's
daily bars over a range) and `/markets/quotes` (many symbols' last trade and
best bid and ask). Market data for a Tradier Brokerage account holder is real
time and consolidated from every exchange. Nothing here streams: Tradier's
streaming session waits for the lake's trades and quotes (contract v19).

**The token.** Tradier's bearer token, from `settings.Credentials`, added to
the request and to nothing else: a raw record keeps the request's other
headers, and as a last guard any text holding the token is redacted before
it is kept. Without a token, nothing is asked.

**Rate limits, honoured.** Tradier allows market data 120 requests a minute
per token; this client spends at most half of it, 60 a minute, one at a
time. A 429 is waited out (Retry-After, else Tradier's X-Ratelimit-Expiry,
else 1, 2, 4 seconds) and asked again at most three times, each counted for
the Connection page.

**Tradier's quirks, held here:** a list of one comes back as the one object
(`"day": {...}`, `"quote": {...}`), and none as `null`; `parse` leaves that
to convert.py, which takes either. Prices are JSON numbers, parsed as
Decimals from their own text, never a float.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .raw import RawStore
from .settings import Credentials

API = "https://api.tradier.com/v1"
SANDBOX = "https://sandbox.tradier.com/v1"
USER_AGENT = "meridian-tradier/0.1.0 (+https://open-meridian.dev)"
NS = 1_000_000_000

#: Tradier allows market data 120 requests a minute; this spends half of it.
LIMIT_PER_MINUTE = 60
#: The most symbols one quotes call names.
SYMBOLS_PER_CALL = 100
#: The symbol the probe asks about: an ETF Tradier carries.
PROBE_SYMBOL = "SPY"
KEPT_HEADERS = (
    "date",
    "content-type",
    "x-ratelimit-allowed",
    "x-ratelimit-used",
    "x-ratelimit-available",
    "x-ratelimit-expiry",
    "retry-after",
)
REDACTED = "[redacted]"


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str]], Response]


def urllib_transport(url: str, headers: Mapping[str, str]) -> Response:
    """One GET over HTTPS, with the standard library."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            return Response(
                answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
            )
    except urllib.error.HTTPError as answer:
        return Response(
            answer.code, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
        )


def parse(text: str) -> Any:
    """JSON with every non-integer number a Decimal from its own text."""
    return json.loads(text, parse_float=Decimal)


class RateLimiter:
    """A token bucket: `per_minute` calls a minute, one at a time."""

    def __init__(
        self,
        per_minute: int = LIMIT_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate = per_minute / 60
        self._clock, self._sleep = clock, sleep
        self._tokens = 1.0
        self._at = clock()

    def acquire(self) -> None:
        now = self._clock()
        self._tokens = min(1.0, self._tokens + (now - self._at) * self.rate)
        self._at = now
        if self._tokens < 1:
            self._sleep((1 - self._tokens) / self.rate)
            self._at = self._clock()
            self._tokens = 1.0
        self._tokens -= 1


class VendorError(Exception):
    """Tradier answered with something other than what was asked for. Its
    message is Tradier's, from the body; never a header, never the token."""

    def __init__(self, call: str, status: int, detail: str, raw_key: str) -> None:
        super().__init__(f"{call}: {status} {detail} (raw record {raw_key})")
        self.call, self.status, self.detail, self.raw_key = call, status, detail, raw_key


class NoKey(Exception):
    """There is no token to ask Tradier with: nothing was asked."""


@dataclass(frozen=True)
class Fetched:
    """A parsed body, the key of the raw record it was kept as, and when it
    arrived."""

    value: Any
    raw_key: str
    received_at_ns: int


@dataclass(frozen=True)
class Entitlements:
    """Whether Tradier answered the token (never its value), and whether its
    data is real time: the sandbox is delayed 15 minutes."""

    answered: bool
    real_time: bool = False
    detail: str = ""


@dataclass
class Usage:
    """What the client has spent, for the Connection page: never a value."""

    calls: int = 0
    rate_limited: int = 0
    last_call_at_ns: int = 0
    last_status: int = 0
    last_error: str = ""
    by_call: dict[str, int] = field(default_factory=dict)


class Tradier:
    """Tradier's market data, every response kept."""

    def __init__(
        self,
        store: RawStore,
        credentials: Credentials | None,
        transport: Transport = urllib_transport,
        limiter: RateLimiter | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 3,
        keyless: bool = False,
        base: str = API,
    ) -> None:
        self.store, self.credentials, self.transport = store, credentials, transport
        self.limiter = limiter or RateLimiter()
        self.clock_ns, self.sleep, self.retries = clock_ns, sleep, retries
        # Synthetic mode asks its built-in exchange with no token.
        self.keyless = keyless
        self.base = base
        self.usage = Usage()
        self._kept = 0

    def _keep(self, key: str, record: dict[str, Any]) -> str:
        self._kept += 1
        return self.store.keep(f"{key}/{record['received_at_ns']}-{self._kept}", record)

    def _redacted(self, text: str) -> str:
        if self.credentials is not None:
            for secret in self.credentials.secrets():
                text = text.replace(secret, REDACTED)
        return text

    def _wait(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = headers.get("retry-after", "")
        if retry_after.isdigit():
            return float(retry_after)
        expiry = headers.get("x-ratelimit-expiry", "")
        if expiry.isdigit():
            # Tradier states the window's end in epoch milliseconds.
            return float(min(60, max(1, int(expiry) // 1000 - self.clock_ns() // NS)))
        return 2.0**attempt

    def get(self, call: str, key: str, path: str, params: Mapping[str, str]) -> Fetched:
        """One call, kept as a raw record before anything reads it."""
        if self.credentials is None and not self.keyless:
            raise NoKey(f"{call}: no Tradier token is set, so nothing was asked")
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        kept_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        headers = dict(kept_headers)
        if self.credentials is not None:
            headers.update(self.credentials.headers())
        for attempt in range(self.retries + 1):
            self.limiter.acquire()
            self.usage.calls += 1
            self.usage.by_call[call] = self.usage.by_call.get(call, 0) + 1
            answer = self.transport(url, headers)
            received = self.clock_ns()
            self.usage.last_call_at_ns, self.usage.last_status = received, answer.status
            text = self._redacted(answer.body.decode("utf-8", errors="replace"))
            raw_key = self._keep(
                key,
                {
                    "venue": "tradier",
                    "call": call,
                    "request": {"method": "GET", "url": url, "headers": kept_headers},
                    "received_at_ns": received,
                    "status": answer.status,
                    "headers": {
                        h: self._redacted(answer.headers[h])
                        for h in KEPT_HEADERS
                        if h in answer.headers
                    },
                    "body": text,
                },
            )
            if answer.status == 429 and attempt < self.retries:
                self.usage.rate_limited += 1
                self.sleep(self._wait(answer.headers, attempt))
                continue
            if answer.status != 200:
                failed = VendorError(call, answer.status, _message(text), raw_key)
                self.usage.last_error = f"{call}: {answer.status} {failed.detail}"
                raise failed
            try:
                value = parse(text)
            except json.JSONDecodeError as broken:
                self.usage.last_error = f"{call}: not JSON"
                raise VendorError(call, answer.status, f"not JSON: {broken}", raw_key) from None
            self.usage.last_error = ""
            return Fetched(value, raw_key, received)
        raise AssertionError("unreachable")

    def history(self, symbol: str, first: str, last: str) -> Fetched:
        """One symbol's daily bars for dates `first` to `last`, in Tradier's
        spelling of the symbol."""
        params = {"symbol": symbol, "interval": "daily", "start": first, "end": last}
        return self.get("history", f"history/{symbol}", "/markets/history", params)

    def quotes(self, symbols: Sequence[str]) -> Fetched:
        params = {"symbols": ",".join(symbols), "greeks": "false"}
        return self.get("quotes", "quotes", "/markets/quotes", params)

    def entitlements(self, symbol: str = PROBE_SYMBOL) -> Entitlements:
        """Ask once whether Tradier answers the token, with a quote. Raises
        NoKey without a token."""
        try:
            self.quotes([symbol])
        except VendorError as refused:
            if refused.status in (401, 403):
                return Entitlements(answered=False, detail=f"{refused.status} {refused.detail}")
            raise
        return Entitlements(answered=True, real_time=self.base == API)


def _message(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text[:200]
    if isinstance(parsed, dict):
        fault = parsed.get("fault")
        if isinstance(fault, dict) and "faultstring" in fault:
            return str(fault["faultstring"])[:200]
        for name in ("message", "error"):
            if name in parsed:
                return str(parsed[name])[:200]
    return text[:200]
