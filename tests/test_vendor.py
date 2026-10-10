"""Tradier's client (vendor.py) and the synthetic exchange: the token sent and
never kept, the rate limit honoured, a 429 waited out, a refused token said,
numbers read as Decimals from their own text, Tradier's list of one and its
none read as lists, and the synthetic exchange answering as Tradier does."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest

from tradier import convert
from tradier.raw import RawStore
from tradier.settings import Credentials, config_from
from tradier.synthetic import SyntheticTransport, dumps
from tradier.vendor import SANDBOX, NoKey, RateLimiter, Response, Tradier, VendorError

from conftest import at, no_wait

TOKEN = Credentials("test-token-never-kept-000000000000000001")


class Scripted:
    """A transport answering each call from a script, recording what it was
    asked and with which headers."""

    def __init__(self, *answers: tuple[int, str, Mapping[str, str]]) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append((url, dict(headers)))
        status, body, extra = self.answers.pop(0)
        return Response(status, {"content-type": "application/json", **extra}, body.encode())


def client(tmp: Path, transport: object, **kwargs: object) -> Tradier:
    return Tradier(
        RawStore(tmp),
        TOKEN,
        transport=transport,  # type: ignore[arg-type]
        limiter=no_wait(),
        clock_ns=lambda: at("2026-10-10", 9),
        sleep=lambda _: None,
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_token_is_sent_and_never_kept_in_a_raw_record(tmp_path: Path) -> None:
    echoed = json.dumps({"fault": {"faultstring": f"Invalid Access Token {TOKEN.token}"}})
    transport = Scripted((200, '{"quotes":{"quote":null}}', {}), (401, echoed, {}))
    tradier = client(tmp_path, transport)
    tradier.quotes(["SPY"])
    with pytest.raises(VendorError) as refused:
        tradier.quotes(["SPY"])
    assert transport.asked[0][1]["Authorization"] == f"Bearer {TOKEN.token}"
    kept = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    assert TOKEN.token not in kept and "[redacted]" in kept
    assert TOKEN.token not in str(refused.value)
    assert TOKEN.token not in repr(TOKEN) and TOKEN.token not in repr(config_from({}))


def test_without_a_token_nothing_is_asked(tmp_path: Path) -> None:
    transport = Scripted()
    tradier = Tradier(RawStore(tmp_path), None, transport=transport)
    with pytest.raises(NoKey):
        tradier.quotes(["SPY"])
    assert transport.asked == []


def test_a_429_is_waited_out_and_counted(tmp_path: Path) -> None:
    waited: list[float] = []
    transport = Scripted(
        (429, "Rate limit exceeded", {"retry-after": "4"}),
        (200, '{"quotes":{"quote":null}}', {}),
    )
    tradier = client(tmp_path, transport)
    tradier.sleep = waited.append
    tradier.quotes(["SPY"])
    assert waited == [4.0]
    assert tradier.usage.rate_limited == 1 and tradier.usage.calls == 2


def test_the_limiter_spends_at_most_half_tradiers_allowance() -> None:
    slept: list[float] = []
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], sleep=slept.append)
    for _ in range(3):
        limiter.acquire()
    assert slept and all(abs(s - 1.0) < 1e-9 for s in slept)  # 60 a minute


def test_a_refused_token_is_said_and_the_sandbox_is_not_real_time(tmp_path: Path) -> None:
    refused = client(tmp_path, Scripted((401, "Invalid Access Token", {}))).entitlements()
    assert not refused.answered and "Invalid Access Token" in refused.detail
    sandbox = client(
        tmp_path / "s", Scripted((200, '{"quotes":{"quote":null}}', {})), base=SANDBOX
    ).entitlements()
    assert sandbox.answered and not sandbox.real_time


def test_numbers_are_decimals_and_a_list_of_one_is_a_list(tmp_path: Path) -> None:
    body = (
        '{"history":{"day":{"date":"2026-10-08","open":1,"high":2,"low":0.5,'
        '"close":1.123456789012345678,"volume":7}}}'
    )
    fetched = client(tmp_path, Scripted((200, body, {}))).history(
        "BRK/B", "2026-10-08", "2026-10-08"
    )
    (bar,) = convert.history(fetched, "BRK.B")
    assert bar.close == Decimal("1.123456789012345678") and bar.symbol == "BRK.B"
    none = client(tmp_path / "n", Scripted((200, '{"history":null}', {}))).history("X", "a", "b")
    assert list(convert.history(none, "X")) == []


def test_the_share_class_is_asked_in_tradiers_spelling_and_named_in_the_one() -> None:
    assert convert.tradier_symbol("BRK.B") == "BRK/B"
    assert convert.spelled("BRK/B") == "BRK.B" and convert.spelled("brk-b") == "BRK.B"
    assert convert.spelled("not a symbol") is None


def test_the_synthetic_exchange_answers_as_tradier_does() -> None:
    transport = SyntheticTransport()
    one = json.loads(
        transport(
            "https://api.tradier.com/v1/markets/history?symbol=BRK%2FB&interval=daily"
            "&start=2026-10-08&end=2026-10-08",
            {},
        ).body,
        parse_float=Decimal,
    )
    assert one["history"]["day"]["date"] == "2026-10-08"  # a list of one: the object
    assert isinstance(one["history"]["day"]["close"], Decimal)
    quotes = json.loads(
        transport("https://api.tradier.com/v1/markets/quotes?symbols=SPY,NOPE", {}).body
    )
    assert quotes["quotes"]["quote"]["symbol"] == "SPY"
    assert quotes["quotes"]["unmatched_symbols"] == {"symbol": "NOPE"}
    assert dumps({"close": "83.1", "exch": "Q"}) == '{"close":83.1,"exch":"Q"}'


def test_the_live_check_asks_for_the_token_on_standard_input_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from tradier import live

    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert live.main(["/nonexistent"]) == 2
    assert "standard input" in capsys.readouterr().out
    assert live._text({"close": Decimal("1.50"), "volume": 3, "exch": "Q"}) == {
        "close": "1.50",
        "volume": "3",
        "exch": "Q",
    }
