"""Tradier's brokerage API, for its accounts and orders: the one module that
speaks to it for custody (from 0.7.0) and connectivity (from 0.6.0).

The account side reads and trades through the environment chosen
(settings.py): Tradier's API, `https://api.tradier.com/v1`, with a Tradier
Brokerage account's token, or its developer sandbox,
`https://sandbox.tradier.com/v1`, the same API paper trading with simulated
money. Both read `GET /user/profile` (the accounts the token reaches, by
their numbers, each a venue account code) and `GET /accounts/{id}/orders`
(the account's orders this session, with their tags). Custody reads too
`GET /accounts/{id}/balances`, `GET /accounts/{id}/positions`,
`GET /accounts/{id}/history` and `GET /markets/quotes` (a holding's kind and
description). Connectivity places, changes and cancels an equity order with
`POST /accounts/{id}/orders`, `PUT /accounts/{id}/orders/{order_id}` and
`DELETE /accounts/{id}/orders/{order_id}`, each form-encoded as Tradier
takes it.

**The token** goes in the bearer header (`settings.Credentials`) and nowhere
else: a raw record keeps the request's other headers and its body, and any
text holding the token is redacted before it is kept. Without one, nothing
is asked.

**Every exchange is a raw record first** (kinds.py), with its request and
the moment its answer arrived, before anything reads it: a read under
`responses`, a page of history under `activity`, a send under `trading`. A
send that never got an answer is kept too, saying so, and raises
`Unanswered`: it may have reached Tradier, and is never sent again on its
own (trading.py). Tradier's numbers are JSON numbers; a body is parsed with
every number a Decimal from its own text.

**Rate limits.** Tradier allows a token 120 brokerage calls a minute; this
client spends at most sixty, one at a time (vendor.RateLimiter). A 429 is
answered by waiting and asking again, a read only: a send is never asked
twice.

Synthetic mode hands the client a simulated brokerage as its transport
(synthetic_broker.py), so the same code is exercised and nothing reaches
Tradier.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .kinds import ACTIVITY, RESPONSES, TRADING, Store
from .settings import Credentials
from .vendor import REDACTED, RateLimiter, Response, parse

USER_AGENT = "meridian-tradier/0.7.0 (+https://open-meridian.dev)"
LIMIT_PER_MINUTE = 60
#: The most history events one page asks for.
HISTORY_PAGE = 100
KEPT_HEADERS = ("date", "content-type", "x-ratelimit-available", "x-ratelimit-expiry")

#: One request: its method, URL, headers and form body, answered.
Send = Callable[[str, str, Mapping[str, str], bytes | None], Response]


def urllib_send(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Response:
    """One request over HTTPS, with the standard library. A connection that
    fails raises OSError: no answer."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            return Response(
                answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
            )
    except urllib.error.HTTPError as answer:
        return Response(
            answer.code, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
        )


class BrokerError(Exception):
    """Tradier answered something other than what was asked: its status and
    its words as it said them. Never a header, never the token."""

    def __init__(self, call: str, status: int, code: str, text: str, raw_key: str) -> None:
        super().__init__(f"{call}: {status} {text}".strip())
        self.call, self.status, self.code, self.text, self.raw_key = (
            call,
            status,
            code,
            text,
            raw_key,
        )


class Unanswered(Exception):
    """A request Tradier never answered: it may have reached Tradier."""

    def __init__(self, call: str, why: str, raw_key: str) -> None:
        super().__init__(f"{call}: no answer ({why})")
        self.call, self.why, self.raw_key = call, why, raw_key


class NoKey(Exception):
    """There is no token to ask Tradier with: nothing was asked."""


@dataclass(frozen=True)
class Answer:
    """A parsed body, the key of the raw record it was kept as, and when it
    arrived."""

    value: Any
    raw_key: str
    received_at: datetime


class Broker:
    """Tradier's brokerage API for one environment, every exchange kept."""

    def __init__(
        self,
        store: Store,
        credentials: Credentials | None,
        base: str,
        send: Send = urllib_send,
        limiter: RateLimiter | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        keyless: bool = False,
        synthetic: bool = False,
    ) -> None:
        self.store, self.credentials, self.base, self.send = store, credentials, base, send
        self.limiter = limiter or RateLimiter(LIMIT_PER_MINUTE)
        self.now, self.sleep = now, sleep
        self.keyless, self.synthetic = keyless, synthetic
        self.calls = 0
        self.last_error = ""

    def _redacted(self, text: str) -> str:
        if self.credentials is not None:
            for secret in self.credentials.secrets():
                text = text.replace(secret, REDACTED)
        return text

    def _ask(
        self,
        call: str,
        kind: str,
        name: str,
        method: str,
        path: str,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> Answer:
        """One exchange, kept as a raw record before anything reads it."""
        if self.credentials is None and not self.keyless:
            raise NoKey(f"{call}: no Tradier token is set, so nothing was asked")
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        sent = None if form is None else urllib.parse.urlencode(form).encode()
        kept_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if sent is not None:
            kept_headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers = dict(kept_headers)
        if self.credentials is not None:
            headers.update(self.credentials.headers())
        request = {
            "method": method,
            "url": url,
            "headers": kept_headers,
            "body": None if sent is None else self._redacted(sent.decode()),
        }
        reads = method == "GET"
        for attempt in range(4 if reads else 1):
            self.limiter.acquire()
            self.calls += 1
            try:
                answer = self.send(method, url, headers, sent)
            except OSError as failed:
                why = type(failed).__name__
                key = self.store.keep(
                    kind,
                    name,
                    {
                        "venue": "tradier",
                        "call": call,
                        "request": request,
                        "answered": False,
                        "why": why,
                        "synthetic": self.synthetic,
                    },
                    self.now(),
                )
                self.last_error = f"{call}: no answer ({why})"
                raise Unanswered(call, why, key) from None
            text = self._redacted(answer.body.decode("utf-8", errors="replace"))
            key = self.store.keep(
                kind,
                name,
                {
                    "venue": "tradier",
                    "call": call,
                    "request": request,
                    "answered": True,
                    "status": answer.status,
                    "headers": {
                        h: self._redacted(answer.headers[h])
                        for h in KEPT_HEADERS
                        if h in answer.headers
                    },
                    "body": text,
                    "synthetic": self.synthetic,
                },
                self.now(),
            )
            if answer.status == 429 and reads and attempt < 3:
                self.sleep(2.0**attempt)
                continue
            if answer.status >= 300:
                words = _said(text)
                self.last_error = f"{call}: {answer.status} {words}"[:200]
                raise BrokerError(call, answer.status, str(answer.status), words, key)
            try:
                value = parse(text) if text.strip() else None
            except json.JSONDecodeError:
                raise BrokerError(call, answer.status, "", "not JSON", key) from None
            failed_said = _errors(value)
            if failed_said:
                # Tradier refuses some sends with a 200 and its errors.
                self.last_error = f"{call}: {failed_said}"[:200]
                raise BrokerError(call, answer.status, str(answer.status), failed_said, key)
            self.last_error = ""
            return Answer(value, key, self.now())
        raise AssertionError("unreachable")

    def profile(self) -> Answer:
        """The user the token is, and the accounts it reaches."""
        return self._ask("profile", RESPONSES, "profile", "GET", "/user/profile")

    def orders(self, account: str) -> Answer:
        """The account's orders this session, with their tags."""
        return self._ask(
            "orders",
            RESPONSES,
            "orders",
            "GET",
            f"/accounts/{urllib.parse.quote(account)}/orders",
            {"includeTags": "true"},
        )

    # ── Custody's reads, from 0.7.0 ─────────────────────────────────────

    def balances(self, account: str) -> Answer:
        """The account's balances: its cash, as Tradier states it now."""
        return self._ask(
            "balances",
            RESPONSES,
            "balances",
            "GET",
            f"/accounts/{urllib.parse.quote(account)}/balances",
        )

    def positions(self, account: str) -> Answer:
        """The account's positions, as Tradier states them now."""
        return self._ask(
            "positions",
            RESPONSES,
            "positions",
            "GET",
            f"/accounts/{urllib.parse.quote(account)}/positions",
        )

    def history(self, account: str, page: int = 1, start: str = "") -> Answer:
        """One page of the account's history, from `start`'s day where given."""
        params = {"page": str(page), "limit": str(HISTORY_PAGE)}
        if start:
            params["start"] = start
        return self._ask(
            "history",
            ACTIVITY,
            "history",
            "GET",
            f"/accounts/{urllib.parse.quote(account)}/history",
            params,
        )

    def quotes(self, symbols: list[str]) -> Answer:
        """Tradier's quotes for the symbols held: each one's kind and
        description."""
        return self._ask(
            "quotes",
            RESPONSES,
            "quotes",
            "GET",
            "/markets/quotes",
            {"symbols": ",".join(symbols), "greeks": "false"},
        )

    # ── Connectivity's sends ────────────────────────────────────────────

    def place(self, account: str, form: Mapping[str, str]) -> Answer:
        return self._ask(
            "placing an order",
            TRADING,
            "place",
            "POST",
            f"/accounts/{urllib.parse.quote(account)}/orders",
            form=form,
        )

    def change(self, account: str, order_id: str, form: Mapping[str, str]) -> Answer:
        return self._ask(
            "changing an order",
            TRADING,
            "change",
            "PUT",
            f"/accounts/{urllib.parse.quote(account)}/orders/{urllib.parse.quote(order_id)}",
            form=form,
        )

    def cancel(self, account: str, order_id: str) -> Answer:
        return self._ask(
            "cancelling an order",
            TRADING,
            "cancel",
            "DELETE",
            f"/accounts/{urllib.parse.quote(account)}/orders/{urllib.parse.quote(order_id)}",
        )


def _errors(value: Any) -> str:
    """Tradier's errors in a body (`{"errors": {"error": [...]}}`), as said."""
    if not isinstance(value, dict):
        return ""
    errors = value.get("errors")
    if isinstance(errors, dict):
        said = errors.get("error")
        listed = said if isinstance(said, list) else [said]
        return "; ".join(str(each) for each in listed if each)[:200]
    fault = value.get("fault")
    if isinstance(fault, dict):
        return str(fault.get("faultstring") or "")[:200]
    return ""


def _said(text: str) -> str:
    try:
        parsed = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError:
        return text[:200]
    return _errors(parsed) or text[:200]
