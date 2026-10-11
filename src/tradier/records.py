"""What the pages' read tools answer (contract v12's parity: a page and its tool
read one source, `pages.answer`): the data role's common records
(`meridian.roles.data`, spec/plugin-pages-follow-their-role), each extended
with Tradier's own fields beside the common ones. Configuration and the
plugin's own work only: never a price, which is the reading roles' to read
under their entitlement, and never a token, of which only whether it is
set."""

from __future__ import annotations

from dataclasses import dataclass, field

from meridian.roles import data


@dataclass(frozen=True)
class FeedRead:
    """What Tradier serves the token, and whether it answered for it."""

    feed: str
    what: str
    entitled: bool


@dataclass(frozen=True)
class SessionRead:
    """The stream: its state (idle, connecting, streaming, waiting, refused,
    no key), the listings it streams, the sessions opened and reopened (each
    reopening a gap Tradier's history cannot fill), the messages heard, and
    the last message and error. Never a token or a session's ID."""

    state: str
    subscribed: int = 0
    opened: int = 0
    reconnects: int = 0
    messages: int = 0
    since: str = ""
    last_message_at: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class ConnectionRead(data.ConnectionRead):
    """Connection's common fields, then Tradier's: the environment chosen,
    the host asked, what the mode means now, what the token is not served,
    each of Tradier's feeds and whether the token answered for it, whether
    its quotes are real time, the last call's HTTP status, and the stream's
    session (none on the sandbox, which does not stream)."""

    environment: str = "live"
    host: str = ""
    detail: str = ""
    not_entitled: str = ""
    feeds: list[FeedRead] = field(default_factory=list)
    real_time: bool = False
    last_status: int = 0
    stream: SessionRead | None = None


@dataclass(frozen=True)
class Served(data.Served):
    """One dataset as "Served" shows it, then Tradier's: its key, the feed and
    host it reads, and what it restated, kept unchanged, could not convert
    and could not match since the plugin started."""

    key: str = ""
    feed: str = ""
    restated: int = 0
    unchanged: int = 0
    unconverted: int = 0
    unmatched: int = 0


@dataclass(frozen=True)
class Want(data.Want):
    """One standing want as "Wants" shows it, then Tradier's: its ID, the
    listings it names, and whether they are streamed."""

    want_id: str = ""
    listings: list[str] = field(default_factory=list)
    streamed: bool = False


@dataclass(frozen=True)
class DatasetsRead(data.DatasetsRead):
    """Datasets' common fields, then Tradier's: the listings it knows, the
    days still forming, the listings streamed, and whether a restart's gap
    is backfilled (never: Tradier's time and sales history names no print by
    its sequence number, which a streamed trade's row is keyed by, so reading
    it would record a trade twice). Its rows are Tradier's, each extending
    the role's."""

    served: list[Served] = field(default_factory=list)  # type: ignore[assignment]
    wants: list[Want] = field(default_factory=list)  # type: ignore[assignment]
    listings: int = 0
    forming: int = 0
    streamed: int = 0
    backfills_a_restart: bool = False
