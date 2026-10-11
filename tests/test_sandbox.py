"""The `sandbox` setting: on, the plugin asks Tradier's developer sandbox with
the token entered, says its data is delayed and opens no stream; off, it asks
api.tradier.com in real time and streams, as before."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from meridian.suites import Recorder
from meridian.testing import PageClient

from tradier.__main__ import feed_for, source_for
from tradier.lake import LIVE_KINDS, TRADES, Lake, Products, Standing
from tradier.page import CONNECTION, DATASETS, State, pages, use
from tradier.raw import RawStore
from tradier.settings import DECLARED, SANDBOX, SANDBOX_SAID, TOKEN, config_from
from tradier.stream import Streamer, TradierFeed
from tradier.vendor import Response

from conftest import RECORDS, SPY, Clock, answer_records, at

KEY = "sandbox-test-token-never-kept-0000000003"
QUOTE = '{"quotes":{"quote":{"symbol":"SPY","last":573.86,"bid":573.85,"ask":573.87}}}'


class Scripted:
    """A transport answering each call with one quote, recording what it was
    asked and with which headers."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append((url, dict(headers)))
        return Response(200, {"content-type": "application/json"}, QUOTE.encode())


def state_for(tmp: Path, sandbox: bool, transport: Scripted) -> State:
    """The plugin's state as watch_settings makes it from these settings."""
    config = config_from({TOKEN: KEY, SANDBOX: sandbox})
    store = RawStore(tmp / "raw")
    tradier, source = source_for(config, store, transport)
    assert source is not None
    recorder = Recorder("tradier-1")
    answer_records(recorder, RECORDS)
    lake = Lake(recorder, source, Products(tmp / "products.json"), Clock(at("2026-10-10", 9)))
    lake.streaming = not config.on_sandbox
    wanted: list[list[str]] = []

    async def nothing(*_: object) -> None:
        pass

    streamer = Streamer(lambda: feed_for(state, store), nothing, nothing)
    streamer.want = lambda symbols: wanted.append(list(symbols))  # type: ignore[method-assign]
    lake.streamer = streamer
    lake.products.symbols[SPY] = "SPY"
    lake.standing["WNT-1"] = Standing("WNT-1", (SPY,), LIVE_KINDS, at("2026-10-10", 9))
    lake.standing["WNT-2"] = Standing(
        "WNT-2", (SPY,), (), 0, dataset=TRADES, data_type="meridian.v1.Trade"
    )
    lake.restream()
    state = State(config=config, lake=lake, source=source, tradier=tradier, streamer=streamer)
    source.entitlements()
    state.wanted = wanted  # type: ignore[attr-defined]
    return state


def test_the_setting_is_declared_off_by_default() -> None:
    (declared,) = [s for s in DECLARED if s.name == SANDBOX]
    assert declared.kind is bool and declared.default is False and not declared.developer
    assert declared.label == "Tradier's developer sandbox"
    assert "developer sandbox token" in declared.description
    assert config_from({TOKEN: KEY}).on_sandbox is False


def test_on_it_asks_the_sandbox_marks_data_delayed_and_opens_no_stream(tmp_path: Path) -> None:
    transport = Scripted()
    state = state_for(tmp_path, True, transport)
    ((url, headers),) = transport.asked
    assert url.startswith("https://sandbox.tradier.com/v1/markets/quotes?")
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert state.source is not None and state.source.known is not None
    assert state.source.known.answered and not state.source.known.real_time
    # No stream: nothing to make one from, and nothing asked of the streamer.
    assert feed_for(state, RawStore(tmp_path / "raw")) is None
    assert state.lake is not None and state.lake.streamed == [] and not state.lake.past_limit
    assert state.wanted == [[]]  # type: ignore[attr-defined]
    use(state)
    client = PageClient(pages)
    connection = client.call_tool("read_connection").data
    assert connection["mode"] == "sandbox" and connection["detail"] == SANDBOX_SAID
    assert connection["live_feed"] == "quotes, delayed" and connection["sessions"] == []
    quotes = next(f for f in connection["feeds"] if f["feed"] == "quotes")
    assert quotes["what"] == "Quotes, every exchange, delayed 15 minutes"
    page = client.get(CONNECTION, "admin").text
    assert SANDBOX_SAID.replace("'", "&#39;") in page and KEY not in page
    datasets = client.call_tool("read_datasets").data
    feeds = {d["key"]: d["feed"] for d in datasets["datasets"]}
    assert set(feeds.values()) == {"consolidated, delayed, sandbox.tradier.com"}
    entitled = {d["key"]: d["entitled"] for d in datasets["datasets"]}
    assert entitled == {"daily": True, "live": True, "trades": False}
    assert datasets["streamed"] == 0 and not any(w["streamed"] for w in datasets["standing"])
    assert "sandbox.tradier.com" in client.get(DATASETS, "admin").text


def test_off_it_asks_tradier_in_real_time_and_streams(tmp_path: Path) -> None:
    transport = Scripted()
    state = state_for(tmp_path, False, transport)
    ((url, _),) = transport.asked
    assert url.startswith("https://api.tradier.com/v1/markets/quotes?")
    assert state.source is not None and state.source.known is not None
    assert state.source.known.real_time
    assert isinstance(feed_for(state, RawStore(tmp_path / "raw")), TradierFeed)
    assert state.lake is not None and state.lake.streamed == ["SPY"]
    assert state.wanted == [["SPY"]]  # type: ignore[attr-defined]
    use(state)
    client = PageClient(pages)
    connection = client.call_tool("read_connection").data
    assert connection["mode"] == "live" and connection["live_feed"] == "quotes"
    assert len(connection["sessions"]) == 1
    quotes = next(f for f in connection["feeds"] if f["feed"] == "quotes")
    assert quotes == {
        "feed": "quotes",
        "what": "Quotes, every exchange, in real time",
        "entitled": True,
    }
    datasets = client.call_tool("read_datasets").data
    assert {d["feed"] for d in datasets["datasets"]} == {"consolidated, api.tradier.com"}
    assert all(d["entitled"] for d in datasets["datasets"]) and datasets["streamed"] == 1
