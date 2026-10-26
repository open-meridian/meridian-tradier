"""What the plugin records in the lake, and how it answers what the lake wants
(contracts v18 and v19, W10): from SDK 0.31.0 the SDK's
(`meridian.roles.data.listings`, ruling 213), this module keeping what is
Tradier's alone -- its source's name, the history it documents no limit to,
its time and sales prints' attributes from their flag, session and
correction (conditions.py) and their sequence numbers. Streamed only: its
time and sales history carries no sequence number to name a trade by, so
neither a range nor a reconnect's gap is read; a cancel naming no print
recorded here is counted and not sent; its quotes name no venue.

**One dataset per timeliness** (from 0.12.0; ruling 551, after 382): Live's
quotes and prices are real time, the developer sandbox's delayed 15
minutes, so they are two datasets, `live` and `live_delayed`, each with its
declared delay. The feed records the live kind into whichever the
environment provides (`delayed`, set from the settings): the SDK's feed
works by its `live` key, and this module names the dataset it is in now.
A want for the other is declined, not covered: this environment does not
serve it. Daily closes are end of day in both, and the sandbox streams no
trades, so `daily` and `trades` stay one each.

**A decline names a reason the lake takes** (0.13.1): DeclineWant takes
`not_covered`, `source_silent` or `beyond_history` and nothing else; the
lake refuses any other, and a refusal raised in a want's handler ends the
SDK's delivery stream, the wants behind it lost. 0.12.0 to 0.13.0 declined
the other timeliness `not_entitled`, which the lake refused every time.

**Option chains** (from 0.13.0; contract v28, ruling 660): a want of the
`options` or `options_delayed` dataset is chains.py's, its series, quotes
and statistics recorded into whichever the environment provides, as the
live kind is; kept current by the timetable (`tick`).

**The edge, done here for now** (from 0.13.0; contract v28, rulings 424
and 518): each live price, quote and trade recorded unasked or for a
standing want has its feed delay recorded (`roles.Latency.aged`, the
`edge` hop) and is judged by the SDK's quality checks
(`quality.EdgeChecks`), as the SDK's `Wants.record` does for the other
feeds. TEMPORARY: the SDK's listings feed records neither in 0.33.1; this
glue goes when its listings feed takes them over (queued as SDK 0.33.2).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import listings
from meridian.roles.data.listings import (
    BAR,
    DAILY,
    LIVE,
    LIVE_CADENCE_SECONDS,
    LIVE_KINDS,
    PRICE,
    QUOTE,
    TRADE,
    TRADES,
    Counts,
    Forming,
    Listings,
    Source,
    Standing,
    row_key,
)
from meridian.roles.data.quality import EdgeChecks

from . import conditions
from .chains import OPTIONS, OPTIONS_DELAYED, Chains
from .convert import SOURCE

#: The live kind delayed 15 minutes: the developer sandbox's (ruling 551).
LIVE_DELAYED = "live_delayed"

__all__ = [
    "BAR", "DAILY", "LIVE", "LIVE_DELAYED", "OPTIONS", "OPTIONS_DELAYED", "LIVE_CADENCE_SECONDS",
    "LIVE_KINDS", "PRICE", "QUOTE", "TRADE", "TRADES", "Counts", "Forming", "Lake", "Products",
    "Source", "Standing", "row_key",
]  # fmt: skip

#: The earliest day asked of the source's daily history: Tradier documents
#: no limit, so a day before this is declined beyond the history.
HISTORY_FROM = dt.date(1990, 1, 1)

#: Which listing each subject is, kept in the plugin's storage.
Products = Listings


class Lake(listings.Feed):
    """Tradier's listings in the lake: the SDK's feed, Tradier's prints."""

    source_name = SOURCE
    history_from = HISTORY_FROM
    settles_declines = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: The option chains wanted (from 0.13.0), counted as one dataset.
        self.counts[OPTIONS] = listings.Counts()
        self.chains = Chains(self)
        #: The plugin's `roles.Latency`, where it keeps one: each live row's
        #: age at the edge recorded (the feed delay); and the edge's checks.
        self.latency: Any = None
        self.quality = EdgeChecks(clock_ns=self.clock_ns)

    def at_the_edge(self, key: str, rows: list[Any], want_id: str) -> list[Any]:
        """Rows of the dataset `key` recorded unasked or for a standing
        want, their age at the edge recorded and judged by the SDK's
        checks; rows pulled for a read as they are. A chain's quotes are
        judged series by series (their subject is the underlying).
        TEMPORARY until the SDK's listings feed does it (SDK 0.33.2)."""
        standing = {w.want_id for w in self.standing.values()}
        standing |= {w for held in self.chains.underlyings.values() for w in held.standing}
        if want_id and want_id not in standing:
            return rows
        dataset = self.named(key)
        if self.latency is not None:
            for row in rows:
                self.latency.aged(dataset, "AGE_HOP_EDGE", row)
        if key not in (OPTIONS, OPTIONS_DELAYED):
            return self.quality.judged(key, rows)
        out: list[Any] = []
        for row in rows:
            series = row.meta.series_key[0].value if row.meta.series_key else ""
            out.extend(self.quality.judged(f"{key}/{series}", [row]))
        return out

    async def _record(self, key: str, data_type: str, rows: Any, want_id: str) -> None:
        if key in (LIVE, TRADES) and data_type in (PRICE, QUOTE, TRADE):
            in_force = LIVE_DELAYED if key == LIVE and self.delayed else key
            rows = self.at_the_edge(in_force, list(rows), want_id)
        await super()._record(key, data_type, rows, want_id)

    def attributes(self, stated: Any) -> listings.Attributes:
        said = conditions.trade_attributes(stated.flag, stated.session, stated.correction)
        return listings.Attributes(
            said.characteristics, said.consolidated, said.market_centre, said.unconverted
        )

    def withdrawn_unrecorded(self, stated: Any) -> listings.Attributes | None:
        return None

    def sequence_of(self, stated: Any) -> int | None:
        return int(stated.sequence)

    #: Whether the environment's live data is delayed (the sandbox's), so
    #: the live kind is recorded into `live_delayed` (above).
    delayed: bool = False

    def named(self, key: str) -> str:
        """A declared dataset's ID in the deployment, by its own key."""
        return super().dataset(key)

    def dataset(self, key: str) -> str:
        """The dataset the feed's `key` is recorded into now: the live kind
        into `live_delayed` while the environment is delayed."""
        return self.named(LIVE_DELAYED if key == LIVE and self.delayed else key)

    def _key_of(self, dataset: str) -> str:
        key = super()._key_of(dataset)
        return {LIVE_DELAYED: LIVE, OPTIONS_DELAYED: OPTIONS}.get(key, key)

    def use_delayed(self, delayed: bool) -> None:
        """The environment's timeliness, as the settings stand: on a change,
        the standing wants of the live kind are let go, since they were
        asked of the other dataset; the lake asks again of this one."""
        if delayed == self.delayed:
            return
        self.delayed = delayed
        for want_id, standing in list(self.standing.items()):
            if standing.dataset == LIVE:
                self.standing.pop(want_id, None)
        self.chains.reset()
        self.restream()

    async def on_want(self, heard: Any) -> None:
        """A want of the live kind's other timeliness is declined, not
        covered (this environment does not serve it); any other is the
        SDK's to answer."""
        want: ops.ObservationsWantedEvent = heard.message
        if self._key_of(want.dataset) == OPTIONS:
            await self.chains.on_want(want)
            return
        if self._key_of(want.dataset) == LIVE and want.dataset != self.dataset(LIVE):
            subjects = [s.entity_id for s in want.subjects]
            await self._decline(LIVE, want.want_id, subjects, "not_covered", settled=False)
            return
        await super().on_want(heard)

    async def on_withdrawn(self, heard: Any) -> None:
        """A standing want withdrawn, a chain's among them."""
        self.chains.withdraw(heard.message.want_id)
        await super().on_withdrawn(heard)

    async def tick(self) -> None:
        """The SDK's timetable, then the chains due (chains.py)."""
        await super().tick()
        await self.chains.refresh()
