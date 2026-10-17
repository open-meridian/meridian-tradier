"""The custody role (contract v11, v14; W2.1 to W2.4, W2.8, W2.10), from
0.7.0: Tradier's view of each account the token reaches, which the
deployment's operations reconcile the book against, in SnapTrade 0.16.0's
shape and the custody template's (`meridian plugin new --role custody`).

Each read asks Tradier's brokerage API (broker.py) for the user's accounts
(`/user/profile`), and for each its balances (`/accounts/{id}/balances`),
positions (`/accounts/{id}/positions`), history (`/accounts/{id}/history`)
and this session's orders (`/accounts/{id}/orders`), and the quotes naming
each holding's kind (`/markets/quotes`); it keeps each answer as a raw
record before anything is converted from it, and reports, in the contract's
words:

- **the accounts** the token reaches (W2.8), each by its number, which is
  also the venue account code connectivity trades it under. Its kind is
  Tradier's: a retirement account where its `classification` is an IRA's
  (`traditional_ira`, `roth_ira`, `rollover_ira`, `sep_ira`), else its
  `type`: `cash` a cash account, `margin` and `pdt` (a pattern day trader's)
  a margin account; any other not known, as reported
  (`tradier:account-type`).
- **each one's sync state** (W2.1): current where Tradier answered; needs
  sign-in where Tradier refused the token (401 or 403), derived by the rule
  "Tradier refused the token": a person issues a new token at Tradier
  before anything new is served; disabled where Tradier says the account is
  closed, derived by its rule; stale where Tradier has not answered for
  longer than Stale after, the last read standing, derived by its rule. Each
  rule is said in the detail, since the sync status carries no provenance.
  How far back its history reaches (`history_from`) is the day Tradier says
  the account was created.
- **a statement** per account per read (W2.2, W2.3), as of the read's day in
  New York, naming Tradier, which the account does not name, as its
  custodian, derived from the connection: a row per position, and the cash
  (`total_cash`) where it is not zero. Each position names its security by
  Tradier's symbol, resolved stating what Tradier's quote says of it: its
  kind (`stock` an equity, `etf` and `mutual_fund` a fund, `option` a
  derivative; any other kept as reported) and its description. Its quantity
  is as Tradier states it, a negative one short; Tradier states its cost
  basis, so its average cost is the cost basis over the quantity, derived
  (rounded half-even to 8 places where it does not divide exactly).
- **the currency**: Tradier states none, for any holding or amount. Each
  linked account's currency is supplied by the plugin's admin, the SDK's
  common setting **Account currency** (`account_currency`, contract v23:
  the account's own row, else the plugin-wide one), and every amount is in
  it, said by its provenance, supplied by the person who set the row
  (`PROVENANCE_KIND_SUPPLIED`). A holding is resolved offering it as its
  currency, as W3.1 has a supplied currency offered. Until a row covers an
  account, nothing that needs the currency is reported for it: its accounts
  and sync state are, its statements and activities wait.
- **settled and pending** (the custody role's, contract v11): Tradier
  states neither for a security. Each fill traded before the as-of day
  (its history's trades, which Tradier updates nightly) and on it (this
  session's filled orders) is given its settlement date by the deployment's
  date read (ComputeDate), and one settling after the as-of day is a
  pending quantity on that date (on the cash too, the cost or proceeds), the
  date read asked as of the read. While it gives one of them no date, a
  pending quantity naming none, the statement is withheld, and read again
  on the next read. The settled quantity is the quantity less them, derived
  by that rule.
- **its activities** (W2.10, contract v14), as Tradier's history lists
  them: a `trade` a purchase or a sale by its quantity's sign; `dividend`,
  `interest`, `fee`, `tax` and `journal` their kinds; `ach`, `wire` and
  `check` a contribution or a withdrawal by the amount's sign; `transfer`
  units moved in or out by the quantity's sign, or cash by the amount's;
  any other type (`option`, `adjustment`) not known, as reported. Tradier
  gives an event no identifier, so each is derived: its day, its type, a
  checksum of the event as Tradier sent it, and its place among events
  alike on that day, the same however often it is read.
"""

from __future__ import annotations

import asyncio
import json
import logging
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import meridian
from meridian.edge import as_reported, derived, supplied_currency
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.connectivity import moment

from .broker import Broker, BrokerError, NoKey, Unanswered
from .venue import listed

log = logging.getLogger("tradier.custody")

#: The listing market's zone: the day a statement's as-of date, and a fill's
#: trade date, is in. US equities only (the SDK's Trader is told it).
MARKET_ZONE = ZoneInfo("America/New_York")

SOURCE = "tradier"
ACTIVITY_SCHEME = "tradier:history-type"
ACCOUNT_TYPE_SCHEME = "tradier:account-type"
SECURITY_TYPE_SCHEME = "tradier:security-type"
SYMBOL_SCHEME = "tradier:symbol"

RULE_SIGN_IN = "Tradier refused the token"
RULE_DISABLED = "Tradier says the account is closed"
RULE_STALE = "Tradier has not answered for longer than Stale after"
RULE_INSTITUTION = "the connection's broker: Tradier"
RULE_AVERAGE = (
    "the cost basis Tradier states, over the quantity, rounded half-even to 8 places where "
    "it does not divide exactly"
)
#: The places an average cost is rounded to where the division is not exact.
AVERAGE_PLACES = Decimal("1e-8")
RULE_SETTLED = (
    "the quantity less the account's fills not settled at the as-of date, each by the "
    "deployment's settlement date for it"
)
RULE_CASH_SETTLED = (
    "the cash less the cost, plus the proceeds, of the account's fills not settled at the "
    "as-of date"
)

#: Tradier's classifications that say an account is an IRA.
RETIREMENT = frozenset({"traditional_ira", "roth_ira", "rollover_ira", "sep_ira"})
_A = meridian.AccountKind
ACCOUNT_KINDS = {
    "cash": _A.ACCOUNT_KIND_CASH,
    "margin": _A.ACCOUNT_KIND_MARGIN,
    "pdt": _A.ACCOUNT_KIND_MARGIN,
}
#: Tradier's security types (a quote's `type`) that convert.
ASSET_CLASSES = {
    "stock": "equity",
    "etf": "fund",
    "mutual_fund": "fund",
    "option": "derivative",
}
#: How far back the fills that may still be unsettled are looked for.
UNSETTLED_DAYS = 10

_K = meridian.ActivityKind
KINDS: dict[str, meridian.ActivityKind] = {
    "dividend": _K.ACTIVITY_KIND_DIVIDEND,
    "interest": _K.ACTIVITY_KIND_INTEREST,
    "fee": _K.ACTIVITY_KIND_FEE,
    "tax": _K.ACTIVITY_KIND_TAX,
    "journal": _K.ACTIVITY_KIND_JOURNAL,
}
#: Tradier's types moving cash in or out, by the amount's sign.
CASH_MOVES = frozenset({"ach", "wire", "check"})

Json = dict[str, Any]


def _ns(at: datetime) -> int:
    return int(at.timestamp()) * 1_000_000_000 + at.microsecond * 1000


def day_ns(day: date) -> int:
    return _ns(datetime.combine(day, time(), UTC))


def stated(value: Any) -> Decimal | None:
    """A number Tradier stated, exactly; None where it gave none."""
    if value is None or value == "" or isinstance(value, bool) or value == "null":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def nonzero(value: Any) -> Decimal | None:
    number = stated(value)
    return None if number is None or number == 0 else number


#: The account's currency, supplied, as `meridian.edge.supplied_currency`
#: answers it for a field: its code and the provenance of that field.
Supplied = Callable[[str], "tuple[str, meridian.Provenance] | None"]


def average(cost: Decimal, quantity: Decimal) -> Decimal:
    """The cost basis over the quantity: exact where it divides, else
    rounded half-even to 8 places."""
    exact = cost / abs(quantity)
    rounded = exact.quantize(AVERAGE_PLACES, rounding=ROUND_HALF_EVEN)
    return exact if rounded == exact else rounded


# ── What a read is ───────────────────────────────────────────────────────


@dataclass
class AccountRead:
    """What Tradier answered for one account, and the raw records it is in."""

    number: str
    profile: Json
    balances: Json = field(default_factory=dict)
    balances_key: str = ""
    positions: list[Json] = field(default_factory=list)
    positions_key: str = ""
    history: list[tuple[Json, str]] = field(default_factory=list)
    orders: list[Json] = field(default_factory=list)
    failed: str = ""


@dataclass
class Read:
    """One read of Tradier: the user's accounts, each one's answers, and the
    quotes naming the holdings' kinds. `refused` where Tradier refused the
    token; `failed` where it did not answer otherwise."""

    at: datetime
    accounts: list[AccountRead] = field(default_factory=list)
    profile_key: str = ""
    quotes: dict[str, Json] = field(default_factory=dict)
    refused: str = ""
    failed: str = ""


def read(broker: Broker, starts: dict[str, str] | None = None) -> Read:
    """One read of every account the token reaches, each page kept as its
    raw record; an account's history from its `starts` day where given."""
    done = Read(at=broker.now())
    try:
        profile = broker.profile()
        done.profile_key = profile.raw_key
        for each in listed(profile.value, "profile", "account"):
            if isinstance(each, dict) and each.get("account_number"):
                done.accounts.append(AccountRead(str(each["account_number"]), each))
    except BrokerError as refused:
        if refused.status in (401, 403):
            done.refused = f"{refused.status} {refused.text}".strip()
        else:
            done.failed = str(refused)
        return done
    except (Unanswered, NoKey) as lost:
        done.failed = str(lost)
        return done
    symbols: set[str] = set()
    for account in done.accounts:
        try:
            _read_account(broker, account, (starts or {}).get(account.number, ""))
        except (BrokerError, Unanswered) as failed:
            account.failed = str(failed)
            continue
        symbols.update(str(p.get("symbol") or "") for p in account.positions)
    symbols.discard("")
    if symbols:
        try:
            quoted = broker.quotes(sorted(symbols))
            for quote in listed(quoted.value, "quotes", "quote"):
                if isinstance(quote, dict) and quote.get("symbol"):
                    done.quotes[str(quote["symbol"])] = quote
        except (BrokerError, Unanswered) as failed:
            log.info("the holdings' quotes were not read: %s", failed)
    return done


def _read_account(broker: Broker, account: AccountRead, start: str) -> None:
    balances = broker.balances(account.number)
    held = balances.value.get("balances") if isinstance(balances.value, dict) else None
    account.balances = held if isinstance(held, dict) else {}
    account.balances_key = balances.raw_key
    positions = broker.positions(account.number)
    account.positions = [
        p for p in listed(positions.value, "positions", "position") if isinstance(p, dict)
    ]
    account.positions_key = positions.raw_key
    for page in range(1, 51):
        answer = broker.history(account.number, page, start)
        events = [e for e in listed(answer.value, "history", "event") if isinstance(e, dict)]
        account.history.extend(
            (event, f"{answer.raw_key}#{index}") for index, event in enumerate(events)
        )
        if len(events) < 100:
            break
    orders = broker.orders(account.number)
    account.orders = [o for o in listed(orders.value, "orders", "order") if isinstance(o, dict)]


# ── Its conversion ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Converted:
    """One of Tradier's history events, converted, but for its instrument."""

    external_activity_id: str
    type: str
    kind: meridian.ActivityKind
    symbol: str
    trade_date: str
    units: Decimal | None
    price: meridian.Money | None
    amount: meridian.Money | None
    description: str

    @property
    def kind_as_reported(self) -> meridian.AsReported | None:
        if self.kind != _K.ACTIVITY_KIND_UNSPECIFIED:
            return None
        return as_reported(ACTIVITY_SCHEME, self.type or "(none)", self.description or None)


def activity_ids(events: list[Json]) -> list[str]:
    """Each event's derived ID: its day, its type, a checksum of the event as
    sent, and its place among events alike that day."""
    seen: dict[str, int] = {}
    ids = []
    for event in events:
        day = str(event.get("date") or "")[:10]
        kind = str(event.get("type") or "")
        digest = zlib.crc32(json.dumps(event, sort_keys=True, default=str).encode())
        stem = f"{day}:{kind}:{digest:08x}"
        seen[stem] = seen.get(stem, 0) + 1
        ids.append(f"{stem}:{seen[stem]}")
    return ids


def convert(event: Json, activity_id: str, currency: str) -> Converted | str:
    """One of Tradier's history events converted, or why it cannot be sent."""
    day = str(event.get("date") or "")[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        return f"event {activity_id} states no date"
    kind_said = str(event.get("type") or "")
    held = event.get(kind_said)
    detail: Json = held if isinstance(held, dict) else {}
    amount = nonzero(event.get("amount"))
    quantity = nonzero(detail.get("quantity"))
    description = str(detail.get("description") or "")[:200]
    symbol = str(detail.get("symbol") or "")
    units: Decimal | None = None
    price: meridian.Money | None = None
    kind = KINDS.get(kind_said, _K.ACTIVITY_KIND_UNSPECIFIED)
    if kind_said == "trade" and quantity is not None:
        kind = _K.ACTIVITY_KIND_PURCHASE if quantity > 0 else _K.ACTIVITY_KIND_SALE
        units = quantity
        said_price = stated(detail.get("price"))
        price = meridian.Money(said_price, currency) if said_price is not None else None
    elif kind_said in CASH_MOVES and amount is not None:
        kind = _K.ACTIVITY_KIND_CONTRIBUTION if amount > 0 else _K.ACTIVITY_KIND_WITHDRAWAL
    elif kind_said == "transfer" and quantity is not None:
        kind = _K.ACTIVITY_KIND_TRANSFER_IN if quantity > 0 else _K.ACTIVITY_KIND_TRANSFER_OUT
        units = quantity
    elif kind_said == "transfer" and amount is not None:
        kind = _K.ACTIVITY_KIND_CONTRIBUTION if amount > 0 else _K.ACTIVITY_KIND_WITHDRAWAL
    elif kind == _K.ACTIVITY_KIND_UNSPECIFIED:
        units = quantity
    return Converted(
        external_activity_id=activity_id,
        type=kind_said,
        kind=kind,
        symbol=symbol,
        trade_date=day,
        units=units,
        price=price,
        amount=None if amount is None else meridian.Money(amount, currency),
        description=description,
    )


@dataclass(frozen=True)
class Freshness:
    state: meridian.SyncState
    healthy: bool
    detail: str


def freshness(
    done: Read,
    account: AccountRead | None,
    last_good: datetime | None,
    stale_after: timedelta,
) -> Freshness | None:
    """An account's sync state from a read, or None where the read says
    nothing new (Tradier did not answer, within Stale after of its last)."""
    if done.refused:
        return Freshness(
            meridian.SyncState.SYNC_STATE_NEEDS_SIGN_IN,
            False,
            f'Tradier refused the token ({done.refused}); derived by the rule "{RULE_SIGN_IN}"',
        )
    failed = done.failed or (account.failed if account is not None else "")
    if failed:
        if last_good is not None and done.at - last_good > stale_after:
            return Freshness(
                meridian.SyncState.SYNC_STATE_STALE,
                False,
                f"Tradier last answered {last_good.isoformat(timespec='seconds')} "
                f'({failed}); derived by the rule "{RULE_STALE}"',
            )
        return None
    status = str((account.profile if account else {}).get("status") or "")
    if status == "closed":
        return Freshness(
            meridian.SyncState.SYNC_STATE_DISABLED,
            False,
            f'Tradier says {status}; derived by the rule "{RULE_DISABLED}"',
        )
    return Freshness(meridian.SyncState.SYNC_STATE_CURRENT, True, "Tradier answered")


def account_kind(profile: Json) -> tuple[meridian.AccountKind, meridian.AsReported | None]:
    """An account's kind from Tradier's classification and type, or not known
    as reported."""
    if str(profile.get("classification") or "") in RETIREMENT:
        return _A.ACCOUNT_KIND_RETIREMENT, None
    said = str(profile.get("type") or "")
    if said in ACCOUNT_KINDS:
        return ACCOUNT_KINDS[said], None
    return _A.ACCOUNT_KIND_UNSPECIFIED, as_reported(
        ACCOUNT_TYPE_SCHEME, said or "(none)", f"Tradier's account type {said or '(not stated)'}"
    )


def external_account(profile: Json, paper: bool) -> meridian.ExternalAccount:
    number = str(profile.get("account_number") or "")
    kind, reported = account_kind(profile)
    return meridian.ExternalAccount(
        external_account_id=number,
        name=f"Tradier {'sandbox' if paper else ''} {number}".replace("  ", " "),
        account_kind=kind,
        account_kind_as_reported=reported,
    )


def institution(paper: bool) -> str:
    return "Tradier (sandbox)" if paper else "Tradier"


# ── Sending ──────────────────────────────────────────────────────────────


class Unsettled(Exception):
    """A fill the date read gives no settlement date yet: the statement is
    withheld, since a pending quantity names its date."""


@dataclass
class Recorded:
    """What one account's read came to, for the pages."""

    statement: str = ""
    rows: int = 0
    stopped: str = ""
    unlinked: bool = False


class Custody:
    """Sends what a read of Tradier says through the SDK's typed operations."""

    def __init__(
        self, plugin: Any, paper: bool = False, currencies: list[Json] | None = None
    ) -> None:
        self._plugin = plugin
        self.paper = paper
        #: The Account currency setting's rows, as delivered.
        self.currencies = currencies or []
        #: Each symbol resolved in this read, by symbol.
        self._resolved: dict[str, str] = {}

    def supplied(self, number: str) -> Supplied:
        """An account's supplied currency for a field, with its provenance."""
        return lambda field: supplied_currency(self.currencies, number, field)

    async def accounts(self, done: Read) -> None:
        if done.accounts:
            await self._plugin.report_external_accounts(
                accounts=[external_account(a.profile, self.paper) for a in done.accounts]
            )

    async def sync(self, number: str, fresh: Freshness, done: Read, history_from: str = "") -> None:
        last = _ns(done.at) if fresh.healthy else 0
        await self._plugin.report_sync_status(
            source=SOURCE,
            external_account_id=number,
            state=fresh.state,
            connection_healthy=fresh.healthy,
            status_detail=fresh.detail[:400],
            observed_at_ns=_ns(done.at),
            last_synced_at_ns=last,
            holdings_as_of_ns=last,
            history_from=history_from,
        )

    async def resolve(
        self, symbol: str, as_of_ns: int, quote: Json | None = None, number: str = ""
    ) -> str:
        """The deployment's record for a symbol, stating what Tradier's quote
        says of it, and offering the account's supplied currency as its own
        with its provenance (W3.1, contract v23), never as a filter; "" where
        none, or more than one, record matches, the miss reported."""
        if symbol in self._resolved:
            return self._resolved[symbol]
        supplied = self.supplied(number)("stated_currency") if number else None
        currency, entry = supplied if supplied is not None else ("", None)
        identifiers = [meridian.Identifier(scheme="symbol", value=symbol, source=SOURCE)]
        said = str((quote or {}).get("type") or "")
        converted = ASSET_CLASSES.get(said, "")
        found = await self._plugin.resolve_identifier(
            identifiers=identifiers,
            as_of_ns=as_of_ns,
            stated_asset_class=converted or None,
            stated_currency=currency,
            provenance=[entry] if entry is not None else [],
            stated_description=str((quote or {}).get("description") or ""),
        )
        instrument = str(found.instrument_id or "") if found.found else ""
        if not instrument:
            await self._plugin.report_missing_instrument(
                source=SOURCE,
                identifiers=identifiers,
                as_of_ns=as_of_ns,
                reason=found.miss_reason or ops.MISS_REASON_NOT_FOUND,
                asset_class=converted or None,
                asset_class_as_reported=(
                    as_reported(SECURITY_TYPE_SCHEME, said) if said and not converted else None
                ),
                observed_at_ns=as_of_ns,
            )
        self._resolved[symbol] = instrument
        return instrument

    def _fills(self, account: AccountRead, as_of: date) -> list[tuple[str, Decimal, Decimal, date]]:
        """The account's fills that may be unsettled at the as-of date: its
        history's trades before it (updated nightly), and this session's
        filled orders on it; each its symbol, units, price and trade date."""
        found: list[tuple[str, Decimal, Decimal, date]] = []
        ids = activity_ids([event for event, _ in account.history])
        for (event, _), activity_id in zip(account.history, ids, strict=True):
            converted = convert(event, activity_id, "")
            if isinstance(converted, str) or converted.type != "trade":
                continue
            if converted.units is None or converted.price is None:
                continue
            traded = date.fromisoformat(converted.trade_date)
            if traded < as_of and (as_of - traded).days <= UNSETTLED_DAYS:
                price = Decimal(converted.price.amount)
                found.append((converted.symbol, converted.units, price, traded))
        for order in account.orders:
            at = moment(order.get("transaction_date"))
            filled = nonzero(order.get("exec_quantity"))
            paid = stated(order.get("avg_fill_price"))
            if at is None or filled is None or paid is None:
                continue
            if at.astimezone(MARKET_ZONE).date() != as_of:
                continue
            sells = str(order.get("side") or "").startswith("sell")
            units = -filled if sells else filled
            found.append((str(order.get("symbol") or ""), units, paid, as_of))
        return found

    async def _pending(
        self, done: Read, account: AccountRead, as_of: date
    ) -> tuple[dict[str, list[tuple[str, Decimal]]], list[tuple[str, Decimal]]]:
        """Each symbol's fills not settled at the as-of date, by their value
        dates from the date read ("" where it gives none), and the cash's."""
        securities: dict[str, list[tuple[str, Decimal]]] = {}
        cash: list[tuple[str, Decimal]] = []
        for symbol, units, price, traded in self._fills(account, as_of):
            instrument = await self.resolve(
                symbol, day_ns(traded), done.quotes.get(symbol), account.number
            )
            value_date = ""
            if instrument:
                answer = await self._plugin.compute_date(
                    settlement=ops.SettlementDateInputs(
                        instrument_id=instrument, trade_date=traded.isoformat()
                    ),
                    as_of_ns=_ns(done.at),
                )
                if answer.outcome == ops.DATE_OUTCOME_COMPUTED and answer.date:
                    value_date = str(answer.date)
            if not value_date:
                raise Unsettled(f"no settlement date for a fill of {symbol} on {traded}")
            if date.fromisoformat(value_date) <= as_of:
                continue
            securities.setdefault(symbol, []).append((value_date, units))
            cash.append((value_date, -units * price))
        return securities, cash

    async def statement(self, done: Read, account: AccountRead) -> Recorded:
        """W2.2 to W2.4: the account's positions and its cash as of the
        read's day, each row with its raw record and the provenance of every
        value this plugin closed; withheld while no Account currency covers
        the account."""
        outcome = Recorded()
        number = account.number
        currency = self.supplied(number)
        found_currency = currency("currency")
        if found_currency is None:
            outcome.stopped = "no Account currency covers the account"
            return outcome
        code = found_currency[0]

        def money(amount: Decimal) -> meridian.Money:
            return meridian.Money(amount, code)

        def supplied(field: str) -> meridian.Provenance:
            held = currency(field)
            assert held is not None
            return held[1]

        as_of = done.at.astimezone(MARKET_ZONE).date()
        as_of_ns = day_ns(as_of)
        rows: list[dict[str, Any]] = []
        try:
            pending, cash_pending = await self._pending(done, account, as_of)
        except Unsettled as waiting:
            outcome.stopped = str(waiting)
            log.info("the statement of %s waits: %s", number, waiting)
            return outcome
        for index, position in enumerate(account.positions):
            symbol = str(position.get("symbol") or "")
            quantity = stated(position.get("quantity"))
            if not symbol or quantity is None or quantity == 0:
                continue
            moves = pending.get(symbol, [])
            settled = quantity - sum((units for _, units in moves), Decimal(0))
            instrument = await self.resolve(symbol, as_of_ns, done.quotes.get(symbol), number)
            cost = stated(position.get("cost_basis"))
            provenance = [derived("settle_date_quantity", RULE_SETTLED)]
            if cost is not None:
                provenance += [
                    derived("average_cost", RULE_AVERAGE),
                    supplied("average_cost.currency_code"),
                ]
            rows.append(
                {
                    **(
                        {"instrument_id": instrument}
                        if instrument
                        else {
                            "unresolved_identifiers": [
                                meridian.Identifier(scheme="symbol", value=symbol, source=SOURCE)
                            ]
                        }
                    ),
                    "quantity": quantity,
                    "side": (
                        meridian.HoldingSide.HOLDING_SIDE_LONG
                        if quantity > 0
                        else meridian.HoldingSide.HOLDING_SIDE_SHORT
                    ),
                    "settle_date_quantity": settled,
                    "pending": [
                        meridian.ReportedPending(value_date=day, quantity=units)
                        for day, units in moves
                    ],
                    "average_cost": None if cost is None else money(average(cost, quantity)),
                    "raw_record": self._plugin.raw_record(f"{account.positions_key}#{index}"),
                    "provenance": provenance,
                }
            )
        cash = nonzero(account.balances.get("total_cash"))
        if cash is not None:
            settled_cash = cash - sum((amount for _, amount in cash_pending), Decimal(0))
            found = await self._plugin.resolve_identifier(
                identifiers=[meridian.Identifier(scheme="iso4217", value=code)],
                as_of_ns=as_of_ns,
            )
            rows.append(
                {
                    "instrument_id": str(found.instrument_id or ""),
                    "quantity": cash,
                    "side": meridian.HoldingSide.HOLDING_SIDE_LONG,
                    "settle_date_quantity": settled_cash,
                    "pending": [
                        meridian.ReportedPending(value_date=day, quantity=amount)
                        for day, amount in cash_pending
                    ],
                    "market_value": money(cash),
                    "raw_record": self._plugin.raw_record(f"{account.balances_key}#total_cash"),
                    "provenance": [
                        derived("settle_date_quantity", RULE_CASH_SETTLED),
                        supplied("market_value.currency_code"),
                    ],
                }
            )
        try:
            opened = await self._plugin.record_holdings_statement(
                source=SOURCE,
                external_statement_id=f"{number}:{done.at.strftime('%Y%m%dT%H%M%S%fZ')}",
                external_account_id=number,
                institution=institution(self.paper),
                as_of_date=as_of.isoformat(),
                read_at_ns=_ns(done.at),
                expected_rows=len(rows),
                raw_record=self._plugin.raw_record(account.balances_key),
                provenance=[derived("institution", RULE_INSTITUTION)],
            )
            outcome.statement, outcome.rows = opened.statement_id, len(rows)
            if opened.already_recorded:
                return outcome
            for row in rows:
                await self._plugin.record_holding(
                    statement_id=opened.statement_id, external_account_id=number, **row
                )
        except meridian.MeridianError as refused:
            outcome.stopped = str(refused)
            outcome.unlinked = isinstance(refused, meridian.NotLinked)
            log.info("the statement of %s stopped: %s", number, refused)
        return outcome

    async def activities(
        self, account: AccountRead, skip: Callable[[str], bool] = lambda _: False
    ) -> list[tuple[Converted, str]]:
        """W2.10: each history event, with the raw record it is in, sent to
        the street, one per call; what was sent, for History."""
        number = account.number
        sent: list[tuple[Converted, str]] = []
        currency = self.supplied(number)
        found_currency = currency("currency")
        if found_currency is None:
            return sent
        code = found_currency[0]
        ids = activity_ids([event for event, _ in account.history])
        for (event, key), activity_id in zip(account.history, ids, strict=True):
            converted = convert(event, activity_id, code)
            if isinstance(converted, str):
                log.warning("%s: %s", number, converted)
                continue
            if skip(converted.external_activity_id):
                continue
            as_of_ns = day_ns(date.fromisoformat(converted.trade_date))
            instrument = (
                await self.resolve(converted.symbol, as_of_ns, None, number)
                if converted.symbol
                else ""
            )
            provenance = [
                held[1]
                for field, value in (
                    ("price.currency_code", converted.price),
                    ("amount.currency_code", converted.amount),
                )
                if value is not None and (held := currency(field)) is not None
            ]
            try:
                await self._plugin.record_activity(
                    external_account_id=number,
                    source=SOURCE,
                    activity=meridian.CustodialActivity(
                        external_activity_id=converted.external_activity_id,
                        kind=converted.kind,
                        kind_as_reported=converted.kind_as_reported,
                        trade_date=converted.trade_date,
                        units=converted.units,
                        price=converted.price,
                        amount=converted.amount,
                        description=converted.description,
                        instrument_id=instrument,
                        instrument_as_reported=(
                            as_reported(SYMBOL_SCHEME, converted.symbol)
                            if converted.symbol and not instrument
                            else None
                        ),
                        raw_record=self._plugin.raw_record(key),
                        provenance=provenance,
                    ),
                )
            except meridian.NotLinked as refused:
                log.info("the activities of %s stopped: %s", number, refused)
                break
            except (meridian.MeridianError, ValueError) as refused:
                log.warning(
                    "activity %s was not recorded: %s", converted.external_activity_id, refused
                )
                continue
            sent.append((converted, instrument))
        return sent


# ── The schedule ─────────────────────────────────────────────────────────


@dataclass
class AccountStatus:
    """What the pages show of one account: never a token."""

    state: str = "Not read yet"
    detail: str = ""
    statement_as_of: str = ""
    statement_state: str = ""
    activities: list[tuple[Converted, str]] = field(default_factory=list)


@dataclass
class Status:
    """What the pages show of custody: each account by its number."""

    accounts: dict[str, AccountStatus] = field(default_factory=dict)
    last_read: datetime | None = None
    last_good: datetime | None = None
    error: str = ""


STATES = {
    meridian.SyncState.SYNC_STATE_CURRENT: "Current",
    meridian.SyncState.SYNC_STATE_STALE: "Stale",
    meridian.SyncState.SYNC_STATE_NEEDS_SIGN_IN: "Needs sign-in",
    meridian.SyncState.SYNC_STATE_DISABLED: "Disabled",
}


class Syncer:
    """Reads Tradier each Read every, and reports what it said."""

    def __init__(
        self,
        plugin: Any,
        broker: Callable[[], Broker | None],
        *,
        paper: Callable[[], bool],
        stale_after: Callable[[], timedelta],
        linked: Callable[[str], bool] = lambda _: True,
        currencies: Callable[[], list[Json]] = list,
    ) -> None:
        self._plugin = plugin
        self._currencies = currencies
        self._broker = broker
        self._paper = paper
        self._stale_after = stale_after
        self._linked = linked
        self.status = Status()
        #: Each account's profile as Tradier last answered it, by number.
        self.profiles: dict[str, Json] = {}
        self._recorded: set[str] = set()
        self._backfilled: set[str] = set()

    def _recorded_of(self, number: str) -> Callable[[str], bool]:
        """Whether one of an account's activities was recorded already."""
        return lambda activity_id: f"{number}/{activity_id}" in self._recorded

    async def run_once(self) -> None:
        broker = self._broker()
        if broker is None:
            return
        since = (broker.now() - timedelta(days=UNSETTLED_DAYS)).date().isoformat()
        starts = {number: since for number in self._backfilled}
        done = await asyncio.to_thread(read, broker, starts)
        custody = Custody(self._plugin, self._paper(), self._currencies())
        self.status.last_read = done.at
        answered = not done.failed and not done.refused
        if answered:
            await custody.accounts(done)
        by_number = {account.number: account for account in done.accounts}
        if answered:
            self.profiles = {number: account.profile for number, account in by_number.items()}
        numbers = list(by_number) if answered else list(self.status.accounts)
        last_good = self.status.last_good
        if answered:
            self.status.last_good = done.at
        self.status.error = done.failed or done.refused
        for number in numbers:
            account = by_number.get(number)
            shown = self.status.accounts.setdefault(number, AccountStatus())
            fresh = freshness(done, account, last_good, self._stale_after())
            if fresh is None:
                continue
            shown.state, shown.detail = STATES.get(fresh.state, ""), fresh.detail
            created = moment((account.profile if account else {}).get("date_created"))
            await custody.sync(
                number,
                fresh,
                done,
                created.astimezone(MARKET_ZONE).date().isoformat() if created else "",
            )
            if account is None or not fresh.healthy or not self._linked(number):
                continue
            if custody.supplied(number)("currency") is None:
                # Tradier states no currency: nothing that needs one is sent
                # until the plugin's admin supplies it (contract v23, W3.1).
                shown.statement_state = "Waiting for Account currency"
                log.info("%s: no Account currency covers it; nothing reported", number)
                continue
            recorded = await custody.statement(done, account)
            shown.statement_as_of = done.at.astimezone(MARKET_ZONE).date().isoformat()
            shown.statement_state = (
                "Not linked" if recorded.unlinked else ("Stopped" if recorded.stopped else "Closed")
            )
            sent = await custody.activities(account, self._recorded_of(number))
            self._recorded.update(f"{number}/{c.external_activity_id}" for c, _ in sent)
            shown.activities = (sent + shown.activities)[:200]
            self._backfilled.add(number)
            log.info("read %s: %d rows, %d activities", number, recorded.rows, len(sent))
