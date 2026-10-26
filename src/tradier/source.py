"""Tradier, as the lake's half of the plugin asks it (lake.Source).

Daily bars from `/markets/history`, one listing a call; live prices and
quotes from `/markets/quotes`, a hundred listings a call, consolidated from
every exchange; from 0.13.0 an underlying's expirations, one expiration's
chain a call, and a month's market days (chains.py). Each listing is
asked in Tradier's spelling (`BRK/B`) and named in the one spelling the
retail pair shares (`BRK.B`). Whether Tradier answers the token is asked
once, and again when the token changes; the Connection page shows the
answer.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Sequence

from . import convert
from .convert import ChainOption, DailyBar, Quoted, SourceQuote, tradier_symbol
from .vendor import SYMBOLS_PER_CALL, Entitlements, Tradier


class TradierSource:
    """lake.Source on Tradier's market data API."""

    def __init__(self, tradier: Tradier, synthetic: bool = False) -> None:
        self.tradier = tradier
        self.synthetic = synthetic
        self._entitled: Entitlements | None = None
        self._lock = threading.Lock()

    def entitlements(self, again: bool = False) -> Entitlements:
        with self._lock:
            if self._entitled is None or again:
                if self.synthetic:
                    self._entitled = Entitlements(answered=True, real_time=True)
                else:
                    self._entitled = self.tradier.entitlements()
            return self._entitled

    @property
    def known(self) -> Entitlements | None:
        return self._entitled

    def daily(self, symbols: Sequence[str], first: dt.date, last: dt.date) -> list[DailyBar]:
        bars: list[DailyBar] = []
        for symbol in symbols:
            fetched = self.tradier.history(
                tradier_symbol(symbol), first.isoformat(), last.isoformat()
            )
            bars.extend(convert.history(fetched, symbol))
        return bars

    def quotes(self, symbols: Sequence[str]) -> list[SourceQuote]:
        """The consolidated best bid and offer of each listing, with sizes."""
        quotes: list[SourceQuote] = []
        for start in range(0, len(symbols), SYMBOLS_PER_CALL):
            chunk = [tradier_symbol(s) for s in symbols[start : start + SYMBOLS_PER_CALL]]
            quotes.extend(convert.quote_rows(self.tradier.quotes(chunk)))
        return quotes

    def live(self, symbols: Sequence[str]) -> list[Quoted]:
        quoted: list[Quoted] = []
        for start in range(0, len(symbols), SYMBOLS_PER_CALL):
            chunk = [tradier_symbol(s) for s in symbols[start : start + SYMBOLS_PER_CALL]]
            quoted.extend(convert.quotes(self.tradier.quotes(chunk)))
        return quoted

    # ── Option chains (from 0.13.0) ──────────────────────────────────────

    def kind(self, symbol: str) -> str:
        """What Tradier says a listing is (its quote's `type`: `stock`,
        `etf`, `index`, ...), or "" where it does not know it."""
        fetched = self.tradier.quotes([tradier_symbol(symbol)])
        held = fetched.value.get("quotes") if isinstance(fetched.value, dict) else None
        for item in convert.as_list(held.get("quote") if isinstance(held, dict) else None):
            if convert.spelled(str(item.get("symbol") or "")) == symbol:
                return str(item.get("type") or "")
        return ""

    def expirations(self, symbol: str) -> list[dt.date]:
        return convert.expirations(self.tradier.expirations(tradier_symbol(symbol)))

    def chain(self, symbol: str, expiration: dt.date) -> list[ChainOption]:
        fetched = self.tradier.chain(tradier_symbol(symbol), expiration.isoformat())
        return list(convert.chain(fetched, symbol))

    def market_days(self, year: int, month: int) -> dict[dt.date, bool]:
        return convert.market_days(self.tradier.calendar(year, month))
