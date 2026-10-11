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
pushed. While any standing want stands, it streams Tradier's time and sales
and quotes for the listings wanted (stream.py), reconnecting with a new
session when the stream breaks; on the sandbox, which does not stream, it
opens none, and keeps live prices current as it does without a stream. A
restart's gap is not backfilled: Tradier's time and sales history names no
print by its sequence number, so reading it again would record trades twice.

It holds nothing it cannot lose: what each subject's symbol is, and every
raw response, are in the storage the deployment grants it (decisions/028);
a restart reads them back and hears the lake again. The token arrives as a
secret setting, never logged, shown or sent anywhere but Tradier.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import tempfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import meridian
from meridian import edge

from .convert import spelled
from .declaration import DECLARATION
from .lake import Lake, Products
from .page import TITLE, State, figures, pages, serve
from .raw import RawStore, storage_root
from .settings import DECLARED, SANDBOX_SAID, Config, config_from
from .source import TradierSource
from .stream import Feed, FeedError, Refused, Streamer, TradierFeed
from .synthetic import SyntheticFeed, SyntheticTransport, exchange
from .vendor import API, SANDBOX, NoKey, Tradier, Transport, VendorError, urllib_transport

log = logging.getLogger("tradier")

#: How often the timetable is looked at.
TICK_SECONDS = 15
#: How often the datasets' licences are read again.
LICENCES_SECONDS = 60


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
    plugin: meridian.Plugin, state: State, store: RawStore, configured: asyncio.Event
) -> None:
    async for delivered in plugin.settings():
        state.config = config_from(delivered.values)
        state.tradier, state.source = source_for(state.config, store)
        if state.lake is not None:
            state.lake.source = state.source
            state.lake.streaming = not state.config.on_sandbox
            if state.config.sample_data:
                # The built-in exchange's listings, as a source's own list.
                await state.lake.seed(sorted(spelled(s) or s for s in exchange()["history"]))
        configured.set()
        await health(plugin, state)
        if state.lake is not None:
            state.lake.restream()
        if state.streamer is not None:
            state.streamer.restart()


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

    port = int(os.environ.get("TRADIER_PAGE_PORT", "8000"))
    granted = edge.storage_dir()
    store = RawStore(storage_root(Path(tempfile.mkdtemp(prefix="tradier-raw-"))))
    async with await meridian.connect(
        interface=meridian.Interface(port=port, title=TITLE, pages=pages),
        settings=DECLARED,
        declaration=DECLARATION,
    ) as plugin:
        log.info(
            "registered as %s, roles %s",
            plugin.identity.instance_id,
            ", ".join(plugin.identity.roles) or "none",
        )
        lake = Lake(plugin, None, Products(granted / "products.json" if granted else None))
        state = State(lake=lake)
        streamer = Streamer(lambda: feed_for(state, store), lake.heard, lake.flush)
        lake.streamer = state.streamer = streamer
        configured = asyncio.Event()
        page = serve(plugin, state, port)
        tasks = [
            asyncio.create_task(
                again(lambda: watch_settings(plugin, state, store, configured), "the settings")
            )
        ]
        await configured.wait()
        tasks.append(
            asyncio.create_task(
                again(
                    lambda: plugin.receive(
                        observations_wanted=lake.on_want, want_withdrawn=lake.on_withdrawn
                    ),
                    "hearing the lake",
                )
            )
        )
        tasks.append(asyncio.create_task(again(lambda: licences(plugin, state), "the licences")))
        tasks.append(
            asyncio.create_task(again(lambda: timetable(plugin, state, lake), "the timetable"))
        )
        tasks.append(asyncio.create_task(again(streamer.run, "the stream")))
        log.info("serving its pages on 127.0.0.1:%d, hearing the lake's wants", port)
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
