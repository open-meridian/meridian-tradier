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
A want for the other is declined, not entitled: this environment does not
serve it. Daily closes are end of day in both, and the sandbox streams no
trades, so `daily` and `trades` stay one each.
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

from . import conditions
from .convert import SOURCE

#: The live kind delayed 15 minutes: the developer sandbox's (ruling 551).
LIVE_DELAYED = "live_delayed"

__all__ = [
    "BAR", "DAILY", "LIVE", "LIVE_DELAYED", "LIVE_CADENCE_SECONDS", "LIVE_KINDS", "PRICE",
    "QUOTE", "TRADE", "TRADES", "Counts", "Forming", "Lake", "Products", "Source", "Standing",
    "row_key",
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
        return LIVE if key == LIVE_DELAYED else key

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
        self.restream()

    async def on_want(self, heard: Any) -> None:
        """A want of the live kind's other timeliness is declined, not
        entitled; any other is the SDK's to answer."""
        want: ops.ObservationsWantedEvent = heard.message
        if self._key_of(want.dataset) == LIVE and want.dataset != self.dataset(LIVE):
            subjects = [s.entity_id for s in want.subjects]
            await self._decline(LIVE, want.want_id, subjects, "not_entitled", settled=False)
            return
        await super().on_want(heard)
