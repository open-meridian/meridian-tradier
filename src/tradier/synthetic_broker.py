"""Synthetic Tradier's brokerage API: a simulated brokerage behind the shapes of
Tradier's user profile and an account's balances, positions, history and
orders, and its quotes' security types, for sample data, the tests and
`make e2e` (from 0.6.0; the account's balances, positions and history from
0.7.0).

SIMULATED ONLY. Nothing here reaches Tradier, its developer sandbox or any
brokerage: an order "placed" here is a line in this module's state, and
every answer is shaped like Tradier's own (its profile, its balances, its
positions, its history, its order, its quote, its errors), invented, every
value of it. A sandbox run against Tradier is the
product owner's alone, by hand, and never this.

It is a `broker.Send`: broker.py speaks to it exactly as to Tradier, so the
same code is exercised. What it holds survives the plugin's restart, as a
brokerage's orders do: a JSON file in the plugin's storage
(`synthetic-venue/orders.json`), written whole on every change; with none
given (a test) it lives in the process. Where the file changes beside it
(an order placed in Tradier's own web app, `place_at_the_brokerage`), the
next request reads it again.

The user reaches one margin account, `SYN-TRD-1001`, opened on 2026-09-01
with a deposit of 100,000 dollars by ACH, which holds one order from the
start: three AAPL bought at the brokerage outside the platform on
2026-09-02 (`9000001`, no tag), which paid a dividend on 2026-09-15: the
history custody reads, and an order filled before the plugin watched the
account, which connectivity leaves alone. An order placed in Tradier's own
web app later (`place_at_the_brokerage`, no tag) is worked as any other,
and its fills are the venue-originated fills connectivity reports on no
placement (contract v23).

Each fill is also a `trade` in the account's history, dated its day, which
the history lists from the day after, as Tradier's is updated nightly; the
positions (each with its cost basis) and the cash are what the fills, the
deposit and the dividend come to, a bust taking its fill back.

How it works an order, each read of the account's orders taking it one step
on, so a test and the e2e see every state:

- placed: `{"order": {"id": <n>, "status": "ok"}}`, the order `open`, its
  tag as given;
- a quantity of at most 100: on the next read `partially_filled`, 40% (to a
  whole share), then `filled`, at the limit price, else the symbol's
  synthetic price, each step stating its last fill's quantity and price;
  more than 100 stays `open` until cancelled;
- cancelled (`DELETE`): `canceled`, what was filled kept; one ended is
  refused (400, "Order is not open");
- changed (`PUT`), while it works: its type, duration, limit and stop as
  asked, the order keeping its ID; one ended is refused (400).

And by the symbol, so each of Tradier's answers has an order to show it:

- `SYNREJ`: refused when placed, 400, Tradier's errors;
- `SYNLOST`: taken, but the answer never arrives (the call fails with no
  status); the order is there when the orders are read;
- `SYNODD`: read `held`, a status the plugin's mapping does not know, then
  `open` on the next read;
- `SYNBUST`: filled in full, then on a later read its filled quantity back
  to 0 and `canceled`, the brokerage having busted the fill;
- `SYNREN`: renamed while it works: once it fills, its order names the
  symbol `SYNRNM`.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from .vendor import Response, parse

ACCOUNT_NUMBER = "SYN-TRD-1001"
REJECTED = "SYNREJ"
LOST = "SYNLOST"
ODD = "SYNODD"
BUSTED = "SYNBUST"
RENAMED = "SYNREN"
RENAMED_TO = "SYNRNM"
#: A status the plugin's mapping does not know.
ODD_STATUS = "held"
FILLS_AT_ONCE = Decimal(100)
PRICES = {"AAPL": Decimal("227.41"), "SPY": Decimal("575.44")}
PRICE = Decimal("100.00")
OUTSIDE_ID = 9000001
DEPOSIT = Decimal("100000.00")
#: Each synthetic symbol's security type, as Tradier's quote states it.
TYPES = {"AAPL": "stock", "SPY": "etf"}
WORKING = ("open", "partially_filled", "pending", ODD_STATUS)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _seeded() -> dict[str, Any]:
    outside = {
        "id": OUTSIDE_ID,
        "type": "market",
        "symbol": "AAPL",
        "side": "buy",
        "quantity": "3",
        "status": "filled",
        "duration": "day",
        "price": None,
        "stop_price": None,
        "avg_fill_price": "226.10",
        "exec_quantity": "3",
        "last_fill_price": "226.10",
        "last_fill_quantity": "3",
        "remaining_quantity": "0",
        "create_date": "2026-09-02T14:31:00.000Z",
        "transaction_date": "2026-09-02T14:31:01.000Z",
        "class": "equity",
    }
    return {
        "next": 1,
        "orders": [outside],
        "events": [
            {
                "amount": _text(DEPOSIT),
                "date": "2026-09-01T00:00:00Z",
                "type": "ach",
                "ach": {"description": "ACH DEPOSIT", "quantity": "0"},
            },
            {
                "amount": "-678.30",
                "date": "2026-09-02T00:00:00Z",
                "type": "trade",
                "trade": {
                    "commission": "0",
                    "description": "APPLE INC COM",
                    "price": "226.10",
                    "quantity": "3",
                    "symbol": "AAPL",
                    "trade_type": "Equity",
                },
            },
            {
                "amount": "0.75",
                "date": "2026-09-15T00:00:00Z",
                "type": "dividend",
                "dividend": {"description": "APPLE INC COM", "quantity": "0"},
            },
        ],
    }


def place_at_the_brokerage(
    state: Path, symbol: str, quantity: str, side: str = "buy", now: datetime | None = None
) -> int:
    """An order placed in Tradier's own web app, outside the platform,
    written to the simulated brokerage's state beside it (the e2e's way in,
    and a test's): a market order with no tag, worked from the next read on.
    Its ID."""
    broker = SyntheticBroker(lambda: now or datetime.now(UTC), state)
    return broker.at_the_brokerage(symbol, quantity, side)


class SyntheticBroker:
    """The simulated brokerage, answering as Tradier's brokerage API."""

    def __init__(self, now: Callable[[], datetime], state: Path | None = None) -> None:
        self._now = now
        self._file = state
        self._stamp: float = 0.0
        self.held: dict[str, Any] = {}
        #: Every request asked of it: method and path.
        self.asked: list[tuple[str, str]] = []
        self._load()

    def _load(self) -> None:
        held: Any = None
        if self._file is not None and self._file.exists():
            try:
                held = parse(self._file.read_text())
            except (OSError, ValueError):
                held = None
        self.held = held if isinstance(held, dict) and "orders" in held else _seeded()
        self.held.setdefault("events", [])
        self._stamp = self._mtime()

    def _mtime(self) -> float:
        try:
            return self._file.stat().st_mtime if self._file is not None else 0.0
        except OSError:
            return 0.0

    def _reload_if_changed(self) -> None:
        """The state as written beside this process (an order placed in
        Tradier's own web app), read again where the file changed."""
        if self._file is not None and self._mtime() != self._stamp:
            self._load()

    def at_the_brokerage(self, symbol: str, quantity: str, side: str = "buy") -> int:
        """An order placed in Tradier's own web app: a market order with no
        tag, worked from the next read on."""
        self._reload_if_changed()
        now = _stamp(self._now())
        number = 9100000 + int(self.held["next"])
        self.held["next"] = int(self.held["next"]) + 1
        self.held["orders"].append(
            {
                "id": number,
                "type": "market",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": "open",
                "duration": "day",
                "price": None,
                "stop_price": None,
                "avg_fill_price": "0",
                "exec_quantity": "0",
                "last_fill_price": "0",
                "last_fill_quantity": "0",
                "remaining_quantity": quantity,
                "create_date": now,
                "transaction_date": now,
                "class": "equity",
            }
        )
        self._save()
        return number

    def _save(self) -> None:
        if self._file is None:
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        made, written = tempfile.mkstemp(dir=self._file.parent, suffix=".tmp")
        try:
            with os.fdopen(made, "w") as file:
                json.dump(self.held, file, default=str, sort_keys=True)
            os.replace(written, self._file)
        except BaseException:
            Path(written).unlink(missing_ok=True)
            raise
        self._stamp = self._mtime()

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> Response:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.removeprefix("/v1")
        self.asked.append((method, path))
        self._reload_if_changed()
        asked = {k: v[0] for k, v in urllib.parse.parse_qs((body or b"").decode()).items()}
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if method == "GET" and path == "/markets/quotes":
            return _ok(self._quotes(query.get("symbols", "")))
        if method == "GET" and path == "/user/profile":
            return _ok(
                {
                    "profile": {
                        "id": "id-syn-user",
                        "name": "Synthetic User",
                        "account": {
                            "account_number": ACCOUNT_NUMBER,
                            "classification": "individual",
                            "date_created": "2026-09-01T13:05:00.000Z",
                            "type": "margin",
                            "status": "active",
                            "day_trader": False,
                            "option_level": 1,
                        },
                    }
                }
            )
        account = f"/accounts/{ACCOUNT_NUMBER}"
        if method == "GET" and path == f"{account}/balances":
            return _ok(self._balances())
        if method == "GET" and path == f"{account}/positions":
            held = self._positions()
            return _ok({"positions": {"position": held} if held else "null"})
        if method == "GET" and path == f"{account}/history":
            return _ok(self._history(query))
        prefix = f"{account}/orders"
        if not path.startswith(prefix):
            return _refused(400, "Invalid Parameter: account_id")
        rest = path.removeprefix(prefix).strip("/")
        if method == "GET" and not rest:
            for order in self.held["orders"]:
                self._step(order)
            self._save()
            shown = [
                {k: v for k, v in o.items() if k != "reads_filled"} for o in self.held["orders"]
            ]
            return _ok({"orders": {"order": shown if len(shown) != 1 else shown[0]}})
        if method == "POST" and not rest:
            return self._place(asked)
        order = self._order(rest)
        if order is None:
            return _refused(404, "Order not found")
        if method == "DELETE":
            return self._cancel(order)
        if method == "PUT":
            return self._change(order, asked)
        return _refused(400, "Invalid request")

    def _order(self, order_id: str) -> dict[str, Any] | None:
        return next((o for o in self.held["orders"] if str(o["id"]) == order_id), None)

    def _place(self, asked: Mapping[str, str]) -> Response:
        symbol = asked.get("symbol", "")
        if symbol == REJECTED:
            return _refused(
                400, "Backoffice rejected override of the order. Insufficient buying power"
            )
        now = _stamp(self._now())
        number = int(self.held["next"])
        self.held["next"] = number + 1
        order = {
            "id": number,
            "type": asked.get("type"),
            "symbol": symbol,
            "side": asked.get("side"),
            "quantity": asked.get("quantity"),
            "status": "open",
            "duration": asked.get("duration"),
            "price": asked.get("price"),
            "stop_price": asked.get("stop"),
            "avg_fill_price": "0",
            "exec_quantity": "0",
            "last_fill_price": "0",
            "last_fill_quantity": "0",
            "remaining_quantity": asked.get("quantity"),
            "create_date": now,
            "transaction_date": now,
            "class": "equity",
            "tag": asked.get("tag"),
        }
        if symbol == ODD:
            order["odd"] = True
        self.held["orders"].append(order)
        self._save()
        if symbol == LOST:
            raise ConnectionResetError("the answer was lost on the way back")
        return _ok({"order": {"id": number, "status": "ok", "partner_id": "synthetic"}})

    def _cancel(self, order: dict[str, Any]) -> Response:
        if order["status"] not in WORKING:
            return _refused(400, "Order is not open")
        order.update(status="canceled", transaction_date=_stamp(self._now()))
        self._save()
        return _ok({"order": {"id": order["id"], "status": "ok"}})

    def _change(self, order: dict[str, Any], asked: Mapping[str, str]) -> Response:
        if order["status"] not in WORKING:
            return _refused(400, "Order is not open")
        for field, given in (
            ("type", "type"),
            ("duration", "duration"),
            ("price", "price"),
            ("stop_price", "stop"),
        ):
            if asked.get(given):
                order[field] = asked[given]
        order["transaction_date"] = _stamp(self._now())
        self._save()
        return _ok({"order": {"id": order["id"], "status": "ok"}})

    def _step(self, order: dict[str, Any]) -> None:
        status, symbol = order["status"], order["symbol"]
        total = Decimal(str(order["quantity"]))
        price = Decimal(str(order["price"])) if order.get("price") else PRICES.get(symbol, PRICE)
        now = self._now()
        before = Decimal(str(order["exec_quantity"]))
        filled = before
        if order.pop("odd", False):
            order["status"] = ODD_STATUS
        elif status == ODD_STATUS:
            order["status"] = "open"
        elif status == "open" and total <= FILLS_AT_ONCE:
            first = (total * Decimal("0.4")).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
            filled = first if 0 < first < total else total
            if symbol == RENAMED:
                order["symbol"] = RENAMED_TO
            order["status"] = "partially_filled" if filled < total else "filled"
        elif status == "partially_filled":
            filled = total
            order["status"] = "filled"
        elif status == "filled" and symbol == BUSTED:
            order["reads_filled"] = int(order.get("reads_filled", 0)) + 1
            if order["reads_filled"] < 2:
                return
            order.update(
                status="canceled",
                exec_quantity="0",
                avg_fill_price="0",
                last_fill_quantity="0",
                last_fill_price="0",
            )
        else:
            return
        if filled > before:
            order.update(
                exec_quantity=_text(filled),
                avg_fill_price=_text(price),
                last_fill_quantity=_text(filled - before),
                last_fill_price=_text(price),
                remaining_quantity=_text(total - filled),
            )
            self._traded(order, filled - before, price, now)
        order["transaction_date"] = _stamp(now + timedelta(milliseconds=1))

    def _traded(
        self, order: dict[str, Any], quantity: Decimal, price: Decimal, at: datetime
    ) -> None:
        """A step's fill, as a `trade` in the account's history, dated its day."""
        sells = str(order["side"]).startswith("sell")
        units = -quantity if sells else quantity
        self.held["events"].append(
            {
                "amount": _text(-units * price),
                "date": at.strftime("%Y-%m-%dT00:00:00Z"),
                "type": "trade",
                "trade": {
                    "commission": "0",
                    "description": f"{order['symbol']} {order['side']}",
                    "price": _text(price),
                    "quantity": _text(units),
                    "symbol": order["symbol"],
                    "trade_type": "Equity",
                },
                "order_id": order["id"],
            }
        )

    # ── The account's balances, positions, history and quotes ──────────

    def _busted(self) -> set[Any]:
        return {
            o["id"]
            for o in self.held["orders"]
            if o["symbol"] == BUSTED and o["status"] == "canceled"
        }

    def _trades(self) -> list[dict[str, Any]]:
        busted = self._busted()
        return [
            e
            for e in self.held["events"]
            if e["type"] == "trade" and e.get("order_id") not in busted
        ]

    def _positions(self) -> list[dict[str, Any]]:
        held: dict[str, tuple[Decimal, Decimal, str]] = {}
        for event in self._trades():
            trade = event["trade"]
            quantity, cost, first = held.get(trade["symbol"], (Decimal(0), Decimal(0), ""))
            units = Decimal(trade["quantity"])
            held[trade["symbol"]] = (
                quantity + units,
                cost + units * Decimal(trade["price"]),
                first or event["date"],
            )
        return [
            {
                "cost_basis": _text(cost),
                "date_acquired": first,
                "id": 130000 + n,
                "quantity": _text(quantity),
                "symbol": symbol,
            }
            for n, (symbol, (quantity, cost, first)) in enumerate(sorted(held.items()))
            if quantity != 0
        ]

    def _balances(self) -> dict[str, Any]:
        cash = Decimal(0)
        for event in self.held["events"]:
            if event["type"] == "trade" and event.get("order_id") in self._busted():
                continue
            cash += Decimal(event["amount"])
        long_value = sum(
            (Decimal(p["quantity"]) * PRICES.get(p["symbol"], PRICE) for p in self._positions()),
            Decimal(0),
        )
        return {
            "balances": {
                "account_number": ACCOUNT_NUMBER,
                "account_type": "margin",
                "total_cash": _text(cash),
                "total_equity": _text(cash + long_value),
                "long_market_value": _text(long_value),
                "market_value": _text(long_value),
                "short_market_value": "0",
                "pending_orders_count": sum(
                    1 for o in self.held["orders"] if o["status"] in WORKING
                ),
                "uncleared_funds": "0",
                "pending_cash": "0",
                "margin": {
                    "fed_call": "0",
                    "maintenance_call": "0",
                    "stock_buying_power": _text(cash * 2),
                    "option_buying_power": _text(cash),
                    "sweep": "0",
                },
            }
        }

    def _history(self, query: Mapping[str, str]) -> dict[str, Any]:
        """The account's history from `start`'s day, a page of `limit`: each
        event from the day after its own, as Tradier updates it nightly."""
        today = self._now().strftime("%Y-%m-%d")
        start = query.get("start", "")
        limit, page = int(query.get("limit", "25")), int(query.get("page", "1"))
        shown = [
            {k: v for k, v in e.items() if k != "order_id"}
            for e in self.held["events"]
            if e["date"][:10] < today and (not start or e["date"][:10] >= start)
        ]
        shown = shown[(page - 1) * limit : page * limit]
        if not shown:
            return {"history": "null"}
        return {"history": {"event": shown if len(shown) != 1 else shown[0]}}

    def _quotes(self, symbols: str) -> dict[str, Any]:
        quoted = [
            {
                "symbol": symbol,
                "description": f"{symbol} (synthetic)",
                "exch": "Q",
                "type": TYPES.get(symbol, "stock"),
                "last": _text(PRICES.get(symbol, PRICE)),
            }
            for symbol in symbols.split(",")
            if symbol
        ]
        return {"quotes": {"quote": quoted if len(quoted) != 1 else quoted[0]}}


def _ok(value: Any) -> Response:
    return Response(200, {"content-type": "application/json"}, json.dumps(value).encode())


def _refused(status: int, message: str) -> Response:
    body = json.dumps({"errors": {"error": [message]}}).encode()
    return Response(status, {"content-type": "application/json"}, body)
