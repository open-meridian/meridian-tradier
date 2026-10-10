"""The live check, run by the account holder on their own machine with their own
token, never in CI and never by an agent: `make live`, or `make live
SANDBOX=1` against Tradier's sandbox with a developer sandbox token.

The token is read from standard input, one line, which `make live` fills from
a prompt that does not echo; it is never an argument, an environment variable
or a file, and is never printed. It asks Tradier whether the token answers,
reads a week of SPY's and BRK/B's daily history and their quotes, converts
them as the plugin does, listens to Tradier's stream for them for up to
twenty seconds (not the sandbox's, which does not stream), and prints what it
found: booleans, counts and converted values, and the flags and sessions its
time and sales carried, never the token or a session's ID. It then checks that
no raw record holds the token.

What Tradier answered is kept under `recordings/` (git-ignored: real
responses are the account holder's, for their personal use), each response
as a raw record, and one `exchange.json` shaped as the synthetic exchange,
which `make e2e-recorded RECORDED=recordings/<when>` replays through the e2e.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import convert
from .convert import SourceQuote, SourceTrade, as_list, tradier_symbol
from .raw import RawStore
from .settings import Credentials
from .stream import TradierFeed
from .vendor import API, SANDBOX, Tradier, VendorError

SYMBOLS = ("SPY", "BRK.B")
#: How long the stream is listened to, at most, and how many events.
STREAM_SECONDS, STREAM_EVENTS = 20.0, 200


async def listen(tradier: Tradier, store: RawStore) -> dict[str, Any]:
    """A short session of Tradier's stream for SYMBOLS: what it stated,
    counted, and the flags and sessions its time and sales carried (which
    the plugin keeps as reported until Tradier says what its flags mean)."""

    async def session() -> str:
        return await asyncio.to_thread(tradier.session)

    feed = TradierFeed(session, store)
    heard: dict[str, Any] = {"connected": False, "trades": 0, "cancels": 0, "quotes": 0}
    flags: set[str] = set()
    sessions: set[str] = set()
    try:
        await feed.open()
        heard["connected"] = True
        await feed.subscribe(list(SYMBOLS))
        until = time.monotonic() + STREAM_SECONDS
        events = 0
        while events < STREAM_EVENTS and time.monotonic() < until:
            try:
                stated = await asyncio.wait_for(feed.receive(), until - time.monotonic())
            except TimeoutError:
                break
            events += len(stated)
            for each in stated:
                if isinstance(each, SourceTrade):
                    heard["cancels" if each.cancelled else "trades"] += 1
                    flags.add(each.flag)
                    sessions.add(each.session)
                elif isinstance(each, SourceQuote):
                    heard["quotes"] += 1
    except Exception as failed:  # noqa: BLE001 - said, for the account holder
        heard["error"] = f"{type(failed).__name__}: {failed}"[:200]
    finally:
        await feed.close()
    heard["flags"], heard["sessions"] = sorted(flags), sorted(sessions)
    return heard


def _text(value: Any) -> Any:
    """A parsed body with each number as its text, as exchange.json holds it."""
    if isinstance(value, dict):
        return {k: _text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_text(v) for v in value]
    if isinstance(value, Decimal | int) and not isinstance(value, bool):
        return str(value)
    return value


def main(argv: list[str]) -> int:
    sandbox = "--sandbox" in argv
    named = [a for a in argv if not a.startswith("--")]
    out = Path(named[0] if named else "recordings") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    lines = sys.stdin.read().splitlines()
    if not lines or not lines[0].strip():
        print("live: give the access token, one line, on standard input")
        return 2
    token = Credentials(lines[0].strip())
    tradier = Tradier(RawStore(out / "raw"), token, base=SANDBOX if sandbox else API)
    said: dict[str, Any] = {"host": "sandbox" if sandbox else "api"}
    try:
        entitled = tradier.entitlements()
    except VendorError as failed:
        print(f"live: Tradier did not answer: {failed.status} {failed.detail}")
        return 1
    said["answered"], said["real_time"] = entitled.answered, entitled.real_time
    if not entitled.answered:
        print(json.dumps({**said, "detail": entitled.detail}, indent=1))
        return 1
    today = dt.datetime.now(dt.UTC).date()
    first = min(dt.date(2026, 10, 5), today - dt.timedelta(days=10))
    histories = {
        s: tradier.history(tradier_symbol(s), first.isoformat(), today.isoformat()) for s in SYMBOLS
    }
    bars = [bar for s, fetched in histories.items() for bar in convert.history(fetched, s)]
    quotes = tradier.quotes([tradier_symbol(s) for s in SYMBOLS])
    live = list(convert.quotes(quotes))
    said["daily_bars"] = {s: sum(1 for b in bars if b.symbol == s) for s in SYMBOLS}
    said["closes"] = [
        {"symbol": b.symbol, "business_date": b.business_date.isoformat(), "close": str(b.close)}
        for b in bars[-4:]
    ]
    said["live"] = [
        {"symbol": q.symbol, "kind": q.kind, "price": str(q.amount), "venue_code": q.venue_code}
        for q in live
    ]
    held = quotes.value.get("quotes") or {}
    said["sizes_in_hundreds"] = {
        str(q.get("symbol")): [q.get("bidsize"), q.get("asksize")]
        for q in as_list(held.get("quote") if isinstance(held, dict) else None)
    }
    said["unconverted"] = sum(len(b.unconverted) for b in bars) + sum(
        len(q.unconverted) for q in live
    )
    if not sandbox:
        # Tradier's sandbox does not stream.
        said["stream"] = asyncio.run(listen(tradier, RawStore(out / "raw")))
    said["calls"], said["rate_limited"] = tradier.usage.calls, tradier.usage.rate_limited
    kept = "".join(p.read_text() for p in (out / "raw").rglob("*.json*"))
    said["key_in_raw_records"] = any(secret in kept for secret in token.secrets())
    exchange = {
        "_about": "Recorded from Tradier by `make live`, for the account holder's personal use.",
        "history": {
            tradier_symbol(s): _text(as_list(((f.value.get("history") or {}) or {}).get("day")))
            for s, f in histories.items()
        },
        "quotes": {
            str(q.get("symbol")): _text(q)
            for q in as_list(held.get("quote") if isinstance(held, dict) else None)
        },
    }
    (out / "exchange.json").write_text(json.dumps(exchange, indent=1))
    said["recorded_in"] = str(out)
    print(json.dumps(said, indent=1, default=str))
    return 1 if said["key_in_raw_records"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
