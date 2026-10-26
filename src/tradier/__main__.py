"""The Tradier plugin: Tradier's US equity and ETF market data in an Open
Meridian deployment's lake, as a data plugin (contract v20;
plans/the-lake-prices-the-book, the retail pair).

It connects to the sidecar it is launched beside, declaring its catalogue,
its settings and its storage (declaration.py) and its pages (page.py); on
each delivery of its settings it makes its Tradier client again with the
token for the environment chosen (or, with sample data, the built-in
exchange; on the `sandbox` environment, Tradier's developer sandbox, delayed
and not streamed) and asks whether Tradier answers it; it reads which of its
datasets a deployment admin has licensed (contract v20), and reports the data
role's figures; then it hears what the lake wants of it and records against
each want or declines it per subject (lake.py), and keeps its timetable:
standing wants kept current, days still forming read again, a final close
pushed; and from 0.13.0 the option chains wanted, each expiration read and
kept current (chains.py). While any standing want stands, it streams Tradier's time and sales
and quotes for the listings wanted (stream.py), reconnecting with a new
session when the stream breaks; on the sandbox, which does not stream, it
opens none, and keeps live prices current as it does without a stream. A
restart's gap is not backfilled: Tradier's time and sales history names no
print by its sequence number, so reading it again would record trades twice.

From 0.6.0 it is also the account's connection for orders, where the
deployment launched it with `connectivity`: it hears each placement naming
its instance and places it at Tradier in the environment chosen (live, or
the developer sandbox's paper trading), reads the account's orders on a
poll, Tradier streaming none on its sandbox, and honours the firm's pauses
and stops, and from 0.7.0 reports the fills of orders placed in Tradier's
own web app on no placement (the SDK's
`meridian.roles.connectivity.Trader`). From 0.7.0, where launched with
`custody`, it is the custodian of each account the token reaches too: it
reads them every Read every, reporting their positions, cash and history
(custody.py). Sample data trades with, and reads, a simulated brokerage
(synthetic_broker.py), never Tradier.

It holds nothing it cannot lose: what each subject's symbol is, and every
raw response, are in the storage the deployment grants it (decisions/028);
a restart reads them back and hears the lake again. The token arrives as a
secret setting, never logged, shown or sent anywhere but Tradier.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import tempfile
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian import edge
from meridian.roles import Latency
from meridian.roles.connectivity import Sent, Trader, Watched, trading_files

from .broker import Broker
from .convert import spelled
from .custody import MARKET_ZONE, Syncer
from .declaration import DECLARATION, PORT
from .kinds import Store, tend, windows_from
from .kinds import root as kinds_root
from .lake import Lake, Products
from .page import State, figures, serve
from .raw import RawStore, storage_root
from .settings import SANDBOX_SAID, Config, config_from
from .source import TradierSource
from .stream import Feed, FeedError, Refused, Streamer, TradierFeed
from .synthetic import SyntheticFeed, SyntheticTransport, exchange
from .synthetic_broker import SyntheticBroker
from .vendor import API, SANDBOX, NoKey, Tradier, Transport, VendorError, urllib_transport
from .venue import TradierVenue

log = logging.getLogger("tradier")

#: How often the timetable is looked at.
TICK_SECONDS = 15
#: How often the datasets' licences are read again.
LICENCES_SECONDS = 60
#: How often connectivity reads an account's orders at Tradier, which
#: streams none on its sandbox; and the simulated brokerage, which steps an
#: order on each read.
POLL_SECONDS = 5
SYNTHETIC_POLL_SECONDS = 1
#: How often custody reads the simulated brokerage, in place of Read every.
SYNTHETIC_READ_SECONDS = 5
#: How often the kinds' windows are tended between deliveries of settings.
TEND_SECONDS = 3600


class Account:
    """Connectivity's client for the settings as they stand: Tradier's API of
    the environment chosen, or the simulated brokerage."""

    def __init__(self, store: Store, granted: Path | None) -> None:
        self.store, self.granted = store, granted
        self.broker: Broker | None = None
        self.venue: TradierVenue | None = None
        self._synthetic: SyntheticBroker | None = None
        self._said: tuple[object, ...] = ()

    def use(self, config: Config) -> bool:
        """Make the client again where the settings changed what it is; True
        where they did."""
        said = (config.sample_data, config.environment, config.credentials)
        if said == self._said:
            return False
        self._said = said
        if config.sample_data:
            if self._synthetic is None:
                state = self.granted / "synthetic-venue" / "orders.json" if self.granted else None
                self._synthetic = SyntheticBroker(lambda: datetime.now(UTC), state)
            self.broker = Broker(
                self.store, None, SANDBOX, send=self._synthetic, keyless=True, synthetic=True
            )
        elif config.credentials is not None:
            base = SANDBOX if config.paper else API
            self.broker = Broker(self.store, config.credentials, base)
        else:
            self.broker = None
        self.venue = TradierVenue(self.broker) if self.broker is not None else None
        return True


def source_for(
    config: Config, store: RawStore, transport: Transport = urllib_transport
) -> tuple[Tradier | None, TradierSource | None]:
    """The client and the source the settings give: sample data, the token's
    at Tradier or at its developer sandbox, or none while there is no
    token."""
    if config.sample_data:
        tradier = Tradier(store, None, transport=SyntheticTransport(), keyless=True)
        return tradier, TradierSource(tradier, synthetic=True)
    if config.credentials is None:
        return None, None
    base = SANDBOX if config.on_sandbox else API
    tradier = Tradier(store, config.credentials, transport=transport, base=base)
    return tradier, TradierSource(tradier)


def feed_for(state: State, store: RawStore) -> Feed | None:
    """The stream the settings give: synthetic, Tradier's with the token, or
    none while there is no token, or on the sandbox, which does not stream."""
    if state.config.sample_data:
        return SyntheticFeed(store)
    if state.config.on_sandbox:
        return None
    tradier = state.tradier
    if state.config.credentials is None or tradier is None:
        return None

    async def session() -> str:
        try:
            return await asyncio.to_thread(tradier.session)
        except NoKey as missing:
            raise Refused(str(missing)) from None
        except VendorError as refused:
            if refused.status in (401, 403):
                raise Refused(f"{refused.status} {refused.detail}") from None
            raise FeedError(f"{refused.status} {refused.detail}") from None

    return TradierFeed(session, store)


async def health(plugin: meridian.Plugin, state: State) -> None:
    """Say how the source is, on the heartbeat: a missing token or a refused
    one is the plugin's health, never a ticket."""
    config = state.config
    if config.sample_data:
        await say(plugin, state, True, "sample data: the built-in exchange")
        return
    if state.source is None:
        await say(plugin, state, False, "no Tradier token: enter it in Settings")
        return
    try:
        entitled = await asyncio.to_thread(state.source.entitlements, True)
    except (NoKey, VendorError, OSError) as failed:
        await say(plugin, state, False, f"Tradier did not answer: {failed}")
        return
    if not entitled.answered:
        await say(plugin, state, False, f"Tradier refused the token: {entitled.detail}")
        return
    if config.on_sandbox:
        await say(plugin, state, True, f"answering at {SANDBOX_SAID}")
        return
    timing = "real time" if entitled.real_time else "delayed"
    await say(plugin, state, True, f"answering; quotes {timing}, consolidated")


async def say(plugin: meridian.Plugin, state: State, healthy: bool, detail: str) -> None:
    """The plugin's health, with the data role's figures as they stand."""
    await plugin.report(healthy=healthy, detail=detail[:200], figures=figures(state))


async def read_licences(plugin: Any, state: State) -> None:
    """Which of its own declared datasets a deployment admin has licensed
    (contract v20, W10.9), for the Datasets page: a dataset with none is
    served by its catalogue's default terms until one is set."""
    answered = await plugin.list_datasets()
    state.licensed = frozenset(licence.dataset for licence in answered.licences)


async def licences(plugin: meridian.Plugin, state: State) -> None:
    """The licences, read on start and every minute."""
    while True:
        try:
            await read_licences(plugin, state)
        except meridian.MeridianError as failed:
            log.warning("the datasets' licences were not read this time: %s", failed)
        await asyncio.sleep(LICENCES_SECONDS)


async def watch_settings(
    plugin: meridian.Plugin,
    state: State,
    store: RawStore,
    configured: asyncio.Event,
    account: Account | None = None,
    woken: asyncio.Event | None = None,
) -> None:
    async for delivered in plugin.settings():
        state.config = config_from(delivered.values, delivered.missing_required)
        state.values = dict(delivered.values)
        if account is not None:
            if account.use(state.config) and woken is not None:
                woken.set()
            state.venue = account.venue
            seconds = SYNTHETIC_POLL_SECONDS if state.config.sample_data else POLL_SECONDS
            state.polled = f"Polled every {seconds}s: Tradier streams no orders on its sandbox"
        state.tradier, state.source = source_for(state.config, store)
        if state.lake is not None:
            state.lake.source = state.source
            state.lake.streaming = not state.config.on_sandbox
            # One dataset per timeliness (ruling 551): the sandbox's live
            # data is delayed 15 minutes, recorded into `live_delayed`.
            state.lake.use_delayed(state.config.on_sandbox)
            if state.config.sample_data:
                # The built-in exchange's listings, as a source's own list.
                await state.lake.seed(sorted(spelled(s) or s for s in exchange()["history"]))
        configured.set()
        await health(plugin, state)
        if state.lake is not None:
            state.lake.restream()
        if state.streamer is not None:
            state.streamer.restart()
        if account is not None:
            await tend_now(plugin, account.store, delivered.values)


async def tend_now(plugin: meridian.Plugin, kinds: Store, values: Any) -> None:
    """Each kind's units past its window moved as the settings say."""
    try:
        await tend(plugin, kinds, windows_from(values), datetime.now(UTC).date())
    except (meridian.MeridianError, OSError) as failed:
        log.warning("the raw records were not tended this time: %s", failed)


async def tend_hourly(plugin: meridian.Plugin, state: State, kinds: Store) -> None:
    while True:
        await asyncio.sleep(TEND_SECONDS)
        await tend_now(plugin, kinds, state.values)


async def follow_scope(plugin: meridian.Plugin, state: State, woken: asyncio.Event) -> None:
    """The account scope, its links (W4.11) and its ems's venue account map
    (W11.22), on start and on every change: the account side and its pages
    hold it from here, and custody reads again at once."""
    async for scope in plugin.account_scope():
        state.scope = scope
        woken.set()


async def custody_reads(state: State, syncer: Syncer, woken: asyncio.Event) -> None:
    """Read Tradier now, then every Read every, or sooner when the settings
    or the links change."""
    while True:
        woken.clear()
        try:
            await syncer.run_once()
        except meridian.MeridianError as failed:
            log.warning("this read of the accounts stopped: %s", failed)
        wait = SYNTHETIC_READ_SECONDS if state.config.sample_data else state.config.poll_seconds
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(woken.wait(), timeout=wait)


async def trade(state: State, trader: Trader, hear: bool) -> None:
    """Connectivity's work; a refusal it meets is said, and the rest goes on."""
    await trader.run(
        lambda: SYNTHETIC_POLL_SECONDS if state.config.sample_data else POLL_SECONDS,
        hear=hear,
    )


async def timetable(plugin: meridian.Plugin, state: State, lake: Lake) -> None:
    while True:
        try:
            await lake.tick()
        except meridian.MeridianError as failed:
            log.warning("the timetable stopped this time: %s", failed)
        # The figures go on the next heartbeat.
        plugin.figures = figures(state)
        await asyncio.sleep(TICK_SECONDS)


async def again(work: Callable[[], Coroutine[Any, Any, None]], what: str) -> None:
    """A stream that stops (the deployment still starting, a sidecar
    restarted) is said and opened again, a little later each time; never
    lost with its task."""
    wait = 1.0
    while True:
        try:
            await work()
            return
        except asyncio.CancelledError:
            raise
        except Exception as failed:  # noqa: BLE001 - said, and opened again
            log.warning("%s stopped (%s); again in %.0fs", what, failed, wait)
        await asyncio.sleep(wait)
        wait = min(wait * 2, 30.0)


async def run() -> None:
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop, stopped.set)

    port = PORT
    granted = edge.storage_dir()
    store = RawStore(storage_root(Path(tempfile.mkdtemp(prefix="tradier-raw-"))))
    kinds = Store(kinds_root())
    # The version's whole declaration (declaration.py): its settings, its
    # pages with the levels each serves and their tools, and its documentation.
    # A version registers exactly what it was uploaded with (contract v25).
    async with await meridian.connect(declaration=DECLARATION) as plugin:
        roles = set(plugin.identity.roles)
        log.info(
            "registered as %s, roles %s",
            plugin.identity.instance_id,
            ", ".join(sorted(roles)) or "none",
        )
        lake = Lake(plugin, None, Products(granted / "products.json" if granted else None))
        # The sessions' latency (contract v27), shown on Connection's
        # Sessions; and from 0.13.0 (contract v28, rulings 515 and 518) each
        # live row's age at the edge too, all reported every 10 seconds.
        latency = Latency(plugin)
        state = State(lake=lake, store=kinds, latency=latency)
        lake.latency = latency
        streamer = Streamer(lambda: feed_for(state, store), lake.heard, lake.flush)
        lake.streamer = state.streamer = streamer
        account = Account(kinds, granted)
        woken = asyncio.Event()
        if "custody" in roles:
            state.syncer = Syncer(
                plugin,
                lambda: account.broker,
                paper=lambda: state.config.paper and not state.config.sample_data,
                stale_after=lambda: state.config.stale_after,
                linked=lambda number: state.scope.link_of(number) is not None,
                currencies=lambda: [dict(row) for row in state.config.account_currency],
            )
        if "connectivity" in roles:
            sent, enabled, originated = trading_files(granted)
            state.trader = Trader(
                plugin,
                lambda: account.venue,
                now=lambda: datetime.now(UTC),
                sent=Sent(sent),
                enabled=Sent(enabled),
                # The venue account codes its ems mapped on it (W11.22).
                scope=lambda: state.scope,
                watched=Watched(originated),
                market_zone=MARKET_ZONE,
                # Each call to the brokerage API its round trip, a placement
                # its acknowledgement, a fill its delay (contract v27).
                latency=state.latency,
            )
        configured = asyncio.Event()
        page = serve(plugin, state, port)
        tasks = [
            asyncio.create_task(
                again(
                    lambda: watch_settings(plugin, state, store, configured, account, woken),
                    "the settings",
                )
            )
        ]
        await configured.wait()
        if roles & {"custody", "connectivity"}:
            tasks.append(
                asyncio.create_task(again(lambda: follow_scope(plugin, state, woken), "the scope"))
            )
            tasks.append(asyncio.create_task(tend_hourly(plugin, state, kinds)))
        if state.syncer is not None:
            syncer = state.syncer
            tasks.append(
                asyncio.create_task(
                    again(lambda: custody_reads(state, syncer, woken), "custody's reads")
                )
            )
        if state.trader is not None:
            trader = state.trader
            # With the data role too, its placements are heard on the one
            # stream that hears the lake's wants (below).
            hears = "data" not in roles
            tasks.append(asyncio.create_task(again(lambda: trade(state, trader, hears), "trading")))
        if "data" in roles:
            hearing: dict[str, Any] = {
                "observations_wanted": lake.on_want,
                "want_withdrawn": lake.on_withdrawn,
            }
            if state.trader is not None:
                hearing["placement_updated"] = state.trader.on_placement
                hearing["trading_instruction_changed"] = state.trader.on_instruction
                hearing["execution_recorded"] = state.trader.on_execution
            tasks.append(
                asyncio.create_task(again(lambda: plugin.receive(**hearing), "hearing the lake"))
            )
            tasks.append(
                asyncio.create_task(again(lambda: licences(plugin, state), "the licences"))
            )
            tasks.append(
                asyncio.create_task(again(lambda: timetable(plugin, state, lake), "the timetable"))
            )
            tasks.append(asyncio.create_task(again(streamer.run, "the stream")))
        # Contract v28: the latency recorded, reported (ReportLatency).
        tasks.append(asyncio.create_task(again(latency.run, "the latency reports")))
        log.info("serving its pages on 127.0.0.1:%d", port)
        await stopped.wait()
        log.info("stopping")
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        page.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
