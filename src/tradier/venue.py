"""Tradier as the Trader's venue (trading.py): its words to the contract's and
back, over its brokerage API (broker.py). The one place Tradier's order
vocabulary is read.

**What Tradier takes** for an equity (`POST /accounts/{id}/orders`,
`class=equity`): `market`, `limit`, `stop` and `stop_limit`; a `market`
order for the `day`, the others for the `day` or `gtc`. Its `pre` and `post`
durations, the extended sessions, have no counterpart among the contract's
times in force, and are never offered; a good-till-date order is rejected
`unsupported` before anything is sent. A buy is `buy`, a sale `sell`, a
short sale `sell_short`. The placement's ID is the order's `tag`, which
Tradier takes as letters, digits and dashes, as a placement's ID is.

**A replace** is `PUT /accounts/{id}/orders/{order_id}`: Tradier changes an
order's type, duration, limit and stop, the order keeping its ID, and never
its quantity, so a replace asking a new quantity is rejected `unsupported`,
nothing sent.

**Its statuses** (Tradier's "Get orders"): working while `pending`, `open`,
`partially_filled` or `pending_cancel`; `filled`; `canceled`; `expired`;
`rejected`. Any other is outcome unknown, the status as reported.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops

from . import trading
from .broker import Broker, BrokerError, Unanswered
from .kinds import TRADING
from .trading import Asked, Catalogue, Change, VenueOrder, VenueRefused, VenueUnanswered

SOURCE = "tradier"
#: How long the token's accounts are held before they are read again.
ACCOUNTS_READ_AGAIN = timedelta(minutes=10)

STATUSES: dict[str, str] = {
    **{
        status: trading.WORKING
        for status in ("pending", "open", "partially_filled", "pending_cancel")
    },
    "filled": trading.FILLED,
    "canceled": trading.CANCELLED,
    "expired": trading.EXPIRED,
    "rejected": trading.REJECTED,
}
SIDES: dict[int, str] = {
    ops.SIDE_BUY: "buy",
    ops.SIDE_SELL: "sell",
    ops.SIDE_SELL_SHORT: "sell_short",
}
ORDER_TYPES: dict[int, str] = {
    ops.ORDER_TYPE_MARKET: "market",
    ops.ORDER_TYPE_LIMIT: "limit",
    ops.ORDER_TYPE_STOP: "stop",
    ops.ORDER_TYPE_STOP_LIMIT: "stop_limit",
}
DURATIONS: dict[int, str] = {
    ops.TIME_IN_FORCE_DAY: "day",
    ops.TIME_IN_FORCE_GOOD_TILL_CANCELLED: "gtc",
}
_DAY_GTC = (ops.TIME_IN_FORCE_DAY, ops.TIME_IN_FORCE_GOOD_TILL_CANCELLED)
CATALOGUE: Catalogue = (
    (ops.ORDER_TYPE_MARKET, (ops.TIME_IN_FORCE_DAY,)),
    (ops.ORDER_TYPE_LIMIT, _DAY_GTC),
    (ops.ORDER_TYPE_STOP, _DAY_GTC),
    (ops.ORDER_TYPE_STOP_LIMIT, _DAY_GTC),
)
_PRICED = (ops.ORDER_TYPE_LIMIT, ops.ORDER_TYPE_STOP_LIMIT)
_STOPPED = (ops.ORDER_TYPE_STOP, ops.ORDER_TYPE_STOP_LIMIT)


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def listed(value: Any, outer: str, inner: str) -> list[Any]:
    """Tradier's list: `{outer: {inner: [...]}}`, one item as an object, none
    as `"null"` or nothing."""
    held = value.get(outer) if isinstance(value, dict) else None
    items = held.get(inner) if isinstance(held, dict) else None
    if isinstance(items, list):
        return items
    return [items] if isinstance(items, dict) else []


def order_of(said: Any) -> VenueOrder:
    """One of Tradier's orders, as the Trader reads it."""
    held = said if isinstance(said, dict) else {}
    last_quantity = trading.number(held.get("last_fill_quantity"))
    last_price = trading.number(held.get("last_fill_price"))
    return VenueOrder(
        order_id=str(held.get("id") or ""),
        client_order_id=str(held.get("tag") or ""),
        status=str(held.get("status") or ""),
        symbol=str(held.get("symbol") or ""),
        quantity=trading.number(held.get("quantity")),
        filled=trading.number(held.get("exec_quantity")) or Decimal(0),
        average=trading.number(held.get("avg_fill_price")) or None,
        limit=trading.number(held.get("price")),
        placed_at=trading.moment(held.get("create_date")),
        updated_at=trading.moment(held.get("transaction_date")),
        last_fill=(
            (last_quantity, last_price)
            if last_quantity is not None and last_price is not None and last_quantity > 0
            else None
        ),
        reason=str(held.get("reason_description") or ""),
    )


class TradierVenue:
    """The Trader's venue: the accounts the token reaches at Tradier."""

    statuses: dict[str, str] = STATUSES
    sides: dict[int, str] = SIDES
    source: str = SOURCE

    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self._accounts: tuple[str, ...] = ()
        self._read_at: datetime | None = None

    def _asking(self, work: Callable[[], Any]) -> Any:
        try:
            return work()
        except BrokerError as refused:
            raise VenueRefused(refused.code, refused.text, refused.raw_key) from None
        except Unanswered as lost:
            raise VenueUnanswered(str(lost), lost.raw_key) from None

    def accounts(self) -> tuple[str, ...]:
        """The accounts the token reaches, by their numbers: read again at
        most every ten minutes. A closed one is not traded."""
        now = self.broker.now()
        if self._accounts and self._read_at and now - self._read_at < ACCOUNTS_READ_AGAIN:
            return self._accounts
        answer = self._asking(self.broker.profile)
        self._accounts = tuple(
            str(each.get("account_number"))
            for each in listed(answer.value, "profile", "account")
            if isinstance(each, dict)
            and each.get("account_number")
            and str(each.get("status") or "active") != "closed"
        )
        self._read_at = now
        return self._accounts

    def catalogue(self, code: str) -> Catalogue:
        return CATALOGUE

    def place(self, code: str, asked: Asked) -> tuple[VenueOrder, str]:
        form = {
            "class": "equity",
            "symbol": asked.symbol,
            "side": SIDES[asked.side],
            "quantity": _text(asked.quantity),
            "type": ORDER_TYPES[asked.order_type],
            "duration": DURATIONS[asked.time_in_force],
            "tag": asked.placement_id,
        }
        if asked.limit is not None and asked.order_type in _PRICED:
            form["price"] = _text(asked.limit)
        if asked.stop is not None and asked.order_type in _STOPPED:
            form["stop"] = _text(asked.stop)
        answer = self._asking(lambda: self.broker.place(code, form))
        said = (answer.value or {}).get("order") if isinstance(answer.value, dict) else None
        placed = said if isinstance(said, dict) else {}
        # Tradier answers an order's ID and "ok"; its status is read next.
        return (
            VenueOrder(
                order_id=str(placed.get("id") or ""),
                client_order_id=asked.placement_id,
                status="pending",
                symbol=asked.symbol,
                quantity=asked.quantity,
                limit=asked.limit,
            ),
            answer.raw_key,
        )

    def orders(self, code: str) -> tuple[list[VenueOrder], str]:
        answer = self._asking(lambda: self.broker.orders(code))
        return [order_of(each) for each in listed(answer.value, "orders", "order")], answer.raw_key

    def cancel(self, code: str, order_id: str) -> str:
        answer = self._asking(lambda: self.broker.cancel(code, order_id))
        return str(answer.raw_key)

    def not_replaceable(self, change: Change) -> str:
        if change.quantity_changed:
            return "Tradier changes an order's type, duration and prices, never its quantity"
        if change.order_type not in ORDER_TYPES or change.side not in SIDES:
            return "Tradier changes the order types and sides it places"
        if change.time_in_force not in DURATIONS:
            return "Tradier takes no such duration"
        return ""

    def replace(
        self, code: str, order: VenueOrder | None, order_id: str, change: Change
    ) -> tuple[VenueOrder | None, str]:
        form = {
            "type": ORDER_TYPES[change.order_type],
            "duration": DURATIONS[change.time_in_force],
        }
        if change.limit is not None and change.order_type in _PRICED:
            form["price"] = _text(change.limit)
        if change.stop is not None and change.order_type in _STOPPED:
            form["stop"] = _text(change.stop)
        answer = self._asking(lambda: self.broker.change(code, order_id, form))
        # The order keeps its ID: nothing new to follow.
        return None, answer.raw_key

    def keep(self, name: str, record: dict[str, Any]) -> str:
        return self.broker.store.keep(
            TRADING,
            name,
            {"venue": SOURCE, "synthetic": self.broker.synthetic, **record},
            self.broker.now(),
        )
