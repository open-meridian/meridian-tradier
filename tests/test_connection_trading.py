"""Connectivity on Connection (from 0.12.0 one page for both roles, the SDK's
`connection_pages`, 457) and Raw records (the SDK's `raw_records_page`): each
the same answer as its tool, Enable trading for the connectivity role's
admin alone, and never a token's value or an account's data on an admin
page. SIMULATED ONLY."""

from __future__ import annotations

import asyncio
from pathlib import Path

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.connectivity import RAW, Sent
from meridian.suites import Recorder
from meridian.testing import PageClient

from tradier.page import CONNECTION, State, pages, use
from tradier.settings import LIVE, SANDBOX, Config, Credentials
from trading_cases import CODE, Rig, placement, scope

#: Connection, which draws connectivity's sections, and its "Enable trading".
TRADING = CONNECTION
ENABLE_TRADING = "/enable-trading"
#: Its Trading tab (the SDK's tab row, 0.32.3).
TAB = {"tab": "trading"}

ROLES = ("data", "connectivity")
KEY = Credentials("trading-page-token-0000000000000009")


def state_with(rig: Rig, config: Config) -> State:
    asyncio.run(rig.trader.start())
    return State(
        config=config, trader=rig.trader, store=rig.store, scope=rig.scope, venue=rig.venue
    )


def client_for(state: State, **given: object) -> PageClient:
    use(state)
    return PageClient(pages, Recorder("tradier"), roles=ROLES, **given)  # type: ignore[arg-type]


def test_trading_is_connections_and_its_tool_reads_the_same(tmp_path: Path) -> None:
    rig = Rig(Recorder("tradier"), enabled=False)
    client = client_for(state_with(rig, Config(sample_data=True)))
    assert client.get(TRADING, "admin").status == 200
    assert client.get(TRADING, "write").status == 403
    assert "/admin/connections" not in {page.path for page in pages.declared}
    page = client.get(TRADING, "admin", **TAB).text
    assert CODE in page and "Read-only" in page and "Enable trading" in page
    assert "Sample data" in page
    data = client.call_tool("read_connection").data["trading"]
    assert data["accounts"] == [
        {"venue_account_code": CODE, "trading": False, "order_types": [], "mapped": True}
    ]


def test_paper_is_said_plainly(tmp_path: Path) -> None:
    rig = Rig(Recorder("tradier"))
    config = Config(credentials=KEY, token_set=True, environment=SANDBOX)
    client = client_for(state_with(rig, config))
    page = client.get(TRADING, "admin", **TAB).text
    assert "Paper: Tradier&#39;s developer sandbox, simulated money" in page
    assert KEY.token not in page
    assert KEY.token not in str(client.call_tool("read_connection").json)


def test_enable_trading_enables_the_account_and_publishes_its_catalogue(tmp_path: Path) -> None:
    recorder = Recorder("tradier")
    rig = Rig(recorder, enabled=False)
    rig.enabled = Sent(tmp_path / "enabled.json")
    rig.trader = rig.make()
    client = client_for(state_with(rig, Config(sample_data=True)))
    checked = client.call_tool("check_enable_trading", {"venue_account_code": CODE})
    assert checked.status == 200 and "Would enable trading" in checked.data["said"]
    assert not rig.trader.trading_on(CODE)
    answer = client.post(ENABLE_TRADING, "admin", {"venue_account_code": CODE})
    assert answer.status == 200 and "Trading enabled on SYN-TRD-1001" in answer.text
    assert rig.trader.trading_on(CODE)
    catalogue = recorder.on("ReportVenueCatalogue")[-1].catalogue
    assert catalogue.venue_account_code == CODE and catalogue.order_types
    data = client.call_tool("read_connection").data["trading"]
    assert data["accounts"][0]["trading"] is True and "limit" in data["accounts"][0]["order_types"]


def test_an_account_the_key_does_not_reach_is_refused(tmp_path: Path) -> None:
    rig = Rig(Recorder("tradier"), enabled=False)
    client = client_for(state_with(rig, Config(sample_data=True)))
    refused = client.call_tool("enable_trading", {"venue_account_code": "SOMEONE-ELSE"})
    assert refused.status != 200
    assert not rig.trader.trading_on("SOMEONE-ELSE")


def test_only_the_connectivity_roles_admin_may_enable_trading(tmp_path: Path) -> None:
    rig = Rig(Recorder("tradier"), enabled=False)
    client = client_for(state_with(rig, Config(sample_data=True)))
    answer = client.post(ENABLE_TRADING, "admin", {"venue_account_code": CODE}, roles=("data",))
    assert answer.status == 403
    assert not rig.trader.trading_on(CODE)
    page = client.request("GET", TRADING, "admin", roles={"data": "admin", "connectivity": "admin"})
    assert page.status == 200


def test_raw_records_follows_a_facts_reference_for_a_reader_of_the_account(
    tmp_path: Path,
) -> None:
    recorder = Recorder("tradier")
    rig = Rig(recorder)
    held = placement()
    rig.holds(held)
    asyncio.run(rig.hear(held))
    (sent,) = recorder.on("ReportPlacement")
    assert sent.event == ops.PLACEMENT_EVENT_ACKNOWLEDGED
    state = state_with(rig, Config(sample_data=True))
    state.scope = scope(CODE)
    assert rig.scope.venue_account_map is not None
    reader = client_for(state, read=[rig.scope.venue_account_map.mappings[0].account_id])
    page = reader.get(RAW, "read", ref=sent.raw_record.key).text
    assert "placing an order" in page and "Trading" in page
    stranger = client_for(state)
    assert "placing an order" not in stranger.get(RAW, "read", ref=sent.raw_record.key).text


def test_the_connections_badge_is_both_keys(tmp_path: Path) -> None:
    """Contract v26 (W11.8): Demo where the setting and the session both say
    sandbox, and "Live (environment not confirmed)" where they disagree -- here
    a setting of Live over the simulated brokerage, which reports sandbox. The
    tool reads the same."""
    rig = Rig(Recorder("tradier"))
    client = client_for(state_with(rig, Config(sample_data=True)))
    page = client.get(TRADING, "admin", **TAB).text
    assert "Demo" in page and "Tradier's sandbox host" in page
    data = client.call_tool("read_connection").data["trading"]
    assert data["reached_environment"] == "sandbox" and data["badge"] == "Demo"
    mismatch = Config(credentials=KEY, token_set=True, environment=LIVE, environment_setting=LIVE)
    client = client_for(state_with(Rig(Recorder("tradier")), mismatch))
    assert (
        client.call_tool("read_connection").data["trading"]["badge"]
        == "Live (environment not confirmed)"
    )
    assert "Live (environment not confirmed)" in client.get(TRADING, "admin", **TAB).text


def test_no_badge_before_there_is_a_client(tmp_path: Path) -> None:
    rig = Rig(Recorder("tradier"))
    state = state_with(rig, Config())
    state.venue = None
    data = client_for(state).call_tool("read_connection").data["trading"]
    assert data["reached_environment"] == "" and data["badge"] == ""
