"""The `environment` setting, the data role's (contract v20): a required choice
shown first, `live` or `sandbox`, the token gated on it. On `sandbox` the
plugin asks Tradier's developer sandbox with the sandbox access token, says
its data is delayed and opens no stream ("Does not stream"); on `live` it
asks api.tradier.com with the API access token, in real time, and streams.
One token, `tradier_access_token`, serves either (option B, 2026-10-11): the
pages name it by the environment."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import meridian
import pytest
from meridian.suites import Recorder
from meridian.testing import PageClient

from tradier.__main__ import feed_for, source_for
from tradier.lake import LIVE_KINDS, TRADES, Lake, Products, Standing
from tradier.page import CONNECTION, DATASETS, State, pages, use
from tradier.raw import RawStore
from tradier.settings import (
    ENVIRONMENT,
    LIVE,
    OLD_SANDBOX,
    SANDBOX,
    SANDBOX_SAID,
    SETTINGS,
    TOKEN,
    Config,
    config_from,
    environment_of,
)
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
    environment = "sandbox" if sandbox else "live"
    config = config_from({ENVIRONMENT: environment, TOKEN: KEY})
    store = RawStore(tmp / "raw")
    tradier, source = source_for(config, store, transport)
    assert source is not None
    recorder = Recorder("tradier-1")
    answer_records(recorder, RECORDS)
    lake = Lake(recorder, source, Products(tmp / "products.json"), Clock(at("2026-10-10", 9)))
    lake.streaming = not config.on_sandbox
    lake.delayed = config.on_sandbox
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


BY_NAME = {setting.name: setting for setting in SETTINGS}


def delivered(held: dict[str, str]) -> meridian.Settings:
    """The settings as the SDK hands them over: typed, the declared defaults
    filled in, and the required ones held nothing for named, as the sidecar
    names them."""
    defaults = {s.name: s.default for s in SETTINGS if s.default is not None}
    values: dict[str, str | int | bool | list[dict[str, str]]] = {
        **defaults,
        **{name: BY_NAME[name]._parsed(text) for name, text in held.items()},
    }
    missing = tuple(s.name for s in SETTINGS if s.required and s.name not in held)
    return meridian.Settings(values=values, missing_required=missing)


def test_the_environment_is_declared_first_and_one_token_serves_either() -> None:
    first, token, poll, stale, currency, old, sample = SETTINGS
    # Custody's "Read every", "Stale after" and "Account currency" (from
    # 0.7.0), its own.
    assert (poll.name, stale.name) == ("poll_seconds", "stale_after_hours")
    assert currency.name == "account_currency" and currency.label == "Account currency"
    assert poll.roles == stale.roles == currency.roles == ("custody",)
    # Sandbox by default (from 0.7.1): Live is a person's choice, and says so.
    assert first.name == ENVIRONMENT and first.required and first.default == "sandbox"
    assert [c.value for c in first.choices] == ["live", "sandbox"] and first.label == "Environment"
    assert [c.label for c in first.choices] == ["Live", "Sandbox"]
    assert "Sandbox until a person chooses Live." in first.description
    # The agents' demo-only guard (contract v26), said where the choice is made.
    assert first.description.endswith("Agents may place orders only on Sandbox.")
    # 0.2.1's switch, declared again so a saved value reaches the plugin.
    assert old.name == OLD_SANDBOX and old.kind is bool and old.developer
    assert old.default is None and not old.required and old.roles == first.roles
    assert old.description.startswith(
        "Replaced by Environment, read only while Environment is unset"
    )
    assert token.name == TOKEN and token.secret and token.required
    assert token.applies_when is None and token.label == "Access token"
    assert token.description.endswith("it must match Environment.")
    assert sample.name == "sample_data" and sample.developer
    assert config_from({TOKEN: KEY}).on_sandbox is True
    # The value carries over whichever environment is chosen: nothing re-entered.
    for environment in ("live", "sandbox"):
        config = config_from({ENVIRONMENT: environment, TOKEN: KEY})
        assert config.credentials is not None and config.credentials.token == KEY


# ── Live is a person's choice (0.7.1) ───────────────────────────────────────


def test_an_unset_environment_is_the_sandbox() -> None:
    # Nothing saved: the SDK fills in the default, and the sidecar names the
    # environment missing.
    settings = delivered({TOKEN: KEY})
    assert settings.values[ENVIRONMENT] == SANDBOX and ENVIRONMENT in settings.missing_required
    config = config_from(settings.values, settings.missing_required)
    assert config.environment == SANDBOX and config.paper and config.on_sandbox
    # However it arrives: absent, or a value that is not a choice.
    assert config_from({TOKEN: KEY}).environment == SANDBOX
    assert config_from({ENVIRONMENT: "", TOKEN: KEY}).environment == SANDBOX
    assert config_from({ENVIRONMENT: "LIVE", TOKEN: KEY}).environment == SANDBOX
    assert Config().environment == SANDBOX


def test_live_is_read_only_once_a_person_chooses_it() -> None:
    settings = delivered({ENVIRONMENT: LIVE, TOKEN: KEY})
    assert settings.missing_required == ()
    config = config_from(settings.values, settings.missing_required)
    assert config.environment == LIVE and not config.paper and not config.on_sandbox


@pytest.mark.parametrize(("old", "environment"), [("true", SANDBOX), ("false", LIVE)])
def test_while_the_environment_is_unset_the_old_sandbox_decides(old: str, environment: str) -> None:
    # Saved under 0.2.1: the token and the switch, and no environment, as the
    # dev deployment held them when 0.7.0 came up on Live.
    settings = delivered({TOKEN: KEY, OLD_SANDBOX: old})
    assert settings.values[ENVIRONMENT] == SANDBOX  # the SDK's filled-in default
    config = config_from(settings.values, settings.missing_required)
    assert config.environment == environment
    assert config.credentials is not None and config.credentials.token == KEY
    assert environment_of(settings.values, settings.missing_required) == environment


@pytest.mark.parametrize("old", ["true", "false"])
def test_once_the_environment_is_saved_the_old_sandbox_is_not_read(old: str) -> None:
    for said in (LIVE, SANDBOX):
        settings = delivered({ENVIRONMENT: said, TOKEN: KEY, OLD_SANDBOX: old})
        assert environment_of(settings.values, settings.missing_required) == said


def test_with_neither_saved_the_environment_is_the_sandbox() -> None:
    settings = delivered({})
    assert environment_of(settings.values, settings.missing_required) == SANDBOX


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
    assert connection["mode"] == "Sandbox" and connection["detail"] == SANDBOX_SAID
    assert connection["sessions"] is None and connection["stream"] is None
    assert [c["label"] for c in connection["credentials"]] == ["Sandbox access token"]
    quotes = next(f for f in connection["feeds"] if f["feed"] == "quotes")
    assert quotes["what"] == "quotes, every exchange, delayed 15 minutes"
    page = client.get(CONNECTION, "admin").text
    assert SANDBOX_SAID.replace("'", "&#39;") in page and KEY not in page
    assert "Does not stream" in client.get(CONNECTION, "admin", tab="stream").text
    datasets = client.call_tool("read_datasets").data
    feeds = {d["key"]: d["feed"] for d in datasets["served"]}
    assert set(feeds.values()) == {"consolidated, delayed, sandbox.tradier.com"}
    at_vendor = {d["key"]: d["entitled_at_vendor"] for d in datasets["served"]}
    # One dataset per timeliness (ruling 551): the sandbox's live data is
    # `live_delayed`'s; `live`, real time, is not served on it.
    assert at_vendor == {
        "daily": "Yes, delayed 15 minutes",
        "live": "No: the sandbox's is delayed",
        "live_delayed": "Yes, delayed 15 minutes",
        "trades": "No: the sandbox does not stream",
    }
    assert datasets["streamed"] == 0 and not any(w["streamed"] for w in datasets["wants"])
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
    assert connection["mode"] == "Live" and connection["real_time"]
    assert connection["sessions"] in (0, 1) and connection["stream"] is not None
    assert [c["label"] for c in connection["credentials"]] == ["API access token"]
    quotes = next(f for f in connection["feeds"] if f["feed"] == "quotes")
    assert quotes == {
        "feed": "quotes",
        "what": "quotes, every exchange, in real time",
        "entitled": True,
    }
    datasets = client.call_tool("read_datasets").data
    assert {d["feed"] for d in datasets["served"]} == {"consolidated, api.tradier.com"}
    at_vendor = {d["key"]: d["entitled_at_vendor"] for d in datasets["served"]}
    assert at_vendor == {
        "daily": "Yes",
        "live": "Yes",
        "live_delayed": "No: Live is real time",
        "trades": "Yes",
    }
    assert datasets["streamed"] == 1
