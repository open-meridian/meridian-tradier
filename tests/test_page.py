"""The pages, Connection and Datasets, under Manage alone, each the same answer
as its read tool (`read_connection`, `read_datasets`): asked in-process with
the SDK's PageClient as the sidecar would ask them."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from meridian.suites import Recorder
from meridian.testing import PageClient

from tradier.lake import LIVE_KINDS, TRADES, Standing
from tradier.page import CONNECTION, DATASETS, State, pages, use
from tradier.settings import Config, Credentials
from tradier.stream import Streamer
from tradier.vendor import Entitlements

from conftest import RECORDS, SPY, Clock, answer_records, at, synthetic_lake

KEY = Credentials("page-test-token-0000000000000000000002")


def synthetic_state(tmp: Path) -> State:
    recorder = Recorder("tradier-1")
    answer_records(recorder, RECORDS)
    lake = synthetic_lake(recorder, Clock(at("2026-10-10", 9)), tmp)
    asyncio.run(lake.daily([SPY], *(__import__("datetime").date(2026, 10, 8),) * 2))
    lake.standing["WNT-1"] = Standing("WNT-1", (SPY,), LIVE_KINDS, at("2026-10-10", 9))
    lake.standing["WNT-2"] = Standing(
        "WNT-2", (SPY,), (), 0, dataset=TRADES, data_type="meridian.v1.Trade"
    )
    lake.restream()
    assert lake.source is not None

    async def nothing(*_: object) -> None:
        pass

    streamer = Streamer(lambda: None, nothing, nothing)
    streamer.session.state, streamer.session.subscribed = "streaming", 1
    streamer.session.reconnects = 2
    return State(
        config=Config(sample_data=True),
        lake=lake,
        source=lake.source,  # type: ignore[arg-type]
        tradier=lake.source.tradier,  # type: ignore[attr-defined]
        streamer=streamer,
    )


@pytest.fixture
def client(tmp_path: Path) -> PageClient:
    use(synthetic_state(tmp_path))
    return PageClient(pages)


def test_each_page_serves_manage_alone(client: PageClient) -> None:
    for path in (CONNECTION, DATASETS):
        assert client.get(path, "admin").status == 200
        assert client.get(path, "write").status == 403
        assert client.get(path, "read").status == 403


def test_the_connection_page_and_its_tool_read_one_source(client: PageClient) -> None:
    page = client.get(CONNECTION, "admin").text
    # The data role's sections under the SDK's tab row (0.32.3), in its order,
    # Key first, with Tradier's rows at its blocks.
    tabs = ("?tab=key", "?tab=limits-and-use", "?tab=stream", "?tab=trading")
    assert [page.index(t) for t in tabs] == sorted(page.index(t) for t in tabs)
    assert "<h2>Key</h2>" in page and "<h2>Stream</h2>" not in page
    assert "Sample data" in page and "Not entitled" in page
    assert "60 a minute" in client.get(CONNECTION, "admin", tab="limits-and-use").text
    page = client.get(CONNECTION, "admin", tab="stream").text
    answer = client.call_tool("read_connection")
    assert answer.status == 200 and answer.outcome == "unchanged"
    data = answer.data
    # Environment unset: Sandbox, the default (from 0.7.1); sample data asks nothing.
    assert data["mode"] == "Sample data" and data["environment"] == "sandbox"
    assert [c["label"] for c in data["credentials"]] == ["Sandbox access token"]
    assert data["limit"].startswith("60 a minute") and data["sessions"] == 1
    assert data["stream"]["state"] == "streaming" and data["stream"]["subscribed"] == 1
    assert data["stream"]["reconnects"] == 2 and "a gap Tradier&#39;s history" in page


def test_the_datasets_page_and_its_tool_read_one_source(client: PageClient) -> None:
    page = client.get(DATASETS, "admin").text
    assert "tradier-1:daily" in page and "tradier-1:live" in page
    assert page.index("<h2>Served</h2>") < page.index("<h2>Wants</h2>")
    assert page.index("<h2>Subjects</h2>") < page.index("<h2>Kept current</h2>")
    data = client.call_tool("read_datasets").data
    daily = next(d for d in data["served"] if d["key"] == "daily")
    assert daily["recorded"] == 1 and daily["arrives"] == "pull, push"
    assert daily["default_terms"] == "kept; personal use" and daily["licensed"] is False
    live = next(d for d in data["served"] if d["key"] == "live")
    assert live["default_terms"] == "served, not kept; personal use"
    trades = next(d for d in data["served"] if d["key"] == "trades")
    assert trades["arrives"] == "stream" and trades["default_terms"].startswith("kept 2")
    assert [w["asked"] for w in data["wants"]] == ["trades", "last, bid, ask"]
    assert data["wants"][0]["listings"] == ["SPY"] and data["wants"][0]["streamed"]
    assert data["listings"] == 1 and data["streamed"] == 1
    assert data["backfills_a_restart"] is False and "/.meridian/ui/0.12.0/" in page


def test_a_licensed_dataset_is_said_so(tmp_path: Path) -> None:
    state = synthetic_state(tmp_path)
    state.licensed = frozenset({"tradier-1:live"})
    use(state)
    served = PageClient(pages).call_tool("read_datasets").data["served"]
    assert [s["licensed"] for s in served] == [False, True, False, False]


def test_the_figures_are_the_data_roles_in_its_order(tmp_path: Path) -> None:
    from tradier.page import figures

    said = figures(synthetic_state(tmp_path))
    assert [f.label for f in said] == [
        "Connection",
        "Entitled at the vendor",
        "Stream",
        "Last recorded",
        "Rate use",
    ]
    assert said[0].value == "Sample data" and said[2].value == "1 listings"


def test_no_key_value_and_no_price_is_ever_shown(tmp_path: Path) -> None:
    state = synthetic_state(tmp_path)
    state.config = Config(credentials=KEY, token_set=True)
    state.source._entitled = Entitlements(answered=True, real_time=True)  # type: ignore[union-attr]
    use(state)
    # The sidecar's stand-in, for the custody pages' reads (from 0.7.0).
    client = PageClient(pages, Recorder("tradier"))
    for path in (CONNECTION, DATASETS):
        text = client.get(path, "admin").text
        assert KEY.token not in text
        assert "573.86" not in text  # the close it recorded: a reader's to read
    for tool in ("read_connection", "read_datasets"):
        said = str(client.call_tool(tool).json)
        assert KEY.token not in said and "573.86" not in said
    assert client.call_tool("read_connection").data["credentials"][0]["set"] is True
    client.assert_no_account_data("573.86")


def test_with_no_key_the_page_says_where_to_enter_it(tmp_path: Path) -> None:
    use(State(config=Config()))
    client = PageClient(pages)
    text = client.get(CONNECTION, "admin").text
    assert "No key yet" in text and 'data-om-opens="settings"' in text
    assert client.call_tool("read_connection").data["mode"] == "No key"
    assert "No wants yet" in client.get(DATASETS, "admin").text
