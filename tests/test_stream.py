"""The stream (contract v19): the WebSocket client against a server on
loopback, Tradier's protocol on a stand-in socket, the streamer's reconnect
with a new session, and the synthetic stream's cycles."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tradier import ws
from tradier.convert import SourceQuote, SourceTrade
from tradier.raw import RawStore
from tradier.stream import FeedError, Streamer, TradierFeed
from tradier.synthetic import SyntheticFeed

SESSION = "c8638963-test-session-not-real"


# ── A WebSocket server on loopback, standard library only ─────────────────


def server_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(payload) < 126:
        head += bytes([len(payload)])
    else:
        head += bytes([126]) + struct.pack("!H", len(payload))
    return head + payload


async def read_client_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    assert second & 0x80, "a client's frame is masked"
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", await reader.readexactly(2))
    mask = await reader.readexactly(4)
    data = await reader.readexactly(length)
    return first & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


async def serving(script: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Any]) -> Any:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        key = next(
            line.split(":", 1)[1].strip()
            for line in head.split("\r\n")
            if line.lower().startswith("sec-websocket-key")
        )
        accept = base64.b64encode(hashlib.sha1((key + ws.GUID).encode()).digest()).decode()
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        with contextlib.suppress(Exception):
            await script(reader, writer)
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


@contextlib.asynccontextmanager
async def bounded(server: asyncio.Server) -> Any:
    """A server for one test, closed within seconds: a connection left open
    fails the test rather than holding it (Python 3.12's `wait_closed` waits
    for every connection)."""
    try:
        yield server
    finally:
        server.close()
        await asyncio.wait_for(server.wait_closed(), 5)


async def test_the_client_hands_on_whole_messages_answers_pings_and_says_a_close() -> None:
    heard: list[tuple[int, bytes]] = []

    async def script(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        heard.append(await read_client_frame(reader))
        writer.write(server_frame(ws.TEXT, b'[{"T":"success",', fin=False))
        writer.write(server_frame(ws.PING, b"are you there"))
        writer.write(server_frame(ws.CONTINUATION, b'"msg":"connected"}]'))
        writer.write(server_frame(ws.TEXT, json.dumps({"n": "x" * 300}).encode()))
        await writer.drain()
        heard.append(await read_client_frame(reader))  # the pong
        writer.write(server_frame(ws.CLOSE, struct.pack("!H", 1000) + b"bye"))
        await writer.drain()
        heard.append(await read_client_frame(reader))  # the close answered

    server = await serving(script)
    port = server.sockets[0].getsockname()[1]
    async with bounded(server):
        socket = await ws.connect(f"ws://127.0.0.1:{port}/v2/iex", timeout=5)
        await socket.send('{"action":"auth"}')
        assert json.loads(await socket.recv()) == [{"T": "success", "msg": "connected"}]
        assert len(json.loads(await socket.recv())["n"]) == 300
        with pytest.raises(ws.Closed, match="1000 bye"):
            await socket.recv()
    assert heard[0] == (ws.TEXT, b'{"action":"auth"}')
    assert heard[1] == (ws.PONG, b"are you there")
    assert heard[2][0] == ws.CLOSE


async def test_a_server_that_breaks_or_refuses_the_upgrade_is_closed_naming_why() -> None:
    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(server_frame(ws.TEXT, b"half")[:3])
        await writer.drain()

    server = await serving(silent)
    port = server.sockets[0].getsockname()[1]
    async with bounded(server):
        socket = await ws.connect(f"ws://127.0.0.1:{port}/")
        with pytest.raises(ws.Closed, match="broke"):
            await socket.recv()

    async def refuse(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        await writer.drain()
        writer.close()

    plain = await asyncio.start_server(refuse, "127.0.0.1", 0)
    port = plain.sockets[0].getsockname()[1]
    async with bounded(plain):
        with pytest.raises(ws.Closed, match="401"):
            await ws.connect(f"ws://127.0.0.1:{port}/")


# ── Tradier's protocol, on a stand-in socket ─────────────────────────────


class Socket:
    """A connection as TradierFeed uses it: what it sent, what it is told."""

    def __init__(self, told: list[str]) -> None:
        self.told = list(told)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def recv(self) -> str:
        if not self.told:
            raise ws.Closed("the server closed the connection: 1000")
        return self.told.pop(0)

    async def close(self) -> None:
        self.closed = True


def feed_on(socket: Socket, tmp: Path, asked: list[str] | None = None) -> TradierFeed:
    sessions: list[int] = []

    async def session() -> str:
        sessions.append(1)
        return f"{SESSION}-{len(sessions)}"

    async def connect(url: str) -> Socket:
        if asked is not None:
            asked.append(url)
        return socket

    return TradierFeed(session, RawStore(tmp / "raw"), connect=connect, clock_ns=lambda: 10**18)


TIMESALE = (
    '{"type":"timesale","symbol":"BRK/B","exch":"N","bid":"455.32","ask":"455.41",'
    '"last":"455.33","size":"25","date":"1791574200123","seq":4434373,"flag":"",'
    '"cancel":false,"correction":false,"session":"regular"}'
)
QUOTE = (
    '{"type":"quote","symbol":"SPY","bid":575.45,"bidsz":3,"bidexch":"P",'
    '"biddate":"1791574200100","ask":575.48,"asksz":2,"askexch":"Q","askdate":"1791574200123"}'
)
TRADE = '{"type":"trade","symbol":"SPY","exch":"Q","price":"575.46","size":"100","date":"1"}'


async def test_the_feed_subscribes_with_its_session_and_keeps_every_event_but_the_session(
    tmp_path: Path,
) -> None:
    socket = Socket([TIMESALE + "\n" + QUOTE + "\n" + TRADE])
    asked: list[str] = []
    feed = feed_on(socket, tmp_path, asked)
    await feed.open()
    await feed.subscribe(["SPY", "BRK.B"])
    await feed.subscribe(["BRK.B", "SPY"])  # the same: nothing sent
    stated = await feed.receive()
    await feed.close()
    assert asked == ["wss://ws.tradier.com/v1/markets/events"]
    (sent,) = socket.sent
    assert sent == {
        "symbols": ["BRK/B", "SPY"],
        "sessionid": f"{SESSION}-1",
        "filter": ["timesale", "quote"],
        "linebreak": True,
        "validOnly": False,
        "advancedDetails": True,
    }
    traded, quoted = stated  # the `trade` event repeats a time and sale: not converted
    assert isinstance(traded, SourceTrade) and isinstance(quoted, SourceQuote)
    assert traded.symbol == "BRK.B" and str(traded.price) == "455.33" and traded.sequence == 4434373
    assert traded.row_key.endswith(":4434373")
    assert quoted.bid_size == 300 and quoted.ask_size == 200  # Tradier's hundreds, in shares
    assert quoted.at_ns == 1791574200123 * 10**6
    kept = "".join(p.read_text() for p in (tmp_path / "raw").rglob("*.jsonl"))
    assert "455.33" in kept and SESSION not in kept
    assert RawStore(tmp_path / "raw").get(traded.raw_key)["message"]["last"] == "455.33"  # type: ignore[index]


async def test_an_error_ends_the_session_and_the_next_is_a_new_one(tmp_path: Path) -> None:
    feed = feed_on(Socket(['{"error":"session not found"}']), tmp_path)
    await feed.open()
    await feed.subscribe(["SPY"])
    with pytest.raises(FeedError, match="session not found"):
        await feed.receive()
    await feed.close()
    await feed.open()
    assert feed.session_id == f"{SESSION}-2"


# ── The streamer: reconnect, resubscribe, catch up ───────────────────────


class Scripted:
    """A Feed whose sessions each state some things, then break."""

    name = "iex"

    def __init__(self, sessions: list[list[list[Any]]]) -> None:
        self.sessions = sessions
        self.subscribed: list[list[str]] = []
        self.opened = 0
        self.script: list[list[Any]] = []

    async def open(self) -> None:
        self.script = list(self.sessions[self.opened])
        self.opened += 1

    async def subscribe(self, symbols: Any) -> None:
        self.subscribed.append(list(symbols))

    async def receive(self) -> list[Any]:
        if not self.script:
            raise ws.Closed("the connection broke: IncompleteReadError")
        return self.script.pop(0)

    async def close(self) -> None:
        pass


def a_trade(symbol: str, at_ns: int, sequence: int) -> SourceTrade:
    return SourceTrade(symbol, at_ns, "Q", sequence, None, None, "", "regular", False, "k")


async def test_a_broken_stream_is_opened_again_with_a_new_session_and_subscribed_again() -> None:
    feed = Scripted(
        [[[a_trade("SPY", 100, 1), a_trade("SPY", 200, 2)]], [[a_trade("SPY", 300, 3)]]]
    )
    heard: list[Any] = []

    async def on_heard(stated: list[Any]) -> None:
        heard.extend(stated)

    async def flush() -> None:
        pass

    async def no_sleep(_: float) -> None:
        pass

    streamer = Streamer(lambda: feed, on_heard, flush, sleep=no_sleep)
    streamer.want(["SPY"])
    await asyncio.wait_for(streamer.run(sessions=2), 5)
    assert feed.opened == 2 and feed.subscribed == [["SPY"], ["SPY"]]
    assert [t.sequence for t in heard] == [1, 2, 3]
    session = streamer.session
    assert session.reconnects == 2 and "broke" in session.last_error


async def test_with_nothing_wanted_nothing_is_opened() -> None:
    opened: list[int] = []

    def make() -> Any:
        opened.append(1)
        return None

    async def nothing(*_: Any) -> None:
        pass

    streamer = Streamer(make, nothing, nothing)
    task = asyncio.create_task(streamer.run())
    await asyncio.sleep(0.05)
    assert not opened and streamer.session.state == "idle"
    streamer.want(["SPY"])
    await asyncio.sleep(0.05)
    assert opened and streamer.session.state == "no key"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_the_synthetic_stream_states_new_trades_each_cycle(tmp_path: Path) -> None:
    async def no_sleep(_: float) -> None:
        pass

    feed = SyntheticFeed(
        RawStore(tmp_path / "raw"), clock_ns=lambda: 1_791_559_800 * 10**9, sleep=no_sleep
    )
    await feed.open()
    await feed.subscribe(["SPY", "BRK.B"])
    first, second = await feed.receive(), await feed.receive()
    await feed.close()

    def keys(stated: list[Any]) -> set[str]:
        return {s.row_key for s in stated if isinstance(s, SourceTrade) and not s.cancelled}

    assert keys(first) and not keys(first) & keys(second)
    assert all(s.symbol in ("SPY", "BRK.B") for s in first)
    assert any(isinstance(s, SourceTrade) and s.cancelled for s in first)
    assert any(isinstance(s, SourceQuote) and s.ask is None for s in first)
