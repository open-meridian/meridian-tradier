"""The plugin's pages, under Manage alone: Connection and Datasets, each a read
tool on the deployment's MCP surface answering what the page shows
(`read_connection`, `read_datasets`; the lake plan's "Every new page's
tools"). A `dgm` shows no market data: prices are the reading roles' to
read, under their entitlement, and an admin page shows no account's data.

Each page fits one screen at 1440x900 and 390x844: one-line rows, the
standing wants cut to the first few with the rest counted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import meridian
from meridian.plugin.v1 import operations_pb2 as ops

from .convert import NEW_YORK
from .declaration import CATALOGUE
from .lake import DAILY, LIVE, Lake
from .records import ConnectionRead, DatasetRead, DatasetsRead, FeedRead, StandingRead
from .settings import Config
from .source import TradierSource
from .vendor import LIMIT_PER_MINUTE, NS, Tradier, Usage

TITLE = "Tradier"
CONNECTION = "/"
DATASETS = "/datasets"
#: Tradier's own limit on market data per token, of which the client spends
#: half.
VENDOR_LIMIT_PER_MINUTE = 120
#: How many standing wants the page lists before counting the rest.
STANDING_SHOWN = 6

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates")


@dataclass
class State:
    """What the pages read: the settings, the lake's half and the source."""

    config: Config = field(default_factory=Config)
    lake: Lake | None = None
    source: TradierSource | None = None
    tradier: Tradier | None = None


_state = State()


def use(state: State) -> None:
    """The state the pages read from now on."""
    global _state
    _state = state


def _when(at_ns: int) -> str:
    if not at_ns:
        return ""
    moment = dt.datetime.fromtimestamp(at_ns / NS, dt.UTC)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _shown(at: str) -> str:
    """A moment as the page shows it: New York's time, to the minute."""
    if not at:
        return "never"
    moment = dt.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(NEW_YORK)
    return moment.strftime("%b %d %H:%M ET")


def connection_read(state: State) -> ConnectionRead:
    config = state.config
    usage = state.tradier.usage if state.tradier is not None else Usage()
    known = state.source.known if state.source is not None else None
    if config.synthetic:
        mode, detail = (
            "synthetic",
            "Serving the built-in synthetic exchange; Tradier is not called.",
        )
    elif config.credentials is None:
        mode, detail = "no key", "Enter the API access token in Settings."
    elif known is None:
        mode, detail = "live", "Not asked yet: Tradier is asked when the token is saved."
    else:
        mode, detail = "live", known.detail or ("Answered." if known.answered else "")
    answered = bool(known and known.answered)
    real_time = bool(known and known.real_time)
    feeds = [
        FeedRead("history", "Daily history, every exchange", answered),
        FeedRead("quotes", "Quotes, every exchange, in real time", answered and real_time),
    ]
    return ConnectionRead(
        mode=mode,
        token_set=config.token_set,
        answered=answered or config.synthetic,
        detail=detail,
        feeds=feeds,
        daily_feed="history",
        live_feed="quotes" if real_time or config.synthetic else "quotes, delayed",
        limit_per_minute=LIMIT_PER_MINUTE,
        vendor_limit_per_minute=VENDOR_LIMIT_PER_MINUTE,
        calls=usage.calls,
        rate_limited=usage.rate_limited,
        last_call_at=_when(usage.last_call_at_ns),
        last_status=usage.last_status,
        last_error=usage.last_error or (state.lake.last_error if state.lake else ""),
        sessions=[],
    )


def datasets_read(state: State) -> DatasetsRead:
    lake = state.lake
    connection = connection_read(state)
    rows: list[DatasetRead] = []
    for declared in CATALOGUE:
        counts = lake.counts[declared.key] if lake is not None else None
        daily = declared.key == DAILY
        rows.append(
            DatasetRead(
                dataset=lake.dataset(declared.key) if lake is not None else declared.key,
                key=declared.key,
                serves="closes and daily bars" if daily else "last, bid and ask",
                feed="consolidated",
                modes=[_mode(m) for m in declared.modes],
                cadence_seconds=declared.cadence,
                kept_by_default=bool(declared.licence_default and declared.licence_default.kept),
                personal_use=bool(
                    declared.licence_default and declared.licence_default.personal_use
                ),
                entitled=connection.answered,
                recorded=counts.recorded if counts else 0,
                restated=counts.restated if counts else 0,
                unchanged=counts.unchanged if counts else 0,
                declined=counts.declined if counts else 0,
                unconverted=counts.unconverted if counts else 0,
                wants=counts.wants if counts else 0,
                last_recorded_at=_when(counts.last_recorded_at_ns) if counts else "",
            )
        )
    standing = []
    if lake is not None:
        for want in lake.standing.values():
            symbols = [lake.products.symbols.get(s, s) for s in want.subjects]
            standing.append(
                StandingRead(
                    want_id=want.want_id,
                    dataset=lake.dataset(LIVE),
                    subjects=len(want.subjects),
                    symbols=symbols,
                    kinds=list(want.kinds),
                    last_kept_at=_when(want.last_at_ns),
                )
            )
    return DatasetsRead(
        datasets=rows,
        standing=standing,
        listings=len(lake.products.symbols) if lake is not None else 0,
        forming=len(lake.forming) if lake is not None else 0,
        reads_instruments=lake.reads_instruments if lake is not None else True,
    )


def _mode(mode: object) -> str:
    """A catalogue's mode as the word the SDK sends (`pull`)."""
    if isinstance(mode, int):
        return str(ops.ObservationMode.Name(mode)).removeprefix("OBSERVATION_MODE_").lower()
    return str(mode).removeprefix("OBSERVATION_MODE_").lower()


def _dot(read: ConnectionRead) -> dict[str, str]:
    if read.mode == "synthetic":
        return {"state": "ok", "label": "Synthetic", "text": "Synthetic"}
    if read.mode == "no key":
        return {"state": "warn", "label": "No key", "text": "No key"}
    if not read.answered:
        return {"state": "error", "label": "Not answering", "text": "Not answering"}
    if read.last_error:
        return {"state": "warn", "label": "Errors", "text": "Errors"}
    return {"state": "ok", "label": "Connected", "text": "Connected"}


def _yes(flag: bool) -> dict[str, str]:
    return {"label": "Yes", "tone": "good"} if flag else {"label": "No", "tone": "warn"}


@pages.page(
    CONNECTION,
    "Connection",
    levels="admin",
    answers=ConnectionRead,
    name="read_connection",
    description=(
        "The plugin's connection to Tradier: whether the access token is set (never its "
        "value) and whether Tradier answers it, whether its quotes are real time, Tradier's "
        "rate limit and what this process has spent of it, the last error, and its "
        "sessions. No market data."
    ),
)
async def connection(request: meridian.Request) -> meridian.Response:
    read = connection_read(_state)
    entitled = [f.what for f in read.feeds if f.entitled]
    refused = [f.what for f in read.feeds if not f.entitled]
    key_rows = [
        {"what": "Mode", "value": read.mode.capitalize(), "note": read.detail},
        {
            "what": "Token",
            "value": "Set" if read.token_set else "Not set",
            "note": "A secret setting: never shown",
        },
        {"what": "Entitled", "value": "; ".join(entitled) or "Nothing yet", "note": ""},
        {"what": "Not entitled", "value": "; ".join(refused) or "Nothing", "note": ""},
    ]
    use_rows = [
        {
            "what": "Rate limit",
            "value": f"{read.limit_per_minute} a minute",
            "note": f"half of Tradier's {read.vendor_limit_per_minute} for market data",
        },
        {
            "what": "Calls",
            "value": f"{read.calls} since start",
            "note": f"{read.rate_limited} answered 429 and waited out",
        },
        {
            "what": "Last call",
            "value": _shown(read.last_call_at),
            "note": f"HTTP {read.last_status}" if read.last_status else "",
        },
        {"what": "Last error", "value": read.last_error or "None", "note": ""},
        {
            "what": "Sessions",
            "value": "None",
            "note": "Tradier's streaming arrives with the lake's trades and quotes",
        },
    ]
    return pages.answer(
        "connection.html",
        read,
        dot=_dot(read),
        key_rows=key_rows,
        use_rows=use_rows,
        feeds={"daily": read.daily_feed, "live": read.live_feed},
    )


@pages.page(
    DATASETS,
    "Datasets",
    levels="admin",
    answers=DatasetsRead,
    name="read_datasets",
    description=(
        "The datasets the plugin serves the lake: each one's catalogue entry (what it "
        "serves, how rows arrive, its default terms), whether the token is answered for it "
        "at Tradier, and what it recorded, restated and declined since the "
        "plugin started; the standing wants it keeps current; the listings it has served. "
        "No prices."
    ),
)
async def datasets(request: meridian.Request) -> meridian.Response:
    read = datasets_read(_state)
    grid_rows = [
        {
            "id": d.key,
            "dataset": d.dataset,
            "serves": d.serves,
            "feed": d.feed,
            "modes": ", ".join(d.modes),
            "terms": ("kept" if d.kept_by_default else "served")
            + ("; personal" if d.personal_use else ""),
            "entitled": "Yes" if d.entitled else "No",
            "entitled_tone": "good" if d.entitled else "warn",
            "recorded": str(d.recorded),
            "restated": str(d.restated),
            "declined": str(d.declined),
            "unconverted": str(d.unconverted),
            "last": _shown(d.last_recorded_at),
        }
        for d in read.datasets
    ]
    columns = [
        {"key": "dataset", "label": "Dataset", "strong": True, "priority": 1, "width": "7.5rem"},
        {"key": "feed", "label": "Feed", "priority": 3, "width": "7.5rem"},
        {"key": "modes", "label": "Arrives", "priority": 3, "width": "7rem"},
        {"key": "terms", "label": "Default terms", "priority": 3, "width": "9rem"},
        {
            "key": "entitled",
            "label": "Entitled",
            "type": "badge",
            "tone": {"field": "entitled_tone"},
            "priority": 1,
            "width": "6rem",
        },
        {"key": "recorded", "label": "Recorded", "type": "number", "priority": 1},
        {"key": "restated", "label": "Restated", "type": "number", "priority": 3},
        {"key": "declined", "label": "Declined", "type": "number", "priority": 2},
        {"key": "unconverted", "label": "Unconverted", "type": "number", "priority": 3},
        {"key": "last", "label": "Last recorded", "priority": 3, "width": "8rem"},
    ]
    standing_rows = [
        {
            "id": s.want_id,
            "symbols": ", ".join(s.symbols[:8])
            + (f" and {len(s.symbols) - 8} more" if len(s.symbols) > 8 else ""),
            "kinds": ", ".join(s.kinds),
            "subjects": str(s.subjects),
            "kept": _shown(s.last_kept_at),
        }
        for s in read.standing[:STANDING_SHOWN]
    ]
    standing_columns = [
        {"key": "symbols", "label": "Listings", "strong": True, "priority": 1},
        {"key": "kinds", "label": "Prices", "priority": 3},
        {"key": "subjects", "label": "Subjects", "type": "number", "priority": 1},
        {"key": "kept", "label": "Last kept", "priority": 2},
    ]
    return pages.answer(
        "datasets.html",
        read,
        grid={"columns": columns, "rows": grid_rows},
        grid_rows=grid_rows,
        standing_grid={"columns": standing_columns, "rows": standing_rows},
        standing_rows=standing_rows,
        more=max(0, len(read.standing) - STANDING_SHOWN),
    )


def serve(plugin: meridian.Plugin, state: State, port: int) -> Any:
    """Serve the pages on loopback beside the sidecar, reading `state`."""
    use(state)
    return pages.serve(plugin, port)
