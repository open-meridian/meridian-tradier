"""Tradier's market data stream, over WebSocket, with reconnect (contract
v19; plans/the-lake-prices-the-book, row 19).

What is streamed is what the lake keeps current: the listings under a
standing want (lake.py says which), and nothing while there is none;
nothing of it is kept here. A standing want is heard once, when the lake
asks: contract v19 gives a want no catch-up read and the lake does not ask
again while it stands, so a process started anew streams nothing until a
want is asked anew (raised with the lake's plan).

**Tradier's protocol:** a session is made by REST (`POST
/markets/events/session`, with the token), and its ID, good for five
minutes until a stream connects with it, opens the WebSocket at
`wss://ws.tradier.com/v1/markets/events`: the client sends the symbols, the
session's ID and the events it wants (`timesale` and `quote`, each print
and the consolidated best bid and offer; `validOnly` false, so a cancel and
a correction arrive too), and sends them again, whole, to change them.
Tradier answers with events, one a line. An error naming the session or the
token closes the session; a new one is made for the next.

**Reconnect.** A connection that breaks, closes or goes silent is opened
again with a new session, a second later, then doubling to a minute; the
subscriptions are sent again from what is wanted. The gap between two
sessions is not caught up: Tradier's time and sales history names no print
by its sequence number, so reading it again would record a trade twice. Each
reconnect is counted on the Connection page.

**Every message is a raw record first**, a line of the session's record
(raw.StreamLog), before anything converts it; neither the token nor the
session's ID is ever in one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from . import convert, ws
from .convert import SourceQuote, SourceTrade, tradier_symbol
from .raw import RawStore, StreamLog
from .vendor import NS, STREAM

log = logging.getLogger("tradier.stream")

#: How long a session may say nothing before it is taken for broken.
SILENT_SECONDS = 120.0
#: How often what is heard is flushed to the lake, at the most.
FLUSH_SECONDS = 0.5
#: The waits between sessions: a second, doubling to a minute.
FIRST_WAIT, MOST_WAIT = 1.0, 60.0
#: After the token is refused, how long before it is tried again.
REFUSED_WAIT = 300.0
#: The events streamed: each print, and the consolidated best bid and offer.
EVENTS = ("timesale", "quote")

Stated = SourceTrade | SourceQuote


class Refused(Exception):
    """Tradier refused the token: tried again only after a while."""


class FeedError(Exception):
    """Tradier said something went wrong in the session."""


class Feed(Protocol):
    """One session with a stream: opened, subscribed, read, closed."""

    name: str

    async def open(self) -> None: ...

    async def subscribe(self, symbols: Sequence[str]) -> None: ...

    async def receive(self) -> list[Stated]: ...

    async def close(self) -> None: ...


class TradierFeed:
    """Feed on Tradier's stream, every message kept."""

    name = "tradier"

    def __init__(
        self,
        session: Callable[[], Awaitable[str]],
        store: RawStore,
        connect: Callable[..., Awaitable[Any]] = ws.connect,
        url: str = STREAM,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.make_session, self.store = session, store
        self.connect, self.url, self.clock_ns = connect, url, clock_ns
        self.socket: Any = None
        self.log: StreamLog | None = None
        self.session_id = ""
        self.subscribed: list[str] = []

    async def open(self) -> None:
        self.subscribed = []
        self.session_id = await self.make_session()
        now = self.clock_ns()
        day = time.strftime("%Y%m%d", time.gmtime(now // NS))
        self.log = StreamLog(self.store, f"stream/{day}/{now}")
        self.socket = await self.connect(self.url)

    async def subscribe(self, symbols: Sequence[str]) -> None:
        wanted = sorted(symbols)
        if wanted == self.subscribed or not wanted:
            self.subscribed = wanted
            return
        await self.socket.send(
            json.dumps(
                {
                    "symbols": [tradier_symbol(s) for s in wanted],
                    "sessionid": self.session_id,
                    "filter": list(EVENTS),
                    "linebreak": True,
                    "validOnly": False,
                    "advancedDetails": True,
                }
            )
        )
        self.subscribed = wanted

    async def receive(self) -> list[Stated]:
        out: list[Stated] = []
        received = self.clock_ns()
        for line in (await self.socket.recv()).splitlines():
            if not line.strip():
                continue
            try:
                message = json.loads(line, parse_float=Decimal)
            except ValueError:
                raise FeedError(f"not JSON: {line[:80]!r}") from None
            if isinstance(message, dict) and "error" in message:
                # A session expired or refused: the next is a new one.
                raise FeedError(str(message.get("error"))[:200])
            key = ""
            if self.log is not None:
                key = self.log.keep({"received_at_ns": received, "message": _textual(message)})
            out.extend(convert.streamed(message, key))
        return out

    async def close(self) -> None:
        if self.socket is not None:
            with contextlib.suppress(Exception):
                await self.socket.close()
        if self.log is not None:
            self.log.close()
        self.socket, self.log, self.session_id = None, None, ""


def _textual(value: Any) -> Any:
    """A parsed message with each number as its text, as it arrived."""
    if isinstance(value, dict):
        return {k: _textual(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_textual(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass
class Session:
    """The stream as the Connection page shows it: never a key."""

    state: str = "idle"
    subscribed: int = 0
    opened: int = 0
    reconnects: int = 0
    messages: int = 0
    last_message_at_ns: int = 0
    last_error: str = ""
    since_ns: int = 0
    symbols: list[str] = field(default_factory=list)


class Restart(Exception):
    """The settings changed: the session is closed and opened again."""


class Streamer:
    """Keeps one session open while anything is wanted, subscribed to what
    is; hands what it hears to `heard`, and flushes with `flush`."""

    def __init__(
        self,
        make_feed: Callable[[], Feed | None],
        heard: Callable[[list[Stated]], Awaitable[None]],
        flush: Callable[[], Awaitable[None]],
        clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        silent_seconds: float = SILENT_SECONDS,
    ) -> None:
        self.make_feed, self.heard, self.flush = make_feed, heard, flush
        self.clock_ns, self.sleep, self.silent_seconds = clock_ns, sleep, silent_seconds
        self.wanted: list[str] = []
        self.session = Session()
        self._changed = asyncio.Event()
        self._restart = False

    def want(self, symbols: Sequence[str]) -> None:
        """Stream these listings, and only these, from now on."""
        if list(symbols) != self.wanted:
            self.wanted = list(symbols)
            self._changed.set()

    def restart(self) -> None:
        """Open the session again: the token changed."""
        self._restart = True
        self._changed.set()

    async def run(self, sessions: int | None = None) -> None:
        """Forever (or for `sessions` sessions, in the tests)."""
        wait = FIRST_WAIT
        held = 0
        while sessions is None or held < sessions:
            if not self.wanted:
                self.session.state = "idle"
                self.session.subscribed, self.session.symbols = 0, []
                self._changed.clear()
                self._restart = False
                await self._changed.wait()
                continue
            feed = self.make_feed()
            if feed is None:
                self.session.state = "no key"
                self._changed.clear()
                self._restart = False
                await self._changed.wait()
                continue
            held += 1
            self._restart = False
            try:
                await self._session(feed)
                # Nothing wanted any more: closed, and idle until there is.
                wait = FIRST_WAIT
                continue
            except Restart:
                wait = FIRST_WAIT
                continue
            except Refused as refused:
                self.session.state, self.session.last_error = "refused", f"refused: {refused}"
                log.warning("Tradier refused the stream: %s", refused)
                await self._pause(REFUSED_WAIT)
                continue
            except (ws.Closed, FeedError, OSError, TimeoutError, ValueError) as broken:
                self.session.last_error = f"{type(broken).__name__}: {broken}"[:300]
                log.warning("the stream stopped: %s", self.session.last_error)
            finally:
                await feed.close()
            self.session.reconnects += 1
            self.session.state = "waiting"
            await self._pause(wait)
            wait = min(wait * 2, MOST_WAIT)

    async def _pause(self, seconds: float) -> None:
        """Wait, or less where the settings change meanwhile."""
        if self._restart:
            return
        changed = asyncio.ensure_future(self._changed.wait())
        slept = asyncio.ensure_future(self.sleep(seconds))
        try:
            await asyncio.wait({changed, slept}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            changed.cancel()
            slept.cancel()

    async def _session(self, feed: Feed) -> None:
        self.session.state = "connecting"
        await feed.open()
        self.session.opened += 1
        self.session.since_ns = self.clock_ns()
        self._changed.clear()
        await self._subscribe(feed)
        self.session.state = "streaming"
        pending: asyncio.Future[list[Stated]] | None = None
        quiet_since = time.monotonic()
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(feed.receive())
                changed: asyncio.Future[Any] = asyncio.ensure_future(self._changed.wait())
                waited: set[asyncio.Future[Any]] = {pending, changed}
                done, _ = await asyncio.wait(
                    waited, timeout=FLUSH_SECONDS, return_when=asyncio.FIRST_COMPLETED
                )
                if changed in done:
                    self._changed.clear()
                    if self._restart:
                        raise Restart()
                    if not self.wanted:
                        return
                    await self._subscribe(feed)
                else:
                    changed.cancel()
                if pending in done:
                    stated = pending.result()
                    pending = None
                    quiet_since = time.monotonic()
                    self._note(stated)
                    await self.heard(stated)
                elif time.monotonic() - quiet_since > self.silent_seconds:
                    raise ws.Closed(f"nothing heard for {self.silent_seconds:.0f} seconds")
                await self.flush()
        finally:
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(BaseException):
                    await pending
            await self.flush()

    async def _subscribe(self, feed: Feed) -> None:
        await feed.subscribe(self.wanted)
        self.session.subscribed = len(self.wanted)
        self.session.symbols = list(self.wanted)

    def _note(self, stated: list[Stated]) -> None:
        now = self.clock_ns()
        for _ in stated:
            self.session.messages += 1
            self.session.last_message_at_ns = now
