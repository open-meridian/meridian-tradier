"""Trades and quotes in the lake's half (contract v19), what the suite does not
reach: a time and sale's attributes exactly as converted from its session
and flag, its sequence number kept, a cancel as the trade's next version
where it names one recorded here, quotes at most one a second per listing
in shares, trades only for listings under a standing want and only by the
stream; and the carried fix, one row an observation however many records of
its listing the deployment holds."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder

from tradier import conditions, convert
from tradier.lake import TRADES, Lake
from tradier.vendor import NS

from conftest import BRK, RECORDS, SPY, TQQQ, Clock, answer_records, at, synthetic_lake, want

DURING = at("2026-10-09", 15, 30)
LIVE_MS = "1791574200500"
NUMBERS = frozenset({"seq", "bid", "ask", "bidsz", "asksz"})


def event(**fields: Any) -> dict[str, Any]:
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


def made(tmp: Path, now: int = DURING) -> tuple[Recorder, Lake, Clock]:
    recorder = Recorder("tradier-1")
    answer_records(recorder, RECORDS)
    clock = Clock(now)
    return recorder, synthetic_lake(recorder, clock, tmp), clock


async def stand(recorder: Recorder, lake: Lake, *subjects: str, want_id: str = "WNT-T") -> None:
    wanted = want(
        *subjects,
        dataset="tradier-1:trades",
        data_type="meridian.v1.Trade",
        standing=True,
        want_id=want_id,
    )
    recorder.answer("ObservationsWanted", lambda _: wanted)
    await recorder.receive(observations_wanted=lake.on_want)


async def hear(lake: Lake, *events: dict[str, Any]) -> None:
    for n, said in enumerate(events):
        await lake.heard(convert.streamed(said, f"stream/t#{n}"))


def trades(recorder: Recorder) -> list[ops.Trade]:
    return [t for sent in recorder.on("RecordTrades") for t in sent.trades]


def quotes(recorder: Recorder) -> list[ops.Quote]:
    return [q for sent in recorder.on("RecordQuotes") for q in sent.quotes]


def eligible(e: ops.Eligibility) -> tuple[str, ...]:
    return tuple(
        ops.Eligible.Name(getattr(e, f)).removeprefix("ELIGIBLE_")
        for f in ("high_low", "open", "close", "volume")
    )


async def test_a_regular_print_is_recorded_with_every_eligibility_and_its_sequence(
    tmp_path: Path,
) -> None:
    recorder, lake, _ = made(tmp_path)
    await stand(recorder, lake, SPY)
    await hear(lake, event(type="timesale", symbol="SPY", seq=4434373, last="575.46", size="100"))
    await lake.flush(force=True)
    (trade,) = trades(recorder)
    assert (
        as_decimal(trade.price.amount) == Decimal("575.46") and trade.price.currency_code == "USD"
    )
    assert as_decimal(trade.quantity) == Decimal("100") and trade.source_sequence == 4434373
    assert trade.aggressor == ops.AGGRESSOR_UNSPECIFIED and not trade.cancelled
    assert eligible(trade.attributes.consolidated) == ("ELIGIBLE",) * 4
    assert eligible(trade.attributes.market_centre) == ("ELIGIBLE",) * 4
    meta = trade.meta
    assert meta.row_key == f"SPY:t:2026-10-09:4434373@{SPY}"
    assert meta.source.dataset == "tradier-1:trades" and meta.source.venue_id.startswith("VEN-")
    assert meta.valid_from_ns == int(LIVE_MS) * 10**6 and not meta.business_date
    assert [s.entity_id for s in meta.subjects] == [SPY]


def test_the_session_converts_and_a_flag_or_correction_is_kept_as_reported() -> None:
    regular = conditions.trade_attributes("", "regular", False)
    assert regular.characteristics == () and regular.consolidated == conditions.EVERY
    assert conditions.trade_attributes("", "normal", False).consolidated == conditions.EVERY
    after = conditions.trade_attributes("", "post", False)
    assert after.characteristics == ("extended_hours",)
    assert after.consolidated == (False, False, False, True)
    flagged = conditions.trade_attributes("X", "regular", False)
    assert flagged.consolidated == conditions.NOT_KNOWN
    assert [(u.scheme, u.code) for u in flagged.unconverted] == [("tradier:timesale.flag", "X")]
    corrected = conditions.trade_attributes("", "regular", True)
    assert [(u.scheme, u.code) for u in corrected.unconverted] == [
        ("tradier:timesale.correction", "true")
    ]


async def test_a_cancel_of_a_print_recorded_is_its_next_version_and_one_unknown_is_counted(
    tmp_path: Path,
) -> None:
    recorder, lake, _ = made(tmp_path)
    await stand(recorder, lake, SPY)
    stated = event(type="timesale", symbol="SPY", seq=1, last="575.40", size="100", session="pre")
    await hear(lake, stated)
    await lake.flush(force=True)
    await hear(
        lake,
        event(type="timesale", symbol="SPY", seq=1, last="575.40", size="100", cancel=True),
        event(type="timesale", symbol="SPY", seq=77, last="575.41", size="10", cancel=True),
    )
    await lake.flush(force=True)
    rows = trades(recorder)
    assert [(t.meta.row_key.split("@")[0].rsplit(":", 1)[1], t.cancelled) for t in rows] == [
        ("1", False),
        ("1", True),
    ]
    assert list(rows[1].attributes.characteristics) == [ops.TRADE_CHARACTERISTIC_EXTENDED_HOURS]
    assert lake.counts[TRADES].withdrawn == 1 and lake.counts[TRADES].unmatched == 1


async def test_trades_are_streamed_only_for_listings_under_a_standing_want(tmp_path: Path) -> None:
    recorder, lake, _ = made(tmp_path)
    await hear(lake, event(type="timesale", symbol="SPY", seq=1, last="575.40", size="100"))
    await lake.flush(force=True)
    assert not trades(recorder)
    await stand(recorder, lake, SPY)
    assert lake.streamed == ["SPY"]
    # A range is not Tradier's to answer: its history names no print.
    ranged = want(SPY, dataset="tradier-1:trades", data_type="meridian.v1.Trade", want_id="WNT-R")
    recorder.answer("ObservationsWanted", lambda _: ranged)
    await recorder.receive(observations_wanted=lake.on_want)
    (declined,) = recorder.on("DeclineWant")
    assert declined.want_id == "WNT-R" and declined.reason == ops.UNANSWERED_REASON_NOT_COVERED
    recorder.answer("WantWithdrawn", lambda _: [ops.WantWithdrawnEvent(want_id="WNT-T")])
    await recorder.receive(want_withdrawn=lake.on_withdrawn)
    assert lake.streamed == []


async def test_quotes_are_recorded_at_most_once_a_second_in_shares(tmp_path: Path) -> None:
    recorder, lake, clock = made(tmp_path)
    await stand(recorder, lake, SPY, BRK)
    for n, bid in enumerate(("575.41", "575.42", "575.43")):
        at_ms = str(int(LIVE_MS) + n)
        await hear(
            lake,
            event(
                type="quote",
                symbol="SPY",
                bid=bid,
                bidsz=3,
                ask="575.48",
                asksz=2,
                biddate=at_ms,
                askdate=at_ms,
            ),
        )
    await hear(lake, event(type="quote", symbol="BRK/B", bid="455.32", bidsz=1, ask=0, asksz=0))
    clock.now += 2 * NS
    await lake.flush()
    spy, brk = sorted(quotes(recorder), key=lambda q: q.meta.row_key, reverse=True)
    assert as_decimal(spy.bid.amount) == Decimal("575.43")
    assert as_decimal(spy.bid_quantity) == 300 and as_decimal(spy.ask_quantity) == 200
    assert spy.meta.source.dataset == "tradier-1:live" and spy.meta.source.venue_id == ""
    assert brk.HasField("bid") and not brk.HasField("ask") and not brk.HasField("ask_quantity")
    await lake.flush()
    assert len(quotes(recorder)) == 2


async def test_a_quote_a_reader_wants_is_read_from_tradiers_quotes_in_shares(
    tmp_path: Path,
) -> None:
    recorder, lake, _ = made(tmp_path, at("2026-10-10", 9))
    wanted = want(SPY, BRK, dataset="tradier-1:live", data_type="meridian.v1.Quote")
    recorder.answer("ObservationsWanted", lambda _: wanted)
    await recorder.receive(observations_wanted=lake.on_want)
    (sent,) = recorder.on("RecordQuotes")
    assert sent.want_id == "WNT-1"
    by = {q.meta.row_key.split(":")[0]: q for q in sent.quotes}
    assert as_decimal(by["SPY"].bid_quantity) == 300 and as_decimal(by["SPY"].ask_quantity) == 200
    assert not by["BRK.B"].HasField("bid") and by["BRK.B"].HasField("ask")
    assert not lake.standing  # not standing: nothing streamed


async def test_two_records_of_one_listing_each_have_their_own_rows(tmp_path: Path) -> None:
    # The carried fix: the deployment holds TQQQ as this source resolved it
    # and as a custodian's book holds it; each record's close and trade under
    # its own key, never one recorded over the other as a restatement.
    own = "LCL-TQQQ-OWN"
    recorder, lake, _ = made(tmp_path, at("2026-10-10", 9))
    lake.products.put(own, "TQQQ")
    await lake.daily([TQQQ, own], dt.date(2026, 10, 8), dt.date(2026, 10, 8))
    await lake.daily([own], dt.date(2026, 10, 8), dt.date(2026, 10, 8))
    rows = [p for sent in recorder.on("RecordPrices") for p in sent.prices]
    assert [p.meta.row_key for p in rows] == [
        f"TQQQ:1d:2026-10-08@{TQQQ}",
        f"TQQQ:1d:2026-10-08@{own}",
        f"TQQQ:1d:2026-10-08@{own}",
    ]
    assert [[s.entity_id for s in p.meta.subjects] for p in rows] == [[TQQQ], [own], [own]]
    assert rows[1] == rows[2]  # read again unchanged: the same raw record
    await stand(recorder, lake, TQQQ, own)
    await hear(lake, event(type="timesale", symbol="TQQQ", seq=5, last="82.45", size="300"))
    await lake.flush(force=True)
    made_rows = trades(recorder)
    assert [[s.entity_id for s in t.meta.subjects] for t in made_rows] == [[TQQQ], [own]]
    assert len({t.meta.row_key for t in made_rows}) == 2
