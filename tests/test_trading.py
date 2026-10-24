"""Connectivity's own behaviour, beyond what the suite asks: the send, the
fills as stated and as inferred, a send never answered, a restart, a replace
and a cancel the ems asks for, the firm's controls, enabling trading and the
catalogue, and an order placed outside the platform. SIMULATED ONLY: the
simulated brokerage (synthetic_broker.py), nothing reaching Tradier."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.connectivity import Sent, Watched, execution_id, fill_price
from meridian.suites import Recorder

from tradier import synthetic_broker
from tradier.synthetic_broker import SyntheticBroker
from trading_cases import CODE, Rig, asking, clock, placement


def run(work: object) -> None:
    asyncio.run(work)  # type: ignore[arg-type]


def placed(recorder: Recorder, *, quantity: str = "10", **rig: object) -> Rig:
    made = Rig(recorder, **rig)  # type: ignore[arg-type]
    held = placement(quantity=quantity)
    made.holds(held)
    run(made.hear(held))
    return made


def events(recorder: Recorder) -> list[str]:
    return [ops.PlacementEvent.Name(p.event) for p in recorder.on("ReportPlacement")]


def test_a_placement_is_sent_with_its_id_as_the_orders_tag() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder)
    (order,) = [o for o in rig.brokerage.held["orders"] if o.get("tag")]
    assert order["tag"] == "PLC-01JAE00000000000000000001"
    assert order["symbol"] == "AAPL" and order["quantity"] == "10" and order["price"] == "230"
    assert order["type"] == "limit" and order["duration"] == "day" and order["class"] == "equity"
    (sent,) = recorder.on("ReportPlacement")
    assert sent.event == ops.PLACEMENT_EVENT_ACKNOWLEDGED and sent.venue_order_id == "1"
    kept = rig.store.get(sent.raw_record.key)
    assert kept is not None and kept["call"] == "placing an order"
    assert sent.raw_record.key.startswith("trading/")
    assert "tag=PLC-01JAE00000000000000000001" in kept["request"]["body"]


def test_fills_are_tradiers_last_fills_and_derived() -> None:
    """Each read's growth is the last fill Tradier states on the order: its
    quantity and price as stated."""
    recorder = Recorder("tradier")
    rig = placed(recorder)
    run(rig.poll(2))
    fills = recorder.on("ReportExecution")
    assert [as_decimal(f.quantity) for f in fills] == [Decimal(4), Decimal(6)]
    assert [f.venue_execution_id for f in fills] == ["1:4", "1:10"]
    assert all(f.kind == ops.EXECUTION_KIND_VENUE_REPORTED for f in fills)
    assert all(f.computed_settlement_date == "2026-09-30" for f in fills)
    assert all(as_decimal(f.price.amount) == Decimal(230) for f in fills)


def test_a_fill_missed_between_reads_is_inferred_from_the_averages() -> None:
    """Two steps between reads: the growth is more than Tradier's last fill,
    so the fill is inferred from the averages, never taken for the last."""
    recorder = Recorder("tradier")
    rig = placed(recorder)
    rig.broker.orders("SYN-TRD-1001")
    run(rig.poll())
    (fill,) = recorder.on("ReportExecution")
    assert fill.kind == ops.EXECUTION_KIND_INFERRED and as_decimal(fill.quantity) == 10
    assert fill.venue_execution_id == "1:10"


def test_a_send_never_answered_is_asked_about_never_sent_again() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200", symbol=synthetic_broker.LOST)
    assert events(recorder) == ["PLACEMENT_EVENT_OUTCOME_UNKNOWN"]
    run(rig.poll())
    assert events(recorder)[-1] == "PLACEMENT_EVENT_ACKNOWLEDGED"
    placed_here = [o for o in rig.brokerage.held["orders"] if o.get("tag")]
    assert len(placed_here) == 1


def test_a_restart_never_sends_a_placement_twice(tmp_path: Path) -> None:
    sent = Sent(tmp_path / "trading" / "sent.json")
    brokerage = SyntheticBroker(clock, tmp_path / "synthetic-venue" / "orders.json")
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200", sent=sent, broker=brokerage)
    assert json.loads((tmp_path / "trading" / "sent.json").read_text()) == [
        "PLC-01JAE00000000000000000001"
    ]
    # Started again, the book still holding the placement queued.
    again = Recorder("tradier")
    restarted = Rig(
        again,
        sent=Sent(tmp_path / "trading" / "sent.json"),
        broker=SyntheticBroker(clock, tmp_path / "synthetic-venue" / "orders.json"),
    )
    restarted.holds(placement(quantity="200"))
    run(restarted.trader.start())
    run(restarted.poll())
    orders = restarted.brokerage.held["orders"]
    assert len([o for o in orders if o.get("tag")]) == 1
    assert events(again) == ["PLACEMENT_EVENT_ACKNOWLEDGED"]
    assert rig.trader.working


def test_a_replace_changes_the_order_at_tradier_keeping_its_id() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200")
    held = placement(quantity="200", state=ops.PLACEMENT_STATE_WORKING, venue_order_id="1")
    asked = asking(held, ops.PLACEMENT_CHANGE_KIND_REPLACE)
    asked.change_requests[0].placement_change.limit_price.CopyFrom(
        ops.Money(amount=ops.Decimal(low=22950, scale=2), currency_code="USD")
    )
    rig.holds(asked)
    run(rig.hear(asked))
    replaced = recorder.on("ReportPlacement")[-1]
    assert replaced.event == ops.PLACEMENT_EVENT_REPLACED and replaced.venue_order_id == "1"
    assert as_decimal(replaced.limit_price.amount) == Decimal("229.50")
    assert ("PUT", "/accounts/SYN-TRD-1001/orders/1") in rig.brokerage.asked
    assert rig.brokerage.held["orders"][-1]["price"] == "229.5"


def test_a_replace_asking_a_new_quantity_is_refused_with_nothing_sent() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200")
    held = placement(quantity="200", state=ops.PLACEMENT_STATE_WORKING, venue_order_id="1")
    asked = asking(held, ops.PLACEMENT_CHANGE_KIND_REPLACE, quantity=ops.Decimal(low=150, scale=0))
    rig.holds(asked)
    run(rig.hear(asked))
    refused = recorder.on("ReportPlacement")[-1]
    assert refused.event == ops.PLACEMENT_EVENT_REJECTED
    assert refused.rejection_reason == ops.REJECTION_REASON_UNSUPPORTED
    assert not [a for a in rig.brokerage.asked if a[0] == "PUT"]


def test_a_replace_the_catalogue_lacks_is_refused_with_nothing_sent() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200")
    held = placement(quantity="200", state=ops.PLACEMENT_STATE_WORKING, venue_order_id="1")
    asked = asking(
        held, ops.PLACEMENT_CHANGE_KIND_REPLACE, time_in_force=ops.TIME_IN_FORCE_GOOD_TILL_DATE
    )
    rig.holds(asked)
    run(rig.hear(asked))
    refused = recorder.on("ReportPlacement")[-1]
    assert refused.event == ops.PLACEMENT_EVENT_REJECTED
    assert refused.rejection_reason == ops.REJECTION_REASON_UNSUPPORTED
    assert not [a for a in rig.brokerage.asked if a[0] == "PUT"]
    # SDK 0.32.0: its raw record names the venue account, as a placement's
    # rejection does.
    kept = rig.store.get(refused.raw_record.key)
    assert kept is not None and kept["venue_account_code"] == CODE


def test_a_cancel_is_sent_and_the_next_read_reports_it() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200")
    held = placement(quantity="200", state=ops.PLACEMENT_STATE_WORKING, venue_order_id="1")
    asked = asking(held, ops.PLACEMENT_CHANGE_KIND_CANCEL)
    rig.holds(asked)
    run(rig.hear(asked))
    assert ("DELETE", "/accounts/SYN-TRD-1001/orders/1") in rig.brokerage.asked
    run(rig.poll())
    assert events(recorder)[-1] == "PLACEMENT_EVENT_CANCELLED"


def test_a_cancel_tradier_refuses_ends_the_request_refused() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="1")
    run(rig.poll())  # filled
    held = placement(quantity="1", state=ops.PLACEMENT_STATE_WORKING, venue_order_id="1")
    rig.trader.working[held.placement_id].ended = ""
    asked = asking(held, ops.PLACEMENT_CHANGE_KIND_CANCEL)
    rig.holds(asked)
    run(rig.hear(asked))
    refused = recorder.on("ReportPlacement")[-1]
    assert refused.event == ops.PLACEMENT_EVENT_REJECTED
    assert refused.rejection_reason == ops.REJECTION_REASON_VENUE_REJECTED
    assert refused.rejection_as_reported.text == "Order is not open"


def test_a_stop_cancels_at_tradier_naming_the_stop() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, quantity="200")
    run(rig.instruct(ops.TRADING_INSTRUCTION_VALUE_STOP))
    (change,) = recorder.on("RequestPlacementChange")
    assert change.cause.entry_id == "ENT-stop-1"
    assert change.change.kind == ops.PLACEMENT_CHANGE_KIND_CANCEL
    assert ("DELETE", "/accounts/SYN-TRD-1001/orders/1") in rig.brokerage.asked


def test_a_pause_holds_a_placement_back_until_lifted() -> None:
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    run(rig.instruct(ops.TRADING_INSTRUCTION_VALUE_PAUSE))
    held = placement()
    rig.holds(held)
    run(rig.hear(held))
    assert recorder.on("ReportPlacement") == []
    run(rig.instruct(ops.TRADING_INSTRUCTION_VALUE_ACTIVE))
    assert events(recorder) == ["PLACEMENT_EVENT_ACKNOWLEDGED"]


def test_enabling_trading_publishes_the_catalogue(tmp_path: Path) -> None:
    recorder = Recorder("tradier")
    rig = Rig(recorder, enabled=False)
    rig.enabled = Sent(tmp_path / "trading" / "enabled.json")
    rig.trader = rig.make()
    run(rig.trader.start())
    (first,) = recorder.on("ReportVenueCatalogue")
    assert first.catalogue.venue_account_code == CODE and not first.catalogue.order_types
    run(rig.trader.enable(CODE, {"enabled_by": "local|ada"}))
    second = recorder.on("ReportVenueCatalogue")[-1]
    offered = {t.order_type: list(t.times_in_force) for t in second.catalogue.order_types}
    assert ops.ORDER_TYPE_LIMIT in offered and ops.TIME_IN_FORCE_GOOD_TILL_DATE not in [
        tif for tifs in offered.values() for tif in tifs
    ]
    assert second.catalogue.execution_acknowledgement == ops.EXECUTION_ACKNOWLEDGEMENT_NONE
    assert json.loads((tmp_path / "trading" / "enabled.json").read_text()) == [CODE]


def test_an_order_filled_before_the_account_was_watched_is_its_history() -> None:
    """The order the brokerage took in its own web app on 2026-09-02, before
    the plugin first watched the account: no order, no fill reported
    (contract v23 reports only the fills after)."""
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    run(rig.trader.start())
    run(rig.poll(2))
    assert recorder.on("ReportExecution") == [] and recorder.on("ReportPlacement") == []
    assert str(synthetic_broker.OUTSIDE_ID) in rig.trader.history


def test_an_order_placed_in_tradiers_app_has_its_fills_reported_on_no_placement(
    tmp_path: Path,
) -> None:
    """Contract v23: the order's fills reported on no placement, as Tradier
    states each (its last fill), each once, a restart reporting none of them
    again (`trading/originated.json`)."""
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    rig.watched = Watched(tmp_path / "trading" / "originated.json")
    rig.trader = rig.make()
    run(rig.trader.start())
    run(rig.poll())
    venue_order = str(rig.brokerage.at_the_brokerage("AAPL", "5"))
    run(rig.poll(3))
    fills = recorder.on("ReportExecution")
    assert [(f.placement_id, f.venue_order_id, f.side) for f in fills] == [
        ("", venue_order, ops.SIDE_BUY),
        ("", venue_order, ops.SIDE_BUY),
    ]
    assert sorted(as_decimal(f.quantity) for f in fills) == [Decimal(2), Decimal(3)]
    assert all(f.kind == ops.EXECUTION_KIND_VENUE_REPORTED for f in fills)
    # SDK 0.32.0: resolved by every identifier Tradier states, its symbol
    # alone, and no currency, which Tradier never states: its fills are priced
    # in the currency of its instrument's record.
    (resolved,) = recorder.on("ResolveIdentifier")
    assert [(i.scheme, i.value) for i in resolved.identifiers] == [("symbol", "AAPL")]
    assert resolved.stated_currency == ""
    rig.watched = Watched(tmp_path / "trading" / "originated.json")
    rig.trader = rig.make()
    run(rig.trader.start())
    run(rig.poll(2))
    assert len(recorder.on("ReportExecution")) == 2, "a restart reports no fill twice"


def test_a_dk_tells_the_venue_nothing_and_a_later_fill_is_unmatched_again() -> None:
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    run(rig.trader.start())
    run(rig.poll())
    venue_order = str(rig.brokerage.at_the_brokerage("AAPL", "5"))
    run(rig.poll())
    (first,) = rig.executions
    answered = ops.Execution(
        execution_id=first.execution_id,
        venue_order_id=venue_order,
        state=ops.EXECUTION_STATE_DONT_KNOW,
        dk_reason=ops.DK_REASON_NO_MATCHING_ORDER,
    )
    asked = len(rig.brokerage.asked)
    recorder.answer("ExecutionRecorded", lambda _: ops.ExecutionRecordedEvent(execution=answered))
    run(recorder.receive(execution_recorded=rig.trader.on_execution))
    assert len(rig.brokerage.asked) == asked, "nothing sent to the venue on a DK"
    run(rig.poll())
    later = recorder.on("ReportExecution")[-1]
    assert later.placement_id == "" and later.venue_order_id == venue_order


def test_a_status_the_mapping_does_not_know_is_unknown_then_known() -> None:
    recorder = Recorder("tradier")
    rig = placed(recorder, symbol=synthetic_broker.ODD)
    run(rig.poll())
    unknown = recorder.on("ReportPlacement")[-1]
    assert unknown.unknown_reason == ops.UNKNOWN_REASON_VENUE_STATUS_NOT_MAPPED
    assert unknown.status_as_reported.code == "held"
    run(rig.poll())
    assert events(recorder)[-1] == "PLACEMENT_EVENT_ACKNOWLEDGED"


def test_a_fills_price_from_two_averages() -> None:
    assert fill_price(Decimal(4), Decimal("10"), Decimal(10), Decimal("11.2"), 8) == (
        Decimal("12"),
        False,
    )
    price, rounded = fill_price(Decimal(1), Decimal(1), Decimal(4), Decimal("1.1"), 8)
    assert rounded and price == Decimal("1.13333333")
    assert execution_id("1", Decimal("4.0")) == "1:4"


def test_tradier_takes_dma_alone_and_an_rfq_is_unsupported_with_nothing_sent() -> None:
    """Contract v27 (W11.20): the catalogue lists DMA alone, and an RFQ
    placement is rejected unsupported before anything reaches Tradier."""
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    run(rig.trader.start())
    catalogue = recorder.on("ReportVenueCatalogue")[-1].catalogue
    assert list(catalogue.placement_types) == [ops.PLACEMENT_TYPE_DMA]
    held = placement(placement_type=ops.PLACEMENT_TYPE_RFQ)
    rig.holds(held)
    run(rig.hear(held))
    refused = recorder.on("ReportPlacement")[-1]
    assert refused.event == ops.PLACEMENT_EVENT_REJECTED
    assert refused.rejection_reason == ops.REJECTION_REASON_UNSUPPORTED
    assert not [a for a in rig.brokerage.asked if a[0] == "POST"]


def test_a_good_till_date_order_is_unsupported_with_nothing_sent() -> None:
    """Tradier's durations take no expiry: a good-till-date placement, its
    expiry on the order (SDK 0.32.0's `Asked.expire_date`), is rejected
    unsupported."""
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    held = placement(tif=ops.TIME_IN_FORCE_GOOD_TILL_DATE)
    rig.holds(held)
    run(rig.hear(held))
    refused = recorder.on("ReportPlacement")[-1]
    assert refused.rejection_reason == ops.REJECTION_REASON_UNSUPPORTED
    assert not [a for a in rig.brokerage.asked if a[0] == "POST"]


def test_the_catalogue_carries_the_environment_the_session_reached() -> None:
    """Contract v26 (G1 question 5): the agents' demo-only guard's second key.
    The simulated brokerage reaches no venue, so it reports `sandbox`."""
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    run(rig.trader.start())
    catalogue = recorder.on("ReportVenueCatalogue")[-1].catalogue
    assert catalogue.environment == "sandbox"


def test_the_environment_is_read_from_the_host_the_brokerage_api_is_called_at(
    tmp_path: Path,
) -> None:
    """`sandbox.tradier.com` is sandbox, `api.tradier.com` live, and any other
    host no report, which the guard counts live. Nothing is sent: the venue
    is only constructed."""
    from tradier.broker import Broker
    from tradier.kinds import Store
    from tradier.vendor import API, SANDBOX
    from tradier.venue import TradierVenue

    def reached(base: str) -> str:
        return TradierVenue(Broker(Store(tmp_path), None, base, keyless=True)).environment

    assert reached(SANDBOX) == "sandbox"
    assert reached(API) == "live"
    assert reached("https://sandbox.example.com/v1") == ""
