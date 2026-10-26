"""The connectivity suite (contract v23): every case Tradier presents, from the
plugin's own trading code and the simulated brokerage.

Each case is mapped to what Tradier's brokerage API answers for it, through the
simulated brokerage (synthetic_broker.py: a symbol for each answer, a
quantity that works or fills), and run through the SDK's Trader
(meridian.roles.connectivity) over its own adapter (venue.py) and client (broker.py),
against the runner's recorder; only the sidecar is stood in for. SIMULATED
ONLY: nothing reaches Tradier.

Thirteen cases are not presented, each with why (`NOT_PRESENTED`), as the
suite lets a case marked `about` or `about_field` be: calendars, locates, a
fill's place of execution, compliance waits, and from contract v23 a bust
(`about: busts`; Tradier states no bust or correction), a charge with no
fill (`about: charges without a fill`), a charge re-reported on an accepted
placement (`about: venue-originated fills`; Tradier's orders carry no fee)
and a value-date roll; from contract v27 a dealer's quote on an RFQ
placement (`about: rfqs`; Tradier takes no request for quote); and from
contract v28 an option's expiry (`about: options`) and a package's fill
(`about: packages`): it places single-leg equity orders alone. The
session's round trip is reported (required again from contract v28, ruling
518): the Trader records each call's, and `Latency.report` sends it. Every
other case passes, among them v23's fills of
orders placed in Tradier's own web app, reported on no placement, and a
later fill on the placement an accept created.
"""

from __future__ import annotations

import asyncio

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import ANSWERED_BY_SDK, Recorder, names, run, suite

from tradier import synthetic_broker
from trading_cases import Producer, Rig, placed_and_filled, placement

NOT_PRESENTED = {
    "reads-a-calendar": (
        "Tradier's orders state no fill's settlement date, so the plugin asks the date read "
        "for each "
        "(ComputeDate); it reads no calendar's days"
    ),
    "records-a-locate": "Tradier offers no locate API",
    "resolves-a-venue-symbol-by-the-facts-date": (
        "Tradier offers no locate API, so the plugin resolves no locate's symbol"
    ),
    "resolves-an-executions-venue": "Tradier's orders state no fill's place of execution",
    "reports-a-venue-not-held": "Tradier's orders state no fill's place of execution",
    "reads-whether-releases-wait-for-compliance": (
        "it places what its ems released; whether releases wait for compliance changes "
        "nothing it sends"
    ),
    "hears-an-accounts-attributes-change": (
        "it places what its ems released; whether releases wait for compliance changes "
        "nothing it sends"
    ),
    "reports-a-bust": (
        "Tradier states no bust or correction: its order statuses (pending, open, "
        "partially_filled, filled, expired, canceled, rejected, pending_cancel) have none"
    ),
    "reports-a-charge": (
        "Tradier's orders carry no fee, and its account history names no order (it is "
        "updated nightly, and its sandbox serves none): Tradier states no charge on a "
        "placement that filled nothing"
    ),
    "re-reports-a-charge-on-the-accepted-placement": (
        "Tradier's orders carry no fee, its own web app's included, and its history names no order"
    ),
    "reports-a-give-up-rejected": (
        "Tradier executes and clears each order in the account that placed it: no trade is "
        "given up to a prime broker, so none is rejected"
    ),
    "reports-a-value-date-roll": (
        "Tradier's trades settle on their settlement dates: it rolls no spot position at a "
        "daily cut"
    ),
    # Contract v27: an RFQ's dealers' quotes (about rfqs).
    "records-a-dealers-quote-on-an-rfq-placement": (
        "Tradier takes no request for quote: its equities are routed to the market, no dealer "
        "quoting the firm, so it takes DMA placements alone"
    ),
    # Contract v28: an option's expiry (about options) and a package's fill
    # (about packages; ruling 602). Named through a table, not as literal
    # keys: meridian 0.1.52's check holds contract v27's suites.
    **{
        case: why
        for case, why in (
            (
                "reports-an-expiry",
                "it places equity orders alone (Tradier's `equity` class): it holds no option "
                "placement to expire",
            ),
            (
                "reports-a-package-fill",
                "it places single-leg equity orders alone: Tradier's `multileg` and `combo` "
                "classes are not sent",
            ),
        )
    },
}

ACCEPTED = "PLC-01JAE0000000000000000ACPT"


async def acknowledged(recorder: Recorder) -> None:
    rig = Rig(recorder)
    held = placement()
    rig.holds(held)
    await rig.hear(held)


async def another_instances(recorder: Recorder) -> None:
    rig = Rig(recorder)
    held = placement(instance="elsewhere")
    rig.holds(held)
    await rig.hear(held)
    await rig.poll()


async def not_offered(recorder: Recorder) -> None:
    """Good till date, which Tradier takes none of."""
    rig = Rig(recorder)
    held = placement(tif=ops.TIME_IN_FORCE_GOOD_TILL_DATE)
    rig.holds(held)
    await rig.hear(held)


async def a_strategy(recorder: Recorder) -> None:
    rig = Rig(recorder)
    held = placement(strategy=ops.StrategyInstruction(kind=ops.STRATEGY_KIND_VWAP))
    rig.holds(held)
    await rig.hear(held)


def by_symbol(symbol: str, quantity: str = "10", polls: int = 0) -> Producer:
    async def produce(recorder: Recorder) -> None:
        rig = Rig(recorder, symbol)
        held = placement(quantity=quantity)
        rig.holds(held)
        await rig.hear(held)
        await rig.poll(polls)

    return produce


async def the_same_fill_twice(recorder: Recorder) -> None:
    """One fill read, then read again by the plugin started again before the
    book held it: the same derived ID both times."""
    rig = Rig(recorder)
    held = placement(quantity="1")
    rig.holds(held)
    await rig.hear(held)
    await rig.poll()
    worked = next(iter(rig.trader.working.values()))
    again = placement(
        quantity="1", state=ops.PLACEMENT_STATE_WORKING, venue_order_id=worked.venue_order_id
    )
    rig.holds(again)
    rig.executions.clear()
    rig.trader = rig.make()
    await rig.trader.start()
    await rig.poll()


async def renamed(recorder: Recorder) -> None:
    """Filled under a symbol renamed while it worked, which names none of the
    deployment's records."""
    rig = Rig(recorder, synthetic_broker.RENAMED)
    recorder.answer(
        "ResolveIdentifier",
        lambda _: ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_NOT_FOUND),
    )
    held = placement(quantity="1")
    rig.holds(held)
    await rig.hear(held)
    await rig.poll()


async def paused(recorder: Recorder) -> None:
    rig = Rig(recorder)
    await rig.instruct(ops.TRADING_INSTRUCTION_VALUE_PAUSE)
    held = placement()
    rig.holds(held)
    await rig.hear(held)


async def stopped(recorder: Recorder) -> None:
    rig = Rig(recorder)
    held = placement(quantity="200")
    rig.holds(held)
    await rig.hear(held)
    await rig.instruct(ops.TRADING_INSTRUCTION_VALUE_STOP)


async def started(recorder: Recorder) -> None:
    rig = Rig(recorder)
    await rig.trader.start()


async def caught_up(recorder: Recorder) -> None:
    rig = Rig(recorder)
    await rig.trader.start()
    await rig.poll()


async def originated(recorder: Recorder) -> None:
    """An order of 5 placed in Tradier's own web app on the mapped account, after
    the plugin watched it: its first fill, 2, reported on no placement."""
    rig = Rig(recorder)
    await rig.poll()
    rig.brokerage.at_the_brokerage("AAPL", "5")
    await rig.poll()


async def accepted_then_filled(recorder: Recorder) -> None:
    """The same order's first fill accepted by the ems: the book's placement
    at filled naming the venue order, and the execution matched; its later
    fill, 3, is reported on that placement."""
    rig = Rig(recorder)
    await rig.poll()
    venue_order = str(rig.brokerage.at_the_brokerage("AAPL", "5"))
    await rig.poll()
    (first,) = rig.executions
    created = placement(
        ACCEPTED, quantity="2", state=ops.PLACEMENT_STATE_FILLED, venue_order_id=venue_order
    )
    matched = ops.Execution(
        execution_id=first.execution_id,
        order_id=created.order_id,
        placement_id=ACCEPTED,
        venue_order_id=venue_order,
        venue_execution_id=first.venue_execution_id,
        state=ops.EXECUTION_STATE_MATCHED,
    )
    await rig.hear(created)
    recorder.answer("ExecutionRecorded", lambda _: ops.ExecutionRecordedEvent(execution=matched))
    await recorder.receive(execution_recorded=rig.trader.on_execution)
    await rig.poll()


async def round_trip(recorder: Recorder) -> None:
    """Contract v28 (ruling 518): the brokerage API's session latency, each
    call's round trip as the Trader records it, reported."""
    rig = Rig(recorder)
    held = placement()
    rig.holds(held)
    await rig.hear(held)
    await rig.poll()
    await rig.latency.report()


PRODUCERS: dict[str, Producer] = {
    "acknowledges-a-placement-naming-it": acknowledged,
    "hears-no-placement-of-another-instance": another_instances,
    "sends-the-venue-account-code-its-ems-set": acknowledged,
    "rejects-what-the-venue-does-not-offer": not_offered,
    "rejects-a-strategy-its-broker-lacks": a_strategy,
    "venue-rejected-with-its-reason-as-reported": by_symbol(synthetic_broker.REJECTED),
    # Tradier answers a send with the order's ID and "ok"; its status is the
    # next read's.
    "unmapped-status-is-outcome-unknown": by_symbol(synthetic_broker.ODD, polls=1),
    "resolves-an-unanswered-send-by-asking": by_symbol(synthetic_broker.LOST, "200", 1),
    "reports-a-fill-with-its-settlement-date": placed_and_filled,
    "derives-the-same-execution-id-twice": the_same_fill_twice,
    "sends-nothing-new-on-a-pause": paused,
    "cancels-at-the-venue-on-a-stop": stopped,
    "publishes-its-catalogue": started,
    "reads-the-instrument-it-places": acknowledged,
    "reads-its-placements-orders-on-start": started,
    "catches-up-placements-after-a-loss": caught_up,
    "reads-the-instructions-in-force-on-start": started,
    "reports-a-symbol-it-cannot-resolve": renamed,
    "reports-a-fill-on-no-placement": originated,
    "reports-a-later-fill-on-the-accepted-placement": accepted_then_filled,
    "reports-a-sessions-round-trip": round_trip,
}


def test_every_case_is_mapped_or_said_not_presented() -> None:
    # Contract v24: the two cases every suite holds, which the SDK answers.
    assert set(names("connectivity")) == set(PRODUCERS) | set(NOT_PRESENTED) | set(ANSWERED_BY_SDK)
    assert not set(PRODUCERS) & set(NOT_PRESENTED)
    held = {case.name: case.about or case.about_field for case in suite("connectivity").cases}
    assert all(held[name] for name in NOT_PRESENTED), "a required case is never skipped"


def test_every_case_of_the_connectivity_suite_passes_but_those_tradier_never_presents() -> None:
    report = run("connectivity", PRODUCERS, not_presented=NOT_PRESENTED, instance_id="tradier")
    assert report.passed, report.failures
    assert report.not_presented == NOT_PRESENTED
    assert set(report.passed_cases) == set(PRODUCERS) | set(ANSWERED_BY_SDK)


def test_a_plugin_sending_on_a_pause_fails_the_suite() -> None:
    """The suite tests the outcome: a trader that ignores a pause fails the
    case that says so."""

    async def ignoring(recorder: Recorder) -> None:
        rig = Rig(recorder)
        await rig.instruct(ops.TRADING_INSTRUCTION_VALUE_PAUSE)
        rig.trader.instructions.clear()
        held = placement()
        rig.holds(held)
        await rig.hear(held)

    report = run(
        "connectivity",
        {**PRODUCERS, "sends-nothing-new-on-a-pause": ignoring},
        not_presented=NOT_PRESENTED,
        instance_id="tradier",
    )
    assert set(report.failures) == {"sends-nothing-new-on-a-pause"}


def test_a_read_only_account_rejects_every_order_unsupported() -> None:
    async def read_only(recorder: Recorder) -> None:
        rig = Rig(recorder, enabled=False)
        held = placement()
        rig.holds(held)
        await rig.hear(held)

    recorder = Recorder("tradier")
    asyncio.run(read_only(recorder))
    (sent,) = recorder.on("ReportPlacement")
    assert sent.event == ops.PLACEMENT_EVENT_REJECTED
    assert sent.rejection_reason == ops.REJECTION_REASON_UNSUPPORTED
    assert recorder.on("ResolveInstrument") == [], "nothing read for what is not sent"
