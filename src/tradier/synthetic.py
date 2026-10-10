"""Synthetic Tradier: answers the plugin's calls from the built-in exchange,
with no token and no network (the `synthetic` setting, for development, the
tests and the e2e).

`exchanges/exchange.json` is shaped on Tradier's documented responses with
every value invented (the lake plan's Q11: real responses stay in a
developer's own storage, never committed): daily history for SPY, BRK/B (as
Tradier spells it) and TQQQ over 2026-10-05 to 2026-10-09, TQQQ's last close
with eighteen decimal places, and the quotes of SPY and BRK/B, BRK/B's bid
side empty, sizes in hundreds. Its numbers are text in the file and go out
as JSON numbers, exactly as written, as Tradier sends them; and, as Tradier
does, a list of one goes out as the one object, none as `null`, and a symbol
it does not know under `unmatched_symbols`.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from .vendor import Response

#: The fields Tradier sends as text, never as numbers.
TEXT_FIELDS = frozenset({"symbol", "description", "exch", "type", "bidexch", "askexch", "date"})


def exchange(path: Path | None = None) -> dict[str, Any]:
    """The built-in exchange, or the one at `path` (a developer's recording)."""
    if path is not None:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    text = resources.files("tradier").joinpath("exchanges/exchange.json").read_text("utf-8")
    built: dict[str, Any] = json.loads(text)
    return built


def dumps(value: Any, key: str = "") -> str:
    """JSON with each number written as its text."""
    if isinstance(value, dict):
        inner = ",".join(f"{json.dumps(k)}:{dumps(v, k)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, list):
        return "[" + ",".join(dumps(v, key) for v in value) + "]"
    if (
        isinstance(value, str)
        and key
        and key not in TEXT_FIELDS
        and re.fullmatch(r"-?\d+(\.\d+)?", value)
    ):
        return value
    return json.dumps(value)


def _one_or_many(items: list[Any]) -> Any:
    """Tradier's list: none is null, one is the object, more a list."""
    if not items:
        return None
    return items[0] if len(items) == 1 else items


class SyntheticTransport:
    """vendor.Transport on the built-in exchange: `/markets/history` and
    `/markets/quotes`, on either Tradier's host or its sandbox."""

    def __init__(self, held: Mapping[str, Any] | None = None) -> None:
        self.held = held if held is not None else exchange()
        self.asked: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append(url)
        parsed = urllib.parse.urlparse(url)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path.endswith("/markets/history"):
            first, last = params.get("start", ""), params.get("end", "")
            days = [
                day
                for day in self.held.get("history", {}).get(params.get("symbol", ""), [])
                if (not first or day["date"] >= first) and (not last or day["date"] <= last)
            ]
            history = _one_or_many(days)
            return self._ok({"history": None if history is None else {"day": history}})
        if parsed.path.endswith("/markets/quotes"):
            symbols = [s for s in params.get("symbols", "").split(",") if s]
            held = self.held.get("quotes", {})
            found = [held[s] for s in symbols if s in held]
            unmatched = [s for s in symbols if s not in held]
            body: dict[str, Any] = {"quote": _one_or_many(found)}
            if unmatched:
                body["unmatched_symbols"] = {"symbol": _one_or_many(unmatched)}
            return self._ok({"quotes": body})
        return Response(404, {"content-type": "text/plain"}, b"Not Found")

    @staticmethod
    def _ok(body: Any) -> Response:
        return Response(200, {"content-type": "application/json"}, dumps(body).encode())
