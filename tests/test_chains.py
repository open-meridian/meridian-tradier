"""Option chains (from 0.13.0; contract v28, ruling 660): an underlying's chain
wanted of `options` (or the sandbox's `options_delayed`), read from Tradier's
expirations and chains -- the built-in exchange, shaped on Tradier's
documented responses -- and recorded under the underlying, keyed by each
series' OSI symbol, never resolved or minted (chains.py)."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import Latency
from meridian.suites import Recorder

from tradier import chains, convert, synthetic
from tradier.synthetic import exchange
from tradier.vendor import Fetched

from conftest import RECORDS, SPY, Clock, answer_records, at, synthetic_lake, want

INSTANCE = "tradier-1"
#: Saturday 2026-10-10, 09:00 New York: no session today.
SATURDAY = at("2026-10-10", 9)
#: Thursday 2026-10-08, 15:00 New York: the session open.
THURSDAY = at("2026-10-08", 15)
SPX = "LCL-SPX"


def lake_at(
    recorder: Recorder, now: int, tmp: Path, held: Any = None, delayed: bool = False
) -> Any:
    records = {**RECORDS, SPX: [ops.Identifier(scheme="symbol", value="SPX", source="tradier")]}
    answer_records(recorder, records)
    lake = synthetic_lake(recorder, Clock(now), tmp, held=held)
    lake.delayed = delayed
    return lake


def chain_want(
    *subjects: str,
    data_type: str = chains.SERIES,
    key: str = "options",
    standing: bool = False,
    business_date: str = "",
    want_id: str = "WNT-1",
) -> ops.ObservationsWantedEvent:
    return want(
        *subjects,
        dataset=f"{INSTANCE}:{key}",
        data_type=data_type,
        standing=standing,
        business_date=business_date,
        want_id=want_id,
    )


def hear(recorder: Recorder, lake: Any, event: ops.ObservationsWantedEvent) -> None:
    recorder.answer("ObservationsWanted", lambda _: event)
    asyncio.run(recorder.receive(observations_wanted=lake.on_want))


def rows(recorder: Recorder, name: str, field: str) -> list[Any]:
    return [row for sent in recorder.on(name) for row in getattr(sent, field)]


# ── Tradier's chain, converted ──────────────────────────────────────────────


def fetched(*options: dict[str, Any]) -> Fetched:
    return Fetched({"options": {"option": list(options)}}, "chains/X", 0)


def item(**said: Any) -> dict[str, Any]:
    held = {
        "symbol": "SPY261016C00575000",
        "option_type": "call",
        "strike": Decimal("575"),
        "expiration_date": "2026-10-16",
        "root_symbol": "SPY",
        "contract_size": 100,
        "bid": Decimal("4.10"),
        "ask": Decimal("4.15"),
        "bidsize": 12,
        "asksize": 9,
        "bid_date": 1791575998000,
        "ask_date": 1791575999000,
        "volume": 2210,
        "open_interest": 1534,
    }
    return {**held, **said}


def test_a_series_is_keyed_by_its_osi_symbol_its_sizes_in_contracts() -> None:
    (option,) = convert.chain(fetched(item()), "SPY")
    assert option.osi == "SPY   261016C00575000" and len(option.osi) == 21
    assert (option.right, option.strike, option.expiration) == (
        "C",
        Decimal(575),
        dt.date(2026, 10, 16),
    )
    # An option's sizes are contracts, never hundreds of shares.
    assert (option.bid_size, option.ask_size) == (Decimal(12), Decimal(9))
    assert option.at_ns == 1791575999000 * 1_000_000 and option.standard


def test_an_adjusted_series_and_a_share_class_root() -> None:
    adjusted, brk = convert.chain(
        fetched(
            item(symbol="SPY1261016C00575000", root_symbol="SPY1"),
            item(
                symbol="BRKB261016P00455000",
                option_type="put",
                strike=Decimal("455"),
                root_symbol="BRKB",
            ),
        ),  # fmt: skip
        "SPY",
    )
    assert adjusted.osi == "SPY1  261016C00575000" and not adjusted.standard
    (brk,) = convert.chain(fetched(item(symbol="BRKB261016P00455000", root_symbol="BRKB")), "BRK.B")
    assert brk.osi == "BRKB  261016P00455000" and brk.standard


def test_what_tradier_leaves_empty_is_no_value() -> None:
    (option,) = convert.chain(
        fetched(item(bid=Decimal("0"), bidsize=0, open_interest=None, volume=None)), "SPY"
    )
    assert option.bid is None and option.bid_size is None and option.ask == Decimal("4.15")
    assert option.open_interest is None and option.volume is None


def test_a_symbol_that_does_not_read_is_counted_not_recorded() -> None:
    (option,) = convert.chain(fetched(item(symbol="NOT AN OPTION")), "SPY")
    assert option.osi == "" and option.unconverted[0].scheme == "tradier:chains.symbol"


# ── A want of the chain ─────────────────────────────────────────────────────


def test_a_want_records_the_whole_chain_under_the_underlying(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path)
    hear(recorder, lake, chain_want(SPY))
    series = rows(recorder, "RecordSeries", "series")
    # Both expirations Tradier lists, every series of each.
    assert len(series) == 6
    first = series[0]
    assert first.template_id == "TPL-listed-option" and first.template_version == "1"
    assert [s.entity_id for s in first.meta.subjects] == [SPY]
    assert [(k.scheme, k.value) for k in first.meta.series_key] == [
        ("occ_osi", "SPY   261016C00575000")
    ]
    fields = {f.path: f.value for f in first.fields}
    assert fields["exercise_style"] == "EXERCISE_STYLE_AMERICAN"
    assert fields["deliverable[0].instrument_id"] == SPY
    assert fields["deliverable[0].quantity"] == "100"
    assert {s.meta.source.dataset for s in series} == {f"{INSTANCE}:options"}
    quotes = rows(recorder, "RecordQuotes", "quotes")
    assert all(q.meta.series_key for q in quotes) and len(quotes) == 6
    one_sided = next(q for q in quotes if q.meta.series_key[0].value.endswith("C00580000"))
    assert not one_sided.HasField("bid") and one_sided.HasField("ask")
    # Never resolved, never minted, never asked for (ruling 561).
    for asked in ("ResolveIdentifier", "RequestSeriesRecords", "ReportMissingInstrument"):
        assert recorder.on(asked) == []
    assert all(sent.want_id == "WNT-1" for sent in recorder.on("RecordSeries"))


def test_open_interest_is_the_previous_market_days(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path)
    hear(recorder, lake, chain_want(SPY, data_type=chains.STATISTIC))
    stats = rows(recorder, "RecordStatistics", "statistics")
    # Read on a Saturday: Friday's open interest; no session today, no volume.
    assert {s.meta.business_date for s in stats} == {"2026-10-09"}
    assert {s.kind for s in stats} == {ops.STATISTIC_KIND_OPEN_INTEREST}
    # The 590 put states no open interest: no row, never a zero.
    assert not [s for s in stats if s.meta.series_key[0].value.endswith("P00590000")]


def test_during_a_session_volume_is_todays(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, THURSDAY, tmp_path)
    hear(recorder, lake, chain_want(SPY, data_type=chains.STATISTIC))
    stats = rows(recorder, "RecordStatistics", "statistics")
    by_kind = {(s.kind, s.meta.business_date) for s in stats}
    assert by_kind == {
        (ops.STATISTIC_KIND_OPEN_INTEREST, "2026-10-07"),
        (ops.STATISTIC_KIND_VOLUME, "2026-10-08"),
    }


def test_a_holiday_is_skipped_by_tradiers_calendar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = synthetic._calendar

    def friday_closed(year: int, month: int) -> dict[str, Any]:
        said = held(year, month)
        for day in said["calendar"]["days"]["day"]:
            if day["date"] == "2026-10-09":
                day["status"] = "closed"
        return said

    monkeypatch.setattr(synthetic, "_calendar", friday_closed)
    recorder = Recorder(INSTANCE)
    hear(
        recorder, lake_at(recorder, SATURDAY, tmp_path), chain_want(SPY, data_type=chains.STATISTIC)
    )
    stats = rows(recorder, "RecordStatistics", "statistics")
    assert {s.meta.business_date for s in stats} == {"2026-10-08"}


def test_a_past_date_is_beyond_the_chains_history(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path)
    hear(recorder, lake, chain_want(SPY, data_type=chains.STATISTIC, business_date="2026-09-01"))
    (declined,) = recorder.on("DeclineWant")
    assert (
        declined.reason == ops.UNANSWERED_REASON_BEYOND_HISTORY
        and recorder.on("RecordStatistics") == []
    )


def test_the_other_timeliness_is_not_covered(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path, delayed=True)
    hear(recorder, lake, chain_want(SPY))
    (declined,) = recorder.on("DeclineWant")
    assert (
        declined.reason == ops.UNANSWERED_REASON_NOT_COVERED and recorder.on("RecordSeries") == []
    )
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path / "2", delayed=True)
    hear(recorder, lake, chain_want(SPY, key="options_delayed"))
    series = rows(recorder, "RecordSeries", "series")
    assert {s.meta.source.dataset for s in series} == {f"{INSTANCE}:options_delayed"}


def test_an_index_and_an_unknown_listing_are_not_covered(tmp_path: Path) -> None:
    held = copy.deepcopy(exchange())
    held["quotes"]["SPX"] = {**held["quotes"]["SPY"], "symbol": "SPX", "type": "index"}
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path, held=held)
    hear(recorder, lake, chain_want(SPX, "LCL-ISIN"))
    declined = {s.entity_id: d.reason for d in recorder.on("DeclineWant") for s in d.subjects}
    assert declined == {
        SPX: ops.UNANSWERED_REASON_NOT_COVERED,
        "LCL-ISIN": ops.UNANSWERED_REASON_NOT_COVERED,
    }
    assert recorder.on("RecordSeries") == []


# ── Kept current ────────────────────────────────────────────────────────────


def test_a_standing_chain_is_kept_current_and_only_changes_sent(tmp_path: Path) -> None:
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path)
    clock = lake.clock_ns
    hear(recorder, lake, chain_want(SPY, standing=True))
    assert len(rows(recorder, "RecordSeries", "series")) == 6
    # Within the minute: nothing due.
    clock.now += 30 * 10**9
    assert asyncio.run(lake.chains.refresh()) == 0
    # A minute on: each expiration read again; nothing changed, nothing sent.
    clock.now += 31 * 10**9
    asyncio.run(lake.tick())
    assert lake.chains.read_count == 4
    assert len(rows(recorder, "RecordSeries", "series")) == 6
    assert len(rows(recorder, "RecordQuotes", "quotes")) == 6
    # Withdrawn: no longer read.
    recorder.answer(
        "WantWithdrawn",
        lambda _: [ops.WantWithdrawnEvent(want_id="WNT-1", dataset=f"{INSTANCE}:options")],
    )
    asyncio.run(recorder.receive(want_withdrawn=lake.on_withdrawn))
    clock.now += 120 * 10**9
    asyncio.run(lake.tick())
    assert lake.chains.read_count == 4 and lake.chains.underlyings == {}


def test_chains_spend_at_most_their_share_of_the_calls(tmp_path: Path) -> None:
    held = copy.deepcopy(exchange())
    spy = held["options"]["SPY"]
    first = dt.date(2026, 10, 16)
    days = [(first + dt.timedelta(weeks=n)).isoformat() for n in range(40)]
    spy["expirations"] = days
    spy["chains"] = {day: spy["chains"]["2026-10-16"] for day in days}
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path, held=held)
    hear(recorder, lake, chain_want(SPY, standing=True))
    assert lake.chains.read_count == chains.CALLS_PER_MINUTE
    # The rest a minute later, the nearest first.
    lake.clock_ns.now += 61 * 10**9
    asyncio.run(lake.chains.refresh())
    read = lake.chains.underlyings[SPY].read_at
    assert set(read) == {dt.date.fromisoformat(d) for d in days}


def test_a_standing_chains_quotes_are_judged_and_aged_at_the_edge(tmp_path: Path) -> None:
    held = copy.deepcopy(exchange())
    crossed = held["options"]["SPY"]["chains"]["2026-11-20"][0]
    crossed["bid"], crossed["ask"] = "12.60", "12.55"
    recorder = Recorder(INSTANCE)
    lake = lake_at(recorder, SATURDAY, tmp_path, held=held)
    lake.latency = Latency(recorder, clock_ns=lake.clock_ns)
    hear(recorder, lake, chain_want(SPY, standing=True))
    quotes = rows(recorder, "RecordQuotes", "quotes")
    invalid = [q for q in quotes if q.meta.quality == ops.QUALITY_STATE_INVALID]
    assert [q.meta.series_key[0].value for q in invalid] == ["SPY   261120C00575000"]
    # Each series judged apart: equal quotes of two series are no duplicate.
    assert not [q for q in quotes if q.meta.quality == ops.QUALITY_STATE_SUSPICIOUS]
    asyncio.run(lake.latency.report())
    (report,) = recorder.on("ReportLatency")
    assert {s.dataset for s in report.snapshots} == {f"{INSTANCE}:options"}
