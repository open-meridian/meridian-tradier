"""Synthetic Tradier: answers the plugin's calls from the built-in exchange,
with no token and no network (the `synthetic` setting, for development, the
tests and the e2e).

`exchanges/exchange.json` is shaped on Tradier's documented responses with
every value invented (the lake plan's Q11: real responses stay in a
developer's own storage, never committed): daily history for SPY, BRK/B (as
Tradier spells it) and TQQQ over 2026-10-05 to 2026-10-09, TQQQ's last close
with eighteen decimal places, and the quotes of SPY and BRK/B, BRK/B's bid
side empty, sizes in hundreds; from 0.13.0 SPY's option expirations and
their chains (`options`), and a month's market days, every weekday open.
Its numbers are text in the file and go out
as JSON numbers, exactly as written, as Tradier sends them; and, as Tradier
does, a list of one goes out as the one object, none as `null`, and a symbol
it does not know under `unmatched_symbols`.

Its stream (`SyntheticFeed`) replays the exchange's `stream` events, as
Tradier's WebSocket sends them: some numbers as numbers, some as text.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from .raw import RawStore, StreamLog
from .vendor import Response

#: The fields Tradier sends as text, never as numbers.
TEXT_FIELDS = frozenset(
    {
        "symbol", "description", "exch", "type", "bidexch", "askexch", "date", "underlying",
        "expiration_date", "expiration_type", "option_type", "root_symbol", "status",
    }
)  # fmt: skip


def exchange(path: Path | None = None) -> dict[str, Any]:
    """The built-in exchange, or the one at `path` (a developer's recording)."""
    if path is not None:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    text = resources.files("tradier").joinpath("exchanges/exchange.json").read_text("utf-8")
    built: dict[str, Any] = json.loads(text)
    return built


def dumps(value: Any, key: str = "") -> str:
    """JSON with each number written as its text."""
    if isinstance(value, dict):
        inner = ",".join(f"{json.dumps(k)}:{dumps(v, k)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, list):
        return "[" + ",".join(dumps(v, key) for v in value) + "]"
    if (
        isinstance(value, str)
        and key
        and key not in TEXT_FIELDS
        and re.fullmatch(r"-?\d+(\.\d+)?", value)
    ):
        return value
    return json.dumps(value)


def _one_or_many(items: list[Any]) -> Any:
    """Tradier's list: none is null, one is the object, more a list."""
    if not items:
        return None
    return items[0] if len(items) == 1 else items


class SyntheticTransport:
    """vendor.Transport on the built-in exchange: `/markets/history`,
    `/markets/quotes`, and from 0.13.0 `/markets/options/expirations`,
    `/markets/options/chains` and `/markets/calendar`, on either Tradier's
    host or its sandbox."""

    def __init__(self, held: Mapping[str, Any] | None = None) -> None:
        self.held = held if held is not None else exchange()
        self.asked: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append(url)
        parsed = urllib.parse.urlparse(url)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path.endswith("/markets/history"):
            first, last = params.get("start", ""), params.get("end", "")
            days = [
                day
                for day in self.held.get("history", {}).get(params.get("symbol", ""), [])
                if (not first or day["date"] >= first) and (not last or day["date"] <= last)
            ]
            history = _one_or_many(days)
            return self._ok({"history": None if history is None else {"day": history}})
        if parsed.path.endswith("/markets/quotes"):
            symbols = [s for s in params.get("symbols", "").split(",") if s]
            held = self.held.get("quotes", {})
            found = [held[s] for s in symbols if s in held]
            unmatched = [s for s in symbols if s not in held]
            body: dict[str, Any] = {"quote": _one_or_many(found)}
            if unmatched:
                body["unmatched_symbols"] = {"symbol": _one_or_many(unmatched)}
            return self._ok({"quotes": body})
        options = self.held.get("options", {}).get(params.get("symbol", ""), {})
        if parsed.path.endswith("/markets/options/expirations"):
            dates = _one_or_many(list(options.get("expirations", [])))
            return self._ok({"expirations": None if dates is None else {"date": dates}})
        if parsed.path.endswith("/markets/options/chains"):
            listed = _one_or_many(list(options.get("chains", {}).get(params.get("expiration"), [])))
            return self._ok({"options": None if listed is None else {"option": listed}})
        if parsed.path.endswith("/markets/calendar"):
            return self._ok(
                _calendar(int(params.get("year", "2026")), int(params.get("month", "1")))
            )
        return Response(404, {"content-type": "text/plain"}, b"Not Found")

    @staticmethod
    def _ok(body: Any) -> Response:
        return Response(200, {"content-type": "application/json"}, dumps(body).encode())


def _calendar(year: int, month: int) -> dict[str, Any]:
    """A month's market days as `/markets/calendar` states them: every
    weekday open, invented (no holiday is held)."""
    import datetime as dt

    day = dt.date(year, month, 1)
    days = []
    while day.month == month:
        status = "open" if day.weekday() < 5 else "closed"
        days.append({"date": day.isoformat(), "status": status})
        day += dt.timedelta(days=1)
    return {"calendar": {"month": str(month), "year": str(year), "days": {"day": days}}}


#: The fields Tradier's stream sends as numbers; the rest of a time and
#: sale's are text, and a quote's dates are text.
STREAM_NUMBERS = frozenset({"seq", "bid", "ask", "bidsz", "asksz"})


class SyntheticFeed:
    """stream.Feed on the built-in exchange's `stream`: no network, no token.
    Each cycle replays its events for the listings subscribed, stamped from
    the moment the cycle began, with sequence numbers moved on by the cycle:
    a regular print, one with a flag, a print and its cancel, one after the
    close, a quote two-sided and one with no offer, and a `trade` event,
    which the plugin does not convert."""

    name = "synthetic"

    def __init__(
        self,
        store: RawStore,
        held: Mapping[str, Any] | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        from .convert import spelled

        self.spelled = spelled
        self.held = held if held is not None else exchange()
        self.store, self.clock_ns, self.sleep = store, clock_ns, sleep
        script = self.held.get("stream", {})
        self.every = float(script.get("every_seconds", "2"))
        self.events: list[dict[str, Any]] = list(script.get("events", []))
        self.subscribed: set[str] = set()
        self.cycle = 0
        self.log: StreamLog | None = None

    async def open(self) -> None:
        self.log = StreamLog(self.store, f"stream/synthetic/{self.clock_ns()}")

    async def subscribe(self, symbols: Sequence[str]) -> None:
        self.subscribed = set(symbols)

    async def receive(self) -> list[Any]:
        from . import convert

        if self.cycle:
            await self.sleep(self.every)
        self.cycle += 1
        began_ms = self.clock_ns() // 1_000_000
        out: list[Any] = []
        for event in self.events:
            if self.spelled(str(event.get("symbol"))) not in self.subscribed:
                continue
            said: dict[str, Any] = {k: v for k, v in event.items() if k != "at_ms"}
            at = str(began_ms + int(event.get("at_ms", "0")))
            if said["type"] == "quote":
                said["biddate"] = said["askdate"] = at
            else:
                said["date"] = at
            if "seq" in said:
                said["seq"] = str(int(said["seq"]) + self.cycle * 1000)
            text = (
                "{"
                + ",".join(
                    f"{json.dumps(k)}:{v if k in STREAM_NUMBERS else json.dumps(v)}"
                    for k, v in said.items()
                )
                + "}"
            )
            message = json.loads(text, parse_float=Decimal)
            key = self.log.keep({"message": said}) if self.log is not None else ""
            out.extend(convert.streamed(message, key))
        return out

    async def close(self) -> None:
        if self.log is not None:
            self.log.close()
            self.log = None
