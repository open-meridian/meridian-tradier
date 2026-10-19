"""What the plugin records in the lake, and how it answers what the lake wants
(contracts v18 and v19, W10): from SDK 0.31.0 the SDK's
(`meridian.roles.data.listings`, ruling 213), this module keeping what is
Tradier's alone -- its source's name, the history it documents no limit to,
its time and sales prints' attributes from their flag, session and
correction (conditions.py) and their sequence numbers. Streamed only: its
time and sales history carries no sequence number to name a trade by, so
neither a range nor a reconnect's gap is read; a cancel naming no print
recorded here is counted and not sent; its quotes name no venue.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

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

__all__ = [
    "BAR", "DAILY", "LIVE", "LIVE_CADENCE_SECONDS", "LIVE_KINDS", "PRICE", "QUOTE", "TRADE",
    "TRADES", "Counts", "Forming", "Lake", "Products", "Source", "Standing", "row_key",
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
