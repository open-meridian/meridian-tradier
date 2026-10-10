"""Tradier's market data, converted to what the plugin records.

The edge is the only place Tradier's vocabulary is read. Each converter takes
what Tradier sent, parsed with Decimals (vendor.parse), and the raw record it
was kept as, and returns observations named by the listing's one spelling
and Tradier's own exchange code, which lake.py resolves to the deployment's
instrument and venue before anything is recorded.

- **The daily close on the declared day.** The daily dataset's day is New
  York's, ending at 16:00, the exchanges' session close (`day_time_zone`
  America/New_York, `day_end_minute` 960). Tradier's daily bar names its
  date as a plain date (`"date": "2026-10-08"`), which is the business date.
  Its close is the day's close, valid from the previous session's close
  until this one's; once 16:00 has passed its `published` source time is
  that close, and before then the day is still forming, recorded under the
  same row key and restated as it fills. Tradier states no VWAP and no trade
  count for a day.
- **Live prices:** Tradier's quote is consolidated from every exchange. Its
  `last` is the last trade's price, at `trade_date`, on the exchange whose
  code Tradier prints (`exch`, Tradier's own letters, resolved as Tradier's
  code); its `bid` and `ask` are the consolidated best bid and offer, no
  venue. Tradier states `bidsize` and `asksize` in hundreds of shares; a
  price carries no size, so the sizes are kept in the raw record until the
  lake's quotes (contract v19) carry them, converted to shares.
- **Tradier's shapes:** a list of one is the one object, and none is `null`;
  both are read as lists here.
- **Exact.** A value that is not a number, or past the contract's Decimal (18
  places), does not convert: the row is not recorded, and Tradier's text is
  kept as reported (`tradier:history.close`) for the Datasets page to count.
- **One spelling of a share class.** Tradier spells Berkshire's B shares
  `BRK/B`; the plugin names the listing `BRK.B`, the spelling the retail
  pair shares, and asks Tradier in Tradier's own.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from meridian.edge import as_reported
from meridian.plugin.v1.operations_pb2 import AsReported

from .vendor import NS, Fetched

SOURCE = "tradier"
NEW_YORK = ZoneInfo("America/New_York")
#: The session's close, the daily dataset's day end: 16:00 New York.
DAY_END_MINUTE = 16 * 60
MOST_PLACES = 18
MOST_DIGITS = 38

#: A US listing in the one spelling: a root of capitals (digits after the
#: first), and a class or series after a dot.
SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,5}(?:\.[A-Z0-9]{1,4})?")


def spelled(symbol: str) -> str | None:
    """The listing in the one spelling this plugin names it by (`BRK.B`), from
    a symbol in any of the usual spellings, or None where it is not one."""
    candidate = symbol.strip().upper().replace("/", ".").replace("-", ".")
    return candidate if SYMBOL.fullmatch(candidate) else None


def tradier_symbol(symbol: str) -> str:
    """The listing as Tradier spells it: a share class after a slash."""
    return symbol.replace(".", "/")


# ── Days ────────────────────────────────────────────────────────────────────


def new_york_date(at_ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(at_ns / NS, NEW_YORK).date()


def new_york_midnight_ns(day: dt.date | str) -> int:
    date = dt.date.fromisoformat(day) if isinstance(day, str) else day
    moment = dt.datetime(date.year, date.month, date.day, tzinfo=NEW_YORK)
    return int(moment.timestamp()) * NS


def close_of(day: dt.date) -> int:
    """The moment a business date's session closes: 16:00 New York."""
    return new_york_midnight_ns(day) + DAY_END_MINUTE * 60 * NS


def previous_close_of(day: dt.date) -> int:
    return close_of(day - dt.timedelta(days=1))


# ── Values ──────────────────────────────────────────────────────────────────


def exact(value: object) -> Decimal | None:
    """A number exactly as Tradier stated it, or None where it is not one the
    contract carries: not a number, not finite, or past 18 places."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        return None
    if not number.is_finite():
        return None
    _, digits, exponent = number.as_tuple()
    if not isinstance(exponent, int) or -exponent > MOST_PLACES:
        return None
    if len(digits) + max(exponent, 0) > MOST_DIGITS:
        return None
    return number


def as_list(value: Any) -> list[Any]:
    """Tradier's list: a list, the one object, or none at all."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


@dataclass
class _Values:
    endpoint: str
    unconverted: list[AsReported] = field(default_factory=list)

    def number(self, name: str, value: object, *, positive: bool = False) -> Decimal | None:
        converted = exact(value)
        if converted is None or (positive and converted <= 0) or converted < 0:
            if value is not None:
                self.unconverted.append(
                    as_reported(f"{SOURCE}:{self.endpoint}.{name}", str(value)[:64])
                )
            return None
        return converted


# ── Daily bars ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DailyBar:
    """One listing's day, as Tradier's daily history states it."""

    symbol: str
    business_date: dt.date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    vwap: Decimal | None
    trade_count: int | None
    raw_key: str
    unconverted: tuple[AsReported, ...] = ()

    @property
    def row_key(self) -> str:
        return f"{self.symbol}:1d:{self.business_date.isoformat()}"

    @property
    def complete(self) -> bool:
        return self.close is not None and None not in (self.open, self.high, self.low)


def history(fetched: Fetched, symbol: str) -> Iterator[DailyBar]:
    """Every day of one listing's `/markets/history`, named by its one
    spelling."""
    held = fetched.value.get("history") or {}
    for index, item in enumerate(as_list(held.get("day") if isinstance(held, dict) else None)):
        values = _Values("history")
        try:
            day = dt.date.fromisoformat(str(item.get("date")))
        except ValueError:
            continue
        yield DailyBar(
            symbol=symbol,
            business_date=day,
            open=values.number("open", item.get("open"), positive=True),
            high=values.number("high", item.get("high"), positive=True),
            low=values.number("low", item.get("low"), positive=True),
            close=values.number("close", item.get("close"), positive=True),
            volume=values.number("volume", item.get("volume")),
            vwap=None,
            trade_count=None,
            raw_key=f"{fetched.raw_key}#{index}",
            unconverted=tuple(values.unconverted),
        )


# ── Live prices ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Quoted:
    """One live price: the last trade's (`last`), or a quote's side."""

    symbol: str
    kind: str
    amount: Decimal | None
    at_ns: int
    venue_code: str
    raw_key: str
    unconverted: tuple[AsReported, ...] = ()

    @property
    def row_key(self) -> str:
        return f"{self.symbol}:{self.kind}:{self.at_ns}"


def _ms(value: object) -> int | None:
    return value * 1_000_000 if isinstance(value, int) and value > 0 else None


def quotes(fetched: Fetched) -> Iterator[Quoted]:
    """`last`, `bid` and `ask` for each symbol of `/markets/quotes`, each
    named by the listing's one spelling. A side with no price is not sent."""
    held = fetched.value.get("quotes") or {}
    for item in as_list(held.get("quote") if isinstance(held, dict) else None):
        symbol = spelled(str(item.get("symbol") or ""))
        if symbol is None:
            continue
        for kind, price, when, exchange in (
            ("last", "last", "trade_date", "exch"),
            ("bid", "bid", "bid_date", ""),
            ("ask", "ask", "ask_date", ""),
        ):
            at = _ms(item.get(when))
            if at is None or item.get(price) is None or exact(item.get(price)) == 0:
                continue
            values = _Values("quotes")
            yield Quoted(
                symbol=symbol,
                kind=kind,
                amount=values.number(price, item.get(price), positive=True),
                at_ns=at,
                venue_code=str(item.get(exchange) or "") if exchange else "",
                raw_key=f"{fetched.raw_key}#{symbol}/{kind}",
                unconverted=tuple(values.unconverted),
            )
