"""Tradier's time and sales, converted to the platform's trade attributes at
the edge (contract v19, W10.4; plans/the-lake-prices-the-book, row 19).

Tradier's stream says of each print its session (`pre`, `regular`, `post`;
the streaming API's own word) and a flag, and whether it corrects a print.
Tradier documents the session and not the flag's values, so the conversion
holds only what is documented (step 5's principle 3: how a plugin converts
its codes is its own):

- a print with no flag in the regular session is a regular trade: it may set
  every statistic, of the consolidated bar and of its market centre's;
- a print outside the regular session is an extended-hours trade, counted
  in the volume only, as the processors' sale-condition matrices count one;
- a flag, or a correction, is kept as reported (`tradier:timesale.flag`,
  `tradier:timesale.correction`), never guessed: the print's eligibilities
  are then not known, and it is counted on the Datasets page for a person
  to map once Tradier says what its flags mean.

No vendor's code reaches the lake as the meaning of anything: only the
platform's attributes, and the codes as reported beside them.
"""

from __future__ import annotations

from dataclasses import dataclass

from meridian.edge import as_reported
from meridian.plugin.v1.operations_pb2 import AsReported

#: Tradier's words for the regular session (its documentation says
#: `regular`; its examples, `normal`).
REGULAR_SESSIONS = frozenset({"regular", "normal", ""})
EXTENDED_SESSIONS = frozenset({"pre", "post"})

Flags = tuple[bool | None, bool | None, bool | None, bool | None]
NOT_KNOWN: Flags = (None, None, None, None)
EVERY: Flags = (True, True, True, True)
VOLUME_ONLY: Flags = (False, False, False, True)


@dataclass(frozen=True)
class Attributes:
    """A print's attributes as converted: each eligibility True, False, or
    None where what Tradier said did not convert (not known)."""

    characteristics: tuple[str, ...]
    consolidated: Flags
    market_centre: Flags
    unconverted: tuple[AsReported, ...] = ()


def trade_attributes(flag: str, session: str, correction: bool) -> Attributes:
    """The platform's attributes for a print's flag, session and correction."""
    unconverted: list[AsReported] = []
    if flag:
        unconverted.append(as_reported("tradier:timesale.flag", flag[:16]))
    if correction:
        unconverted.append(as_reported("tradier:timesale.correction", "true"))
    if session not in REGULAR_SESSIONS | EXTENDED_SESSIONS:
        unconverted.append(as_reported("tradier:timesale.session", session[:16]))
    characteristics = ("extended_hours",) if session in EXTENDED_SESSIONS else ()
    if unconverted:
        return Attributes(characteristics, NOT_KNOWN, NOT_KNOWN, tuple(unconverted))
    flags = VOLUME_ONLY if characteristics else EVERY
    return Attributes(characteristics, flags, flags)
