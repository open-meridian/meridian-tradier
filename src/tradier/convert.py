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
  price carries no size, and a quote (contract v19) carries them converted
  to shares.
- **Trades and quotes streamed** (contract v19): a time and sale
  (`timesale`) is a trade -- the exchange it printed on, its price and
  size in shares, Tradier's sequence number (`seq`), its session and flag,
  and whether it cancels or corrects one; a `quote` the consolidated best
  bid and offer, sizes in hundreds, to shares. The stream sends some
  numbers as text (`"price": "281.85"`) and some as numbers; both are read
  exactly, never through a float. Its `trade`, `tradex` and `summary`
  events repeat what a time and sale says and are not converted.
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
    """Epoch milliseconds, as a number or its text, in nanoseconds."""
    if isinstance(value, Decimal) and value == value.to_integral_value():
        value = int(value)
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


# ── Trades and quotes (contract v19) ────────────────────────────────────────

#: A number Tradier's stream sends as text.
NUMBER_TEXT = re.compile(r"-?\d+(?:\.\d+)?")
#: Tradier's stream's sizes of a quote: hundreds of shares.
ROUND_LOT = Decimal(100)


def number(value: object) -> object:
    """A number Tradier stated as a number or as its text, as a Decimal from
    its own text; anything else as it is (which then does not convert)."""
    if isinstance(value, str) and NUMBER_TEXT.fullmatch(value.strip()):
        return Decimal(value.strip())
    return value


@dataclass(frozen=True)
class SourceTrade:
    """One of Tradier's time and sales prints: the exchange it printed on
    (`exch`, Tradier's code), its price and size, Tradier's sequence number
    for it (`seq`), its session (`pre`, `regular` or `post`) and flag, and
    whether it cancels a print (`cancel`) or corrects one (`correction`)."""

    symbol: str
    at_ns: int
    venue_code: str
    sequence: int
    price: Decimal | None
    quantity: Decimal | None
    flag: str
    session: str
    correction: bool
    raw_key: str
    cancelled: bool = False
    unconverted: tuple[AsReported, ...] = ()

    @property
    def row_key(self) -> str:
        """The print's identity: the listing, the New York day and Tradier's
        sequence number, which a cancel of it repeats."""
        day = new_york_date(self.at_ns).isoformat()
        return f"{self.symbol}:t:{day}:{self.sequence}"


@dataclass(frozen=True)
class SourceQuote:
    """The consolidated best bid and offer as Tradier states it: a side with
    no price is empty; sizes in shares, from Tradier's hundreds."""

    symbol: str
    at_ns: int
    bid: Decimal | None
    ask: Decimal | None
    bid_size: Decimal | None
    ask_size: Decimal | None
    raw_key: str
    unconverted: tuple[AsReported, ...] = ()

    @property
    def row_key(self) -> str:
        return f"{self.symbol}:q:{self.at_ns}"


def timesale(message: Any, raw_key: str) -> SourceTrade | None:
    """A trade from a time and sale; None where its listing, time or
    sequence is not one."""
    symbol = spelled(str(message.get("symbol") or ""))
    at = _ms(number(message.get("date")) if message.get("date") is not None else None)
    sequence = number(message.get("seq"))
    if symbol is None or at is None or not isinstance(sequence, int | Decimal):
        return None
    values = _Values("timesale")
    return SourceTrade(
        symbol=symbol,
        at_ns=at,
        venue_code=str(message.get("exch") or ""),
        sequence=int(sequence),
        price=values.number("last", number(message.get("last")), positive=True),
        quantity=values.number("size", number(message.get("size")), positive=True),
        flag=str(message.get("flag") or ""),
        session=str(message.get("session") or ""),
        correction=message.get("correction") is True,
        raw_key=raw_key,
        cancelled=message.get("cancel") is True,
        unconverted=tuple(values.unconverted),
    )


def _side(
    values: _Values, price: object, size: object, price_name: str, size_name: str
) -> tuple[Decimal | None, Decimal | None]:
    stated = number(price)
    if stated is None or exact(stated) == 0:
        return None, None
    amount = values.number(price_name, stated, positive=True)
    lots = number(size)
    shares = values.number(size_name, lots, positive=True) if exact(lots) != 0 else None
    return amount, None if shares is None else shares * ROUND_LOT


def stream_quote(message: Any, raw_key: str) -> SourceQuote | None:
    """A quote from the stream's `quote` event: valid from the later of its
    sides' times."""
    symbol = spelled(str(message.get("symbol") or ""))
    times = [
        _ms(number(message.get(k))) for k in ("biddate", "askdate") if message.get(k) is not None
    ]
    held = [t for t in times if t is not None]
    if symbol is None or not held:
        return None
    values = _Values("quote")
    bid, bid_size = _side(values, message.get("bid"), message.get("bidsz"), "bid", "bidsz")
    ask, ask_size = _side(values, message.get("ask"), message.get("asksz"), "ask", "asksz")
    return SourceQuote(
        symbol, max(held), bid, ask, bid_size, ask_size, raw_key, tuple(values.unconverted)
    )


def quote_rows(fetched: Fetched) -> Iterator[SourceQuote]:
    """Each listing's quote of `/markets/quotes`, as a quote."""
    held = fetched.value.get("quotes") or {}
    for item in as_list(held.get("quote") if isinstance(held, dict) else None):
        symbol = spelled(str(item.get("symbol") or ""))
        times = [_ms(item.get(k)) for k in ("bid_date", "ask_date")]
        stamped = [t for t in times if t is not None]
        if symbol is None or not stamped:
            continue
        values = _Values("quotes")
        bid, bid_size = _side(values, item.get("bid"), item.get("bidsize"), "bid", "bidsize")
        ask, ask_size = _side(values, item.get("ask"), item.get("asksize"), "ask", "asksize")
        key = f"{fetched.raw_key}#{symbol}/quote"
        yield SourceQuote(
            symbol, max(stamped), bid, ask, bid_size, ask_size, key, tuple(values.unconverted)
        )


def streamed(message: Any, raw_key: str) -> list[SourceTrade | SourceQuote]:
    """What one of Tradier's stream events states: a time and sale, or a
    quote; nothing for any other."""
    if not isinstance(message, dict):
        return []
    kind = message.get("type")
    if kind == "timesale":
        trade = timesale(message, raw_key)
        return [trade] if trade is not None else []
    if kind == "quote":
        quote = stream_quote(message, raw_key)
        return [quote] if quote is not None else []
    return []


# ── Option chains (from 0.13.0; contract v28) ───────────────────────────────

#: Tradier's option symbol: the root, the expiration as yymmdd, C or P, and
#: the strike times 1,000 in 8 digits -- the OSI symbol with its root unpadded.
OPTION_SYMBOL = re.compile(
    r"^(?P<root>[A-Z0-9]{1,6})(?P<day>\d{6})(?P<right>[CP])(?P<strike>\d{8})$"
)
#: The rights Tradier names (`option_type`).
RIGHTS = {"call": "C", "put": "P"}


def expirations(fetched: Fetched) -> list[dt.date]:
    """An underlying's expiration dates as `/markets/options/expirations`
    lists them, earliest first; none where it lists none (`null`)."""
    held = fetched.value.get("expirations") if isinstance(fetched.value, dict) else None
    dates = as_list(held.get("date") if isinstance(held, dict) else None)
    out: set[dt.date] = set()
    for each in dates:
        try:
            out.add(dt.date.fromisoformat(str(each)))
        except ValueError:
            continue
    return sorted(out)


@dataclass(frozen=True)
class ChainOption:
    """One series of a chain as Tradier states it: its OSI symbol (the
    21-character key, root padded to 6), its root, right, strike and
    expiration, the shares one contract delivers (`contract_size`), its
    best bid and offer with their sizes in contracts and their times, and its
    volume and open interest, each None where Tradier states none."""

    osi: str
    underlying: str
    root: str
    right: str
    strike: Decimal
    expiration: dt.date
    contract_size: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    bid_size: Decimal | None
    ask_size: Decimal | None
    at_ns: int | None
    volume: Decimal | None
    open_interest: Decimal | None
    raw_key: str
    unconverted: tuple[AsReported, ...] = ()

    @property
    def standard(self) -> bool:
        """A standard contract: its root is its underlying's symbol and it
        delivers 100 shares. An adjusted one (a new root after a corporate
        action) states no deliverable here."""
        return self.root == self.underlying.replace(".", "") and self.contract_size == 100


def _option_side(
    values: _Values, price: object, size: object, name: str
) -> tuple[Decimal | None, Decimal | None]:
    """A side of an option's quote: no price (or 0) is an empty side; its
    size in contracts, as Tradier states it for an option."""
    if price is None or exact(price) == 0:
        return None, None
    amount = values.number(name, price, positive=True)
    contracts = values.number(f"{name}size", size, positive=True) if exact(size) != 0 else None
    return amount, contracts


def chain(fetched: Fetched, underlying: str) -> Iterator[ChainOption]:
    """Every series of `/markets/options/chains`, keyed by its OSI symbol;
    one whose symbol, right, strike or expiration does not read is left out
    and counted (`tradier:chains.symbol`)."""
    held = fetched.value.get("options") if isinstance(fetched.value, dict) else None
    for item in as_list(held.get("option") if isinstance(held, dict) else None):
        values = _Values("chains")
        stated = str(item.get("symbol") or "")
        found = OPTION_SYMBOL.match(stated)
        right = RIGHTS.get(str(item.get("option_type") or ""))
        strike = exact(item.get("strike"))
        try:
            expiration = dt.date.fromisoformat(str(item.get("expiration_date")))
        except ValueError:
            expiration = None
        if found is None or right is None or strike is None or strike <= 0 or expiration is None:
            yield ChainOption(
                osi="", underlying=underlying, root="", right="", strike=Decimal(0),
                expiration=dt.date.min, contract_size=None, bid=None, ask=None,
                bid_size=None, ask_size=None, at_ns=None, volume=None, open_interest=None,
                raw_key=f"{fetched.raw_key}#{stated}",
                unconverted=(as_reported(f"{SOURCE}:chains.symbol", stated[:64]),),
            )  # fmt: skip
            continue
        root = found.group("root")
        osi = f"{root:<6}{found.group('day')}{found.group('right')}{found.group('strike')}"
        bid, bid_size = _option_side(values, item.get("bid"), item.get("bidsize"), "bid")
        ask, ask_size = _option_side(values, item.get("ask"), item.get("asksize"), "ask")
        times = [_ms(item.get(k)) for k in ("bid_date", "ask_date")]
        stamped = [t for t in times if t is not None]
        yield ChainOption(
            osi=osi,
            underlying=underlying,
            root=str(item.get("root_symbol") or root),
            right=right,
            strike=strike,
            expiration=expiration,
            contract_size=values.number("contract_size", item.get("contract_size"), positive=True),
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            at_ns=max(stamped) if stamped else None,
            volume=values.number("volume", item.get("volume")),
            open_interest=values.number("open_interest", item.get("open_interest")),
            raw_key=f"{fetched.raw_key}#{stated}",
            unconverted=tuple(values.unconverted),
        )


def market_days(fetched: Fetched) -> dict[dt.date, bool]:
    """A month's days as `/markets/calendar` states them: open or not."""
    held = fetched.value.get("calendar") if isinstance(fetched.value, dict) else None
    days = held.get("days") if isinstance(held, dict) else None
    out: dict[dt.date, bool] = {}
    for item in as_list(days.get("day") if isinstance(days, dict) else None):
        try:
            day = dt.date.fromisoformat(str(item.get("date")))
        except (ValueError, AttributeError):
            continue
        out[day] = item.get("status") == "open"
    return out
