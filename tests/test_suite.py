"""The data suite, the SDK's own (meridian.suites; contract v23 from 0.7.0),
run unchanged against this plugin: every case mapped to the plugin's own conversion, from
Tradier's recorded exchange and stream, through the lake's half it runs in
production (lake.py), against the suite's `Recorder`.

Eleven cases are not presented, each with why (`NOT_PRESENTED`). Two are about
kinds of data Tradier's US stock data never publishes (`about`, from
contract v19): a currency's rate against another currency, and a crypto
asset's price. Three are about a field its time and sales never state
(`about_field`, from contract v20): the side that took liquidity
(`meridian.v1.Trade.aggressor`) -- the taker's side, and a maker's side
inverted -- and an odd lot (`meridian.v1.TradeAttributes.characteristics`),
which Tradier's flags may say but Tradier does not document, so its flags
are kept as reported rather than converted. And a restart's gap, backfilled
(`a-restarts-gap-backfilled`, about trades): Tradier's time and sales
history names no print by its sequence number, which a streamed trade's row
is keyed by, so reading it after a restart would record trades twice; the
gap is said on the Datasets page rather than filled. And two are contract
v22's calendar cases (`about` calendars and settlement dates): the plugin
dates a bar by the date Tradier states, and never reads a settlement
calendar or asks for a settlement date. And from contract v23, three are
about an event contract's outcomes (`about` outcomes), which Tradier's
stock data never states.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder, run

from tradier import convert
from tradier.lake import LIVE_KINDS, Standing

from conftest import (
    BRK,
    ISIN_ONLY,
    RECORDS,
    SPY,
    TQQQ,
    Clock,
    answer_records,
    at,
    synthetic_lake,
    want,
)

DAY = "2026-10-08"
#: Saturday morning after the synthetic week: every day of it final.
AFTER = at("2026-10-10", 9)
#: Thursday 2026-10-09, 15:00 New York: the session still open.
DURING = at("2026-10-09", 15)

Producer = Callable[[Recorder], Awaitable[None]]

#: The cases Tradier's stock data does not present, and why (above).
NOT_PRESENTED = {
    "an-fx-rate": "Tradier's US stock data states no currency's rate against another",
    "a-stablecoin-quote": "a data plugin of US stocks: Tradier states no crypto asset's price",
    "the-takers-side-stated": "Tradier's time and sales never state which side took liquidity",
    "the-makers-side-inverted": "Tradier's time and sales state neither side of a trade",
    "a-condition-converted": "Tradier documents no flag for an odd lot: its flags are as reported",
    "a-restarts-gap-backfilled": (
        "Tradier's time and sales history names no print by its sequence number, which a "
        "streamed trade is keyed by: read after a restart, it would record trades twice"
    ),
    "reads-a-calendar": ("dates each bar by the date Tradier states: reads no settlement calendar"),
    "asks-for-a-settlement-date": (
        "records bars and trades as Tradier publishes them; never computes a settlement date"
    ),
    "records-an-outcome": "Tradier's stock data lists no event contract, so states no outcome",
    "restates-a-disputed-outcome": (
        "Tradier's stock data lists no event contract, so states no outcome"
    ),
    "records-a-partial-payout": (
        "Tradier's stock data lists no event contract, so states no outcome"
    ),
}

#: A moment in the session, for the stream's events: epoch milliseconds.
LIVE_MS = "1791574200123"
#: The fields Tradier's stream sends as numbers; the rest as text.
NUMBERS = frozenset({"seq", "bid", "ask", "bidsz", "asksz"})


def event(**fields: Any) -> dict[str, Any]:
    """One of Tradier's stream events, its numbers parsed as Tradier's are:
    some as numbers, each a Decimal from its own text, the rest as text."""
    said = {"date": LIVE_MS, "biddate": LIVE_MS, "askdate": LIVE_MS, **fields}
    if said.get("type") == "timesale":
        said = {
            "exch": "Q",
            "flag": "",
            "cancel": False,
            "correction": False,
            "session": "regular",
            **said,
        }
    text = (
        "{"
        + ",".join(
            f"{json.dumps(k)}:{v if k in NUMBERS else json.dumps(v)}" for k, v in said.items()
        )
        + "}"
    )
    return dict(json.loads(text, parse_float=Decimal))


def producers(tmp: Path) -> dict[str, Producer]:
    def lake(recorder: Recorder, now: int = AFTER):  # type: ignore[no-untyped-def]
        answer_records(recorder, RECORDS)
        return synthetic_lake(recorder, Clock(now), tmp / uuid.uuid4().hex)

    async def wanted(recorder: Recorder, event: ops.ObservationsWantedEvent) -> None:
        held = lake(recorder)
        recorder.answer("ObservationsWanted", lambda _: event)
        await recorder.receive(observations_wanted=held.on_want)

    async def daily_close(recorder: Recorder) -> None:
        # The plugin resolves a listing by its own symbol, then records the
        # close the lake wants for it.
        held = lake(recorder)
        await held.seed(["BRK.B"])
        (subject,) = held.products.symbols
        recorder.answer("ObservationsWanted", lambda _: want(subject, business_date=DAY))
        await recorder.receive(observations_wanted=held.on_want)

    async def forming(recorder: Recorder) -> None:
        clock = Clock(DURING)
        answer_records(recorder, RECORDS)
        held = synthetic_lake(recorder, clock, tmp / "forming")
        await held.daily([SPY], dt.date(2026, 10, 9), dt.date(2026, 10, 9))
        clock.now = at("2026-10-09", 16, 30)
        await held.tick()

    async def exact(recorder: Recorder) -> None:
        # TQQQ's close on 2026-10-09 is stated to eighteen places.
        await wanted(recorder, want(TQQQ, business_date="2026-10-09"))

    async def bar(recorder: Recorder) -> None:
        # Tradier's daily history states no VWAP.
        await wanted(recorder, want(BRK, data_type="meridian.v1.Bar", business_date=DAY))

    async def streamed(recorder: Recorder, *messages: dict[str, Any], subject: str = SPY) -> None:
        # A standing want of the trades: the listing streamed, and what the
        # stream states recorded, as the plugin's stream hands it on.
        held = lake(recorder, DURING)
        event = want(
            subject, dataset="suite-plugin:trades", data_type="meridian.v1.Trade", standing=True
        )
        recorder.answer("ObservationsWanted", lambda _: event)
        await recorder.receive(observations_wanted=held.on_want)
        for n, said in enumerate(messages):
            await held.heard(convert.streamed(said, f"stream/suite#{n}"))
        await held.flush(force=True)

    async def not_converted(recorder: Recorder) -> None:
        # A flag Tradier does not document: kept as reported.
        await streamed(
            recorder,
            event(type="timesale", symbol="SPY", seq=8, last="575.46", size="50", flag="X"),
        )

    async def withdrawn_trade(recorder: Recorder) -> None:
        stated = event(type="timesale", symbol="SPY", seq=9, last="575.47", size="100")
        cancel = event(type="timesale", symbol="SPY", seq=9, last="575.47", size="100", cancel=True)
        await streamed(recorder, stated, cancel)

    async def quote(recorder: Recorder) -> None:
        await streamed(
            recorder,
            event(type="quote", symbol="SPY", bid="575.45", bidsz=3, ask="575.48", asksz=2),
        )

    async def one_sided(recorder: Recorder) -> None:
        # BRK/B's offer side empty: Tradier sends it as 0.
        await streamed(
            recorder,
            event(type="quote", symbol="BRK/B", bid="455.32", bidsz=1, ask=0, asksz=0),
            subject=BRK,
        )

    async def standing_streamed(recorder: Recorder) -> None:
        await streamed(
            recorder, event(type="timesale", symbol="SPY", seq=10, last="575.48", size="100")
        )

    async def ambiguous(recorder: Recorder) -> None:
        # The listing's symbol meets two of the deployment's records.
        held = lake(recorder)
        recorder.answer(
            "ResolveIdentifier",
            lambda _: ops.ResolveIdentifierResult(
                found=False, miss_reason=ops.MISS_REASON_AMBIGUOUS
            ),
        )
        await held.seed(["TQQQ"])

    async def venue(recorder: Recorder) -> None:
        # SPY's last trade printed on the exchange Tradier codes Q, resolved
        # as Tradier's code.
        await wanted(recorder, want(SPY, dataset="suite-plugin:live"))

    async def venue_not_held(recorder: Recorder) -> None:
        held = lake(recorder)
        recorder.answer(
            "ResolveVenue",
            lambda _: ops.ResolveVenueResult(found=False, miss_reason=ops.MISS_REASON_NOT_FOUND),
        )
        recorder.answer("ObservationsWanted", lambda _: want(SPY, dataset="suite-plugin:live"))
        await recorder.receive(observations_wanted=held.on_want)

    async def recorded_against(recorder: Recorder) -> None:
        await wanted(recorder, want(SPY, business_date=DAY))

    async def elsewhere(recorder: Recorder) -> None:
        # TQQQ as a custodian's book holds it, by its CUSIP and the
        # custodian's symbol: the record read (W3.6), Tradier's symbol found.
        await wanted(recorder, want(TQQQ, business_date=DAY))

    async def declined(recorder: Recorder) -> None:
        await wanted(recorder, want(ISIN_ONLY, business_date=DAY))

    async def licences(recorder: Recorder) -> None:
        # On start, its own declared datasets' licences (contract v20).
        from tradier.__main__ import read_licences
        from tradier.page import State

        recorder.answer(
            "ListDatasets",
            lambda _: ops.ListDatasetsResult(
                licences=[ops.DatasetLicence(dataset="suite-plugin:daily", kept=True)]
            ),
        )
        state = State()
        await read_licences(recorder, state)
        assert state.licensed == {"suite-plugin:daily"}

    async def withdrawn(recorder: Recorder) -> None:
        clock = Clock(AFTER)
        answer_records(recorder, RECORDS)
        held = synthetic_lake(recorder, clock, tmp / "withdrawn")
        held.standing["WNT-9"] = Standing("WNT-9", (SPY,), LIVE_KINDS, AFTER)
        recorder.answer(
            "WantWithdrawn",
            lambda _: [ops.WantWithdrawnEvent(want_id="WNT-9", dataset="suite-plugin:live")],
        )
        await recorder.receive(want_withdrawn=held.on_withdrawn)
        clock.now += 3600 * 10**9
        await held.tick()

    return {
        "a-daily-close": daily_close,
        "the-forming-day-restated": forming,
        "an-exact-price": exact,
        "a-daily-bar": bar,
        "an-asset-that-does-not-resolve": ambiguous,
        "a-venue-resolved": venue,
        "a-venue-not-held": venue_not_held,
        "a-want-recorded-against": recorded_against,
        "a-subject-another-source-resolved": elsewhere,
        "a-subject-declined": declined,
        "a-standing-want-withdrawn": withdrawn,
        "a-condition-not-converted": not_converted,
        "a-trade-withdrawn": withdrawn_trade,
        "a-quote-recorded": quote,
        "a-one-sided-quote": one_sided,
        "a-standing-want-streamed": standing_streamed,
        "a-trade-recorded": standing_streamed,
        "reads-its-datasets-licences": licences,
    }


def test_the_data_suite_passes_unchanged(tmp_path: Path) -> None:
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED)
    assert report.passed, report.failures
    # Contract v24: and the two cases every suite holds, which the SDK answers.
    assert len(report.passed_cases) == 20
    assert sorted(report.not_presented) == sorted(NOT_PRESENTED)


def test_a_price_read_through_a_float_fails_the_suite(tmp_path: Path, restore_parse: None) -> None:
    import json

    import tradier.vendor as vendor

    vendor.parse = lambda text: json.loads(text, parse_float=float)
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED)
    assert "an-exact-price" in report.failures, report.failures
