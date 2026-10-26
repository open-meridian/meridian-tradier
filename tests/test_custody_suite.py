"""The custody suite (contract v23): every case Tradier presents, from
Tradier's own shapes.

Each case is mapped to what Tradier's brokerage API answers for it -- the
user's profile, an account's balances, positions, history and this
session's orders, and the quotes naming a holding's kind, as JSON in
Tradier's own shapes, served by a stand-in for its transport (`Answers`) --
and run through this plugin's own client (broker.py), reads and conversion
(custody.py) and pages (custody_pages.py), against the runner's recorder, as
a read does. Only the sidecar and the transport are stood in for. SIMULATED
ONLY: nothing reaches Tradier.

Tradier states no currency for any holding or amount: each linked
account's is supplied by the plugin's admin (the SDK's Account currency,
`account_currency`, contract v23), and every amount carries it with its
provenance, supplied by the person who set it. Until it is set nothing that
needs it is reported.

Every case passes but those Tradier never presents (`NOT_PRESENTED`), each
a closed-list or `about` case, with why in Tradier's terms.
`currency-not-stated` and `resolve-gives-the-currency-with-its-provenance`
pass on their supplied ways (the product owner's ruling, 2026-10-13): the
average cost's currency, and the currency offered on each resolve, each
with its entry, supplied by the person who set Account currency.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import urllib.parse
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import meridian
import pytest
from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import ANSWERED_BY_SDK, Recorder, run, suite
from meridian.testing import PageClient

from tradier import custody, page
from tradier.broker import Broker
from tradier.custody import Syncer
from tradier.kinds import Store
from tradier.page import State, pages
from tradier.settings import Config
from tradier.vendor import SANDBOX, RateLimiter, Response

Producer = Callable[[Recorder], Awaitable[None]]
Json = dict[str, Any]

NUMBER = "SYN-TRD-2002"
#: Monday 2026-10-12, 15:00 New York: the read's day.
NOW = datetime(2026, 10, 12, 19, 0, tzinfo=UTC)
TODAY = "2026-10-12"
ADMIN = "local|ada"
#: The Account currency setting's row for every linked account.
CURRENCY_ROW: Json = {"external_account": "", "currency": "USD", "changed_by": ADMIN}
TOMORROW = "2026-10-13"


def profile(**changes: Any) -> Json:
    """One account of Tradier's user profile, as `/user/profile` lists it."""
    base: Json = {
        "account_number": NUMBER,
        "classification": "individual",
        "date_created": "2024-10-07T14:11:09.000Z",
        "day_trader": False,
        "option_level": 2,
        "status": "active",
        "type": "margin",
        "last_update_date": "2026-10-12T13:00:00.000Z",
    }
    return {**base, **changes}


def position(symbol: str, quantity: str, cost: str = "2655.00") -> Json:
    """One of Tradier's positions, as `/accounts/{id}/positions` lists it."""
    return {
        "cost_basis": cost,
        "date_acquired": "2026-03-02T14:41:11.405Z",
        "id": 130089,
        "quantity": quantity,
        "symbol": symbol,
    }


def quote(symbol: str, kind: str = "stock") -> Json:
    """Tradier's quote of a symbol, as `/markets/quotes` answers it."""
    return {"symbol": symbol, "description": f"{symbol} Inc", "exch": "Q", "type": kind}


def event(kind: str, amount: str = "0", **detail: Any) -> Json:
    """One event of Tradier's history, of its type `kind`."""
    return {
        "amount": amount,
        "date": "2026-09-15T00:00:00Z",
        "type": kind,
        kind: {"description": f"{kind} {detail.get('symbol', '')}".strip(), **detail},
    }


def filled_today(symbol: str, quantity: str, price: str, side: str = "buy") -> Json:
    """One of this session's orders, filled, as `/accounts/{id}/orders` lists
    it."""
    return {
        "id": 228175,
        "type": "market",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "status": "filled",
        "duration": "day",
        "avg_fill_price": price,
        "exec_quantity": quantity,
        "last_fill_price": price,
        "last_fill_quantity": quantity,
        "remaining_quantity": "0",
        "create_date": f"{TODAY}T14:31:00.000Z",
        "transaction_date": f"{TODAY}T14:31:01.000Z",
        "class": "equity",
    }


def wrapped(items: list[Json], outer: str, inner: str) -> Json:
    """Tradier's list: one item as an object, none as "null"."""
    if not items:
        return {outer: "null"}
    return {outer: {inner: items if len(items) != 1 else items[0]}}


class Answers:
    """A stand-in for Tradier's transport (broker.Send), answering as its
    brokerage API does, from JSON in its shapes; `status` answers every
    request with that status instead, and `lost` never answers."""

    def __init__(
        self,
        profile_: Json,
        positions: list[Json],
        history: list[Json],
        cash: str = "0",
        orders: list[Json] | None = None,
        quotes: list[Json] | None = None,
    ) -> None:
        self.profile, self.positions, self.history = profile_, positions, history
        self.cash, self.orders, self.quotes = cash, orders or [], quotes or []
        self.status, self.lost = 200, False

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> Response:
        if self.lost:
            raise ConnectionResetError("no answer")
        if self.status != 200:
            return Response(self.status, {}, b"Invalid Access Token")
        path = urllib.parse.urlparse(url).path.removeprefix("/v1")
        account = f"/accounts/{self.profile['account_number']}"
        value: Any = {
            "/user/profile": {"profile": {"id": "id-syn", "account": self.profile}},
            f"{account}/balances": {
                "balances": {
                    "account_number": NUMBER,
                    "account_type": self.profile["type"],
                    "total_cash": self.cash,
                }
            },
            f"{account}/positions": wrapped(self.positions, "positions", "position"),
            f"{account}/history": wrapped(self.history, "history", "event"),
            f"{account}/orders": wrapped(self.orders, "orders", "order"),
            "/markets/quotes": wrapped(self.quotes, "quotes", "quote"),
        }[path]
        return Response(200, {"content-type": "application/json"}, json.dumps(value).encode())


class Read:
    """A Syncer over the recorder and a stand-in transport, the accounts
    linked; a read is `once()`."""

    def __init__(self, recorder: Recorder, answers: Answers) -> None:
        self.answers = answers
        self.broker = Broker(
            Store(Path(tempfile.mkdtemp())),
            None,
            SANDBOX,
            send=answers,
            limiter=RateLimiter(per_minute=6_000_000, sleep=lambda _: None),
            now=lambda: NOW,
            sleep=lambda _: None,
            keyless=True,
            synthetic=True,
        )
        self.syncer = Syncer(
            recorder,
            lambda: self.broker,
            paper=lambda: False,
            stale_after=lambda: timedelta(hours=36),
            currencies=lambda: self.currencies,
        )
        #: The Account currency setting's rows: every account's USD, set by a
        #: plugin admin.
        self.currencies: list[Json] = [CURRENCY_ROW]

    async def once(self) -> None:
        await self.syncer.run_once()


def settled(day: str) -> ops.ComputeDateResult:
    return ops.ComputeDateResult(
        date=day,
        outcome=ops.DATE_OUTCOME_COMPUTED,
        basis=ops.DateBasis(rule=ops.DateRuleRef(subject="XNAS", version=1)),
        business_day=True,
    )


def reading(
    profile_: Json | None = None,
    positions: list[Json] | None = None,
    history: list[Json] | None = None,
    *,
    cash: str = "0",
    orders: list[Json] | None = None,
    quotes: list[Json] | None = None,
    settles: str = "",
) -> Producer:
    """One read of an account holding `positions`, its history these; the
    date read answering each fill's settlement date `settles` where given."""

    async def produce(recorder: Recorder) -> None:
        if settles:
            recorder.answer("ComputeDate", lambda _: settled(settles))
        answers = Answers(
            profile_ or profile(), positions or [], history or [], cash, orders, quotes
        )
        await Read(recorder, answers).once()

    return produce


def then_answering(**failure: Any) -> Producer:
    """A read Tradier answered, then one it did not: refused (`status`) or
    lost, past Stale after."""

    async def produce(recorder: Recorder) -> None:
        read = Read(recorder, Answers(profile(), [], []))
        await read.once()
        read.syncer.status.last_good = NOW - timedelta(days=3)
        read.answers.status = failure.get("status", 200)
        read.answers.lost = failure.get("lost", False)
        await read.once()

    return produce


def ambiguous(recorder: Recorder) -> Awaitable[None]:
    recorder.answer(
        "ResolveIdentifier",
        lambda _: ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_AMBIGUOUS),
    )
    return reading(positions=[position("SPX", "1")], quotes=[quote("SPX", "index")])(recorder)


def thin(recorder: Recorder) -> Awaitable[None]:
    """A holding Tradier names by its symbol alone, stating no description of
    the security, which the platform does not know (contract v24): recorded
    unresolved, naming what it was given, never guessed."""
    recorder.answer(
        "ResolveIdentifier",
        lambda _: ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_NOT_FOUND),
    )
    return reading(positions=[position("ZZTOP", "5")], quotes=[{"symbol": "ZZTOP"}])(recorder)


def paged(**caller: Any) -> Callable[[Recorder], PageClient]:
    def client(recorder: Recorder) -> PageClient:
        syncer = Syncer(
            recorder, lambda: None, paper=lambda: False, stale_after=lambda: timedelta(hours=36)
        )
        syncer.status.accounts[NUMBER] = custody.AccountStatus(state="Current")
        syncer.profiles[NUMBER] = profile()
        page.use(State(config=Config(sample_data=True), syncer=syncer))
        return PageClient(pages, recorder, roles=("data", "custody", "connectivity"), **caller)

    return client


async def read_for_linking(recorder: Recorder) -> None:
    # The page client runs its own loop: off this one.
    answer = await asyncio.to_thread(paged()(recorder).get, "/links", "admin")
    assert answer.status == 200, answer.text


async def link_a_new_account(recorder: Recorder) -> None:
    """Account links' create and link, as a deployment admin's form sends it
    (the kit's account map): its custodian and type pre-filled from Tradier's."""
    answer = await asyncio.to_thread(
        paged(deployment_admin=True)(recorder).call_tool,
        "link_account",
        {"external_account_id": NUMBER, "intent": "create", "new_account_name": "Tradier margin"},
        level="admin",
    )
    assert answer.status == 200, answer.json


TYPES = (
    "trade, option, ach, wire, dividend, fee, tax, journal, check, transfer, adjustment and "
    "interest"
)
#: The cases Tradier never presents, each with why, in Tradier's terms.
NOT_PRESENTED = {
    "sync-delayed-by-design": (
        "Tradier serves balances and positions as they stand: nothing it serves of the "
        "holdings is late by design"
    ),
    "sync-holdings-unavailable": "Tradier's brokerage API serves every account's positions",
    "cash-net-of-a-fund-counted-in-cash": (
        "Tradier states a sweep as cash (a balance's `sweep`), never also as a position"
    ),
    "fund-larger-than-cash": (
        "Tradier states a sweep as cash (a balance's `sweep`), never also as a position"
    ),
    "activity-reinvestment": f"Tradier's history lists no reinvestment: its types are {TYPES}",
    "activity-split": f"Tradier's history lists no split: its types are {TYPES}",
    "activity-corporate-action": (
        f"Tradier's history lists no corporate action: its types are {TYPES}"
    ),
    "activity-moves-no-cash": f"Tradier's history lists no split: its types are {TYPES}",
    "activity-plan-code-not-linked": (
        "Tradier's history names a security by its symbol, never by a plan's own fund code"
    ),
    "activity-plan-code-linked-by-a-person": (
        "Tradier's history names a security by its symbol, never by a plan's own fund code"
    ),
    "activity-re-resolved-when-a-plan-code-is-linked-later": (
        "Tradier's history names a security by its symbol, never by a plan's own fund code"
    ),
    "reads-a-calendar": (
        "asks the date read for each fill's settlement date (ComputeDate); it reads no "
        "calendar's days"
    ),
    # Contract v28 (about options; ruling 602). Named through a table, not
    # as a literal key: meridian 0.1.52's check holds contract v27's suites.
    **{
        case: why
        for case, why in (
            (
                "reports-an-assignment",
                "Tradier's history states an option's assignment, exercise or expiry as an "
                "`option` entry naming no event, which it reports as not known: it reports no "
                "assignment",
            ),
        )
    },
}

HELD = [position("AAPL", "12.5")]
QUOTED = [quote("AAPL")]
PENDING = reading(
    positions=[position("AAPL", "30", "6372.00")],
    cash="1523.45",
    orders=[filled_today("AAPL", "5", "227.41")],
    quotes=QUOTED,
    settles=TOMORROW,
)


def history(*events: Json) -> Producer:
    return reading(positions=HELD, history=list(events), cash="1523.45", quotes=QUOTED)


PRODUCERS: dict[str, Producer] = {
    "sync-current": reading(),
    "sync-stale": then_answering(lost=True),
    "sync-needs-sign-in": then_answering(status=401),
    "sync-disabled": reading(profile(status="closed")),
    "account-kind-cash": reading(profile(type="cash")),
    "account-kind-margin": reading(profile(type="margin")),
    "account-kind-retirement": reading(profile(type="cash", classification="roth_ira")),
    # A type none of Tradier's three: not known, as reported.
    "account-kind-not-known": reading(profile(type="futures")),
    "read-accounts-for-linking": read_for_linking,
    "link-a-new-account": link_a_new_account,
    # The account's cash 0: the one row is the security's.
    "a-security-holding": reading(positions=HELD, quotes=QUOTED),
    "records-a-thinly-described-holding-unresolved": thin,
    "institution-not-stated": reading(positions=HELD, quotes=QUOTED),
    "currency-not-stated": reading(positions=HELD, quotes=QUOTED),
    "settled-quantity-not-stated": reading(positions=HELD, quotes=QUOTED),
    "pending-by-value-date": PENDING,
    "kind-not-converted-on-an-ambiguous-resolve": ambiguous,
    # Contract v14: each of Tradier's history types, converted to its kind.
    "activity-purchase": history(
        event("trade", "-586.25", symbol="AAPL", quantity="2.5", price="234.50")
    ),
    "activity-sale": history(event("trade", "562.50", symbol="AAPL", quantity="-2.5", price="225")),
    "activity-dividend": history(event("dividend", "3.25", quantity="0")),
    "activity-interest": history(event("interest", "0.42", quantity="0")),
    "activity-fee": history(event("fee", "-0.03", quantity="0")),
    "activity-tax": history(event("tax", "-0.49", quantity="0")),
    "activity-transfer-in": history(event("transfer", symbol="AAPL", quantity="10")),
    "activity-transfer-out": history(event("transfer", symbol="AAPL", quantity="-10")),
    "activity-contribution": history(event("ach", "5000.00", quantity="0")),
    "activity-withdrawal": history(event("wire", "-500.00", quantity="0")),
    "activity-journal": history(event("journal", "-200.00", quantity="0")),
    "activity-kind-not-converted": history(
        event("option", option_type="expiration", quantity="-1")
    ),
    "activity-signs": history(
        event("trade", "562.50", symbol="AAPL", quantity="-2.5", price="225.00")
    ),
    "resolve-gives-the-currency-with-its-provenance": reading(positions=HELD, quotes=QUOTED),
    "history-from-stated": reading(),
    # Contract v22: each fill's settlement date asked of the date read.
    "asks-for-a-settlement-date": PENDING,
}


def test_every_case_is_mapped_or_said_not_presented() -> None:
    every = {case.name for case in suite("custody").cases}
    # Contract v24: the two cases every suite holds, which the SDK answers.
    assert every == set(PRODUCERS) | set(NOT_PRESENTED) | set(ANSWERED_BY_SDK)
    assert not set(PRODUCERS) & set(NOT_PRESENTED)


def test_every_case_of_the_custody_suite_passes_but_those_tradier_never_presents() -> None:
    report = run("custody", PRODUCERS, not_presented=NOT_PRESENTED, instance_id="tradier")
    assert report.passed, report.failures
    assert report.not_presented == NOT_PRESENTED
    assert set(report.passed_cases) == set(PRODUCERS) | set(ANSWERED_BY_SDK)


def recorded(producer: Producer) -> Recorder:
    recorder = Recorder("tradier")

    async def produce() -> None:
        await producer(recorder)

    asyncio.run(produce())
    return recorder


def test_a_holding_is_resolved_offering_the_supplied_currency_never_filtering() -> None:
    """What Tradier states of a holding: its symbol, and its quote's kind and
    description; and the account's supplied currency offered as its own
    (W3.1), never a filter."""
    recorder = recorded(PRODUCERS["a-security-holding"])
    (resolved,) = [
        r for r in recorder.on("ResolveIdentifier") if r.identifiers[0].scheme == "symbol"
    ]
    assert resolved.stated_asset_class == ops.ASSET_CLASS_EQUITY
    assert resolved.stated_description == "AAPL Inc"
    assert resolved.stated_currency == "USD" and not resolved.currency
    (entry,) = resolved.provenance
    assert (entry.field, entry.person) == ("stated_currency", ADMIN)
    assert entry.kind == meridian.ProvenanceKind.PROVENANCE_KIND_SUPPLIED


def test_the_average_cost_is_derived_and_its_currency_supplied() -> None:
    recorder = recorded(PRODUCERS["currency-not-stated"])
    (row,) = recorder.on("RecordHolding")
    assert as_decimal(row.average_cost.amount) == Decimal("2655.00") / Decimal("12.5")
    said = {p.field: p for p in row.provenance}
    assert said["average_cost"].rule == custody.RULE_AVERAGE
    supplied = said["average_cost.currency_code"]
    assert supplied.kind == meridian.ProvenanceKind.PROVENANCE_KIND_SUPPLIED
    assert supplied.person == ADMIN and row.average_cost.currency_code == "USD"


def test_nothing_needing_the_currency_is_reported_until_it_is_supplied() -> None:
    """The account and its sync state are reported; its statement and its
    activity wait for an Account currency row covering it."""

    async def produce(recorder: Recorder) -> None:
        read = Read(recorder, Answers(profile(), HELD, [event("fee", "-0.03")], "10"))
        read.currencies = [
            {"external_account": "SYN-OTHER", "currency": "USD", "changed_by": ADMIN}
        ]
        await read.once()
        assert read.syncer.status.accounts[NUMBER].statement_state == "Waiting for Account currency"

    recorder = recorded(produce)
    assert recorder.on("ReportExternalAccounts") and recorder.on("ReportSyncStatus")
    assert not recorder.on("RecordHoldingsStatement") and not recorder.on("RecordActivity")
    own = recorded(reading(positions=HELD, quotes=QUOTED))
    assert own.on("RecordHoldingsStatement")


def test_the_settled_quantity_and_the_cash_are_less_what_is_pending() -> None:
    recorder = recorded(PENDING)
    rows = sorted(
        (as_decimal(row.quantity), as_decimal(row.settle_date_quantity))
        for row in recorder.on("RecordHolding")
    )
    assert rows == [
        (Decimal("30"), Decimal("25")),
        (Decimal("1523.45"), Decimal("1523.45") + Decimal(5) * Decimal("227.41")),
    ]


def test_an_events_derived_id_is_the_same_however_often_it_is_read() -> None:
    events = [event("fee", "-0.03"), event("fee", "-0.03"), event("tax", "-0.49")]
    first, again = (
        custody.activity_ids(events),
        custody.activity_ids(json.loads(json.dumps(events))),
    )
    assert first == again and len(set(first)) == 3
    assert first[0].endswith(":1") and first[1].endswith(":2")


def test_needing_sign_in_says_the_rule_it_was_derived_by() -> None:
    recorder = recorded(PRODUCERS["sync-needs-sign-in"])
    sent = recorder.on("ReportSyncStatus")[-1]
    assert sent.state == meridian.SyncState.SYNC_STATE_NEEDS_SIGN_IN
    assert f'derived by the rule "{custody.RULE_SIGN_IN}"' in sent.status_detail


@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ({"type": "cash"}, meridian.AccountKind.ACCOUNT_KIND_CASH),
        ({"type": "margin"}, meridian.AccountKind.ACCOUNT_KIND_MARGIN),
        ({"type": "pdt"}, meridian.AccountKind.ACCOUNT_KIND_MARGIN),
        (
            {"type": "margin", "classification": "traditional_ira"},
            meridian.AccountKind.ACCOUNT_KIND_RETIREMENT,
        ),
    ],
)
def test_each_of_tradiers_account_types(said: Json, kind: meridian.AccountKind) -> None:
    assert custody.account_kind(profile(**said)) == (kind, None)


def test_a_statement_waits_while_a_fill_has_no_settlement_date() -> None:
    """A pending quantity names its date: while the date read gives an
    unsettled fill none, the statement is withheld, and sent once it does."""
    withheld = recorded(
        reading(
            positions=[position("AAPL", "30")],
            orders=[filled_today("AAPL", "5", "1")],
            quotes=QUOTED,
        )
    )
    assert withheld.on("RecordHoldingsStatement") == [] and withheld.on("RecordHolding") == []
    assert recorded(PENDING).on("RecordHoldingsStatement")


def test_an_average_cost_that_does_not_divide_is_rounded_to_eight_places() -> None:
    assert custody.average(Decimal("6743.53"), Decimal("28")) == Decimal("240.84035714")
    assert custody.average(Decimal("2655.00"), Decimal("-12.5")) == Decimal("212.4")
