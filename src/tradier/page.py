"""The plugin's pages, under Manage alone: the data role's common pages
(spec/plugin-pages-follow-their-role), Connection and Datasets, in its
order, each a read tool on the deployment's MCP surface answering what the
page shows under the role's names (`read_connection`, `read_datasets`).
Each record is the role's (`meridian.roles.data`), extended with Tradier's
fields; each template is the role's, with Tradier's nuance at its blocks
only: the environment and host under "Key", its stream's session under
"Stream" (none on the sandbox, which does not stream), the feed each dataset
reads as a column of "Served", and a section of what it keeps current. A
data plugin shows no market data: prices, trades and quotes are the reading
roles' to read, under their entitlement, and an admin page shows no
account's data.

From 0.12.0 (SDK 0.32.0; rulings 202 and 457) Connection is one page for
the data role and connectivity, the SDK's
(`meridian.roles.connectivity.connection_pages`): connectivity's Trading is
`read_connection`'s `trading`, drawn as Connection's further sections
(Environment, Accounts, Placements), with "Enable trading" made on it; and
Raw records is the SDK's (`raw_records_page`). No Trading page of its own.

Each page fits one screen at 375, 582 and 1280 pixels wide: one-line rows,
the details a click away, and the standing wants, which grow, drawn the
latest few with how many there are (the tool answers every one).
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import meridian
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import Latency, connectivity, data
from meridian.roles.connectivity import Trader

from .convert import NEW_YORK
from .custody import Syncer
from .declared import CATALOGUE
from .kinds import KINDS, Store
from .lake import DAILY, LIVE, LIVE_DELAYED, PRICE, QUOTE, TRADES, Lake
from .records import ConnectionRead, DatasetsRead, FeedRead, Served, SessionRead, Want
from .settings import SAID, SANDBOX, SANDBOX_SAID, Config
from .source import TradierSource
from .stream import Streamer
from .vendor import LIMIT_PER_MINUTE, NS, Tradier, Usage

TITLE = "Tradier"
CONNECTION = connectivity.CONNECTION
DATASETS = "/datasets"
#: Tradier's own limit on market data per token, of which the client spends
#: half.
VENDOR_LIMIT_PER_MINUTE = 120
#: The kit the pages are built on: 0.12.0's "Facts" and "Next step".
KIT = "0.12.0"
#: The standing wants a browser is shown, the latest; the tool answers all.
SHOWN_WANTS = 3

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)


@dataclass
class State:
    """What the pages read: the settings, the lake's half and the source."""

    config: Config = field(default_factory=Config)
    lake: Lake | None = None
    source: TradierSource | None = None
    tradier: Tradier | None = None
    streamer: Streamer | None = None
    #: The datasets a deployment admin has licensed (contract v20), as read.
    licensed: frozenset[str] = frozenset()
    #: The account side: custody's reads (from 0.7.0), connectivity's
    #: trader (from 0.6.0), the kinds' store, the account scope with its
    #: links and its ems's map, and the settings as delivered (for each
    #: kind's window).
    syncer: Syncer | None = None
    trader: Trader | None = None
    #: Connectivity's venue as the settings stand, for the environment its
    #: session reached (contract v26).
    venue: Any = None
    updates: Any = None
    store: Store | None = None
    scope: meridian.AccountScope = field(default_factory=meridian.AccountScope)
    values: dict[str, object] = field(default_factory=dict)
    #: How often the orders are read, as Connection's Placements say it.
    polled: str = ""
    #: The sessions' latency (contract v27): the Trader's calls to Tradier's
    #: brokerage API, recorded for Connection's Sessions; not yet reported
    #: (core receives ReportLatency from contract v28, ruling 515).
    latency: Latency | None = None


_state = State()


def current() -> State:
    """The state the pages read now."""
    return _state


def use(state: State) -> None:
    """The state the pages read from now on."""
    global _state
    _state = state


def _when(at_ns: int) -> str:
    if not at_ns:
        return ""
    moment = dt.datetime.fromtimestamp(at_ns / NS, dt.UTC)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def shown(at: str) -> str:
    """A moment as the page shows it: New York's time, to the minute."""
    if not at:
        return ""
    moment = dt.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(NEW_YORK)
    return moment.strftime("%b %d %H:%M ET")


pages.environment.filters["shown"] = shown


def host(state: State) -> str:
    """The host Tradier is asked at, or none: sample data asks none, and
    there is no client while there is no token."""
    if state.config.sample_data or state.tradier is None:
        return ""
    return urllib.parse.urlparse(state.tradier.base).hostname or ""


def connection_read(state: State) -> ConnectionRead:
    config = state.config
    usage = state.tradier.usage if state.tradier is not None else Usage()
    known = state.source.known if state.source is not None else None
    sandbox = config.environment == SANDBOX
    if config.sample_data:
        mode, detail = "Sample data", "Recorded responses; Tradier is not called."
    elif config.credentials is None:
        token = "sandbox access token" if sandbox else "API access token"
        mode, detail = "No key", f"Enter the {token} in Settings."
    elif known is None:
        mode = "Sandbox" if sandbox else "Live"
        detail = "Not asked yet: Tradier is asked when the token is saved."
    elif not known.answered:
        mode, detail = (
            ("Sandbox" if sandbox else "Live"),
            f"Tradier refused the token: {known.detail}",
        )
    else:
        mode = "Sandbox" if sandbox else "Live"
        detail = SANDBOX_SAID if sandbox else "Tradier answers the token, in real time."
    answered = bool(known and known.answered) or config.sample_data
    real_time = bool(known and known.real_time) or config.sample_data
    feeds = [
        FeedRead("history", "daily history, every exchange", answered),
        FeedRead("quotes", "quotes, every exchange, delayed 15 minutes", answered)
        if config.on_sandbox
        else FeedRead("quotes", "quotes, every exchange, in real time", answered and real_time),
        FeedRead(
            "stream", "time and sales and quotes, streamed", answered and not config.on_sandbox
        ),
    ]
    asked = config.sample_data or (known is not None and known.answered)
    entitled = "; ".join(f.what for f in feeds if f.entitled)
    refused = "; ".join(f.what for f in feeds if not f.entitled)
    # The sandbox does not stream: no session, and "Does not stream".
    stream = session_read(state) if state.streamer is not None and not config.on_sandbox else None
    credential = (
        data.Credential("Sandbox access token", config.token_set)
        if sandbox
        else data.Credential("API access token", config.token_set)
    )
    return ConnectionRead(
        mode=mode,
        credentials=[credential],
        entitled_at_vendor=(entitled[:1].upper() + entitled[1:]) if asked else "",
        limit=(
            f"{LIMIT_PER_MINUTE} a minute, half of Tradier's {VENDOR_LIMIT_PER_MINUTE} "
            "for market data"
        ),
        calls=usage.calls,
        rate_limited=usage.rate_limited,
        last_call_at=_when(usage.last_call_at_ns),
        last_error=(
            usage.last_error
            or (state.lake.last_error if state.lake else "")
            or (stream.last_error if stream is not None else "")
        ),
        sessions=(
            None
            if config.on_sandbox
            else (1 if stream is not None and stream.state == "streaming" else 0)
        ),
        environment=config.environment,
        host=host(state),
        detail=detail,
        not_entitled=(refused[:1].upper() + refused[1:]) if asked else "",
        feeds=feeds,
        real_time=real_time,
        last_status=usage.last_status,
        stream=stream,
    )


def session_read(state: State) -> SessionRead:
    assert state.streamer is not None
    held = state.streamer.session
    return SessionRead(
        state=held.state,
        subscribed=held.subscribed,
        opened=held.opened,
        reconnects=held.reconnects,
        messages=held.messages,
        since=_when(held.since_ns),
        last_message_at=_when(held.last_message_at_ns),
        last_error=held.last_error,
    )


SERVES = {
    DAILY: "closes and daily bars",
    LIVE: "last, bid and ask; quotes",
    LIVE_DELAYED: "last, bid and ask; quotes, delayed 15 minutes",
    TRADES: "time and sales",
}


def _terms(declared: Any) -> str:
    licence = declared.licence_default
    if licence is None or not licence.kept:
        kept = "served, not kept"
    else:
        kept = f"kept {licence.retention_days} days" if licence.retention_days else "kept"
    return kept + ("; personal use" if licence is not None and licence.personal_use else "")


def datasets_read(state: State) -> DatasetsRead:
    lake = state.lake
    connection = connection_read(state)
    asked = host(state)
    delayed = ", delayed" if state.config.on_sandbox else ""
    feed = f"consolidated{delayed}, {asked}" if asked else "consolidated"
    served: list[Served] = []
    # One dataset per timeliness (ruling 551): the live kind's counts are the
    # dataset the environment records into now; the other's are none.
    in_force = LIVE_DELAYED if state.config.on_sandbox else LIVE
    for declared in CATALOGUE:
        live_kind = declared.key in (LIVE, LIVE_DELAYED)
        counts = (
            None
            if lake is None or (live_kind and declared.key != in_force)
            else lake.counts[LIVE if live_kind else declared.key]
        )
        if live_kind and declared.key != in_force:
            at_vendor = (
                "No: Live is real time"
                if declared.key == LIVE_DELAYED
                else "No: the sandbox's is delayed"
            )
        elif connection.mode == "Sample data":
            at_vendor = "Yes"
        elif connection.mode == "No key" or not connection.entitled_at_vendor:
            at_vendor = "Not asked yet"
        elif declared.key == TRADES and state.config.on_sandbox:
            # The sandbox does not stream, and trades are only streamed.
            at_vendor = "No: the sandbox does not stream"
        elif state.config.on_sandbox:
            at_vendor = "Yes, delayed 15 minutes"
        else:
            at_vendor = "Yes"
        dataset = lake.named(declared.key) if lake is not None else declared.key
        served.append(
            Served(
                dataset=dataset,
                data=SERVES.get(declared.key, declared.key),
                arrives=", ".join(_mode(m) for m in declared.modes),
                day="New York's, to 16:00",
                default_terms=_terms(declared),
                entitled_at_vendor=at_vendor,
                recorded=counts.recorded if counts else 0,
                declined=counts.declined if counts else 0,
                last_recorded=_when(counts.last_recorded_at_ns) if counts else "",
                licensed=dataset in state.licensed,
                key=declared.key,
                feed=feed,
                restated=counts.restated if counts else 0,
                unchanged=counts.unchanged if counts else 0,
                unconverted=counts.unconverted if counts else 0,
                unmatched=counts.unmatched if counts else 0,
            )
        )
    wants: list[Want] = []
    if lake is not None:
        streamed = set(lake.streamed)
        for standing in reversed(list(lake.standing.values())):
            listings = [lake.products.symbols.get(s, s) for s in standing.subjects]
            on_stream = bool(listings) and all(s in streamed for s in listings)
            answered = lake.by_want.get(standing.want_id, [0, 0])
            if standing.data_type == PRICE and standing.dataset == LIVE:
                state_word = f"Kept current, {shown(_when(standing.last_at_ns))}"
            elif state.config.on_sandbox:
                state_word = "Not streamed: the sandbox does not stream"
            else:
                state_word = "Streamed" if on_stream else "Not streamed"
            wants.append(
                Want(
                    dataset=lake.dataset(standing.dataset),
                    asked=_asks(standing.data_type, standing.kinds),
                    subjects=len(standing.subjects),
                    recorded=answered[0],
                    declined=answered[1],
                    state=state_word,
                    want_id=standing.want_id,
                    listings=listings,
                    streamed=on_stream,
                )
            )
    return DatasetsRead(
        served=served,
        wants=wants,
        reads_instruments=lake.reads_instruments if lake is not None else True,
        listings=len(lake.products.symbols) if lake is not None else 0,
        forming=len(lake.forming) if lake is not None else 0,
        streamed=len(lake.streamed) if lake is not None else 0,
        backfills_a_restart=False,
    )


def _asks(data_type: str, kinds: tuple[str, ...]) -> str:
    if data_type == PRICE:
        return ", ".join(kinds) or "prices"
    return "quotes" if data_type == QUOTE else "trades"


def _mode(mode: object) -> str:
    """A catalogue's mode as the word the SDK sends (`pull`)."""
    if isinstance(mode, int):
        return str(ops.ObservationMode.Name(mode)).removeprefix("OBSERVATION_MODE_").lower()
    return str(mode).removeprefix("OBSERVATION_MODE_").lower()


def status(read: ConnectionRead) -> dict[str, str]:
    """The head's status, the role's Connection words."""
    if read.mode == "Sample data":
        return {"state": "ok", "label": "Sample data"}
    if read.mode == "No key":
        return {"state": "warn", "label": "No key"}
    if not read.entitled_at_vendor:
        return {"state": "error", "label": "Not answering"}
    return {"state": "warn" if read.last_error else "ok", "label": "Answering"}


def figures(state: State) -> list[meridian.Figure]:
    """The data role's figures, in its order (`meridian.roles.data`); Tradier
    reports none of its own."""
    read = connection_read(state)
    word = status(read)["label"]
    connection: Any = word
    if word == "Not answering":
        connection = meridian.Figure("", word, state="error", why=read.detail[:200])
    elif word == "Answering" and read.last_error:
        connection = meridian.Figure("", word, state="warn", why=read.last_error[:200])
    served = datasets_read(state).served
    ok = [s for s in served if s.entitled_at_vendor.startswith("Yes")]
    entitled: Any = None
    if read.mode != "No key":
        missing = [s.key for s in served if s not in ok]
        entitled = meridian.Figure(
            "",
            f"{len(ok)} of {len(served)} datasets",
            state="warn" if missing else None,
            why=("Not served: " + ", ".join(missing)) if missing else "",
        )
    stream = read.stream
    if read.sessions is None:
        streaming: Any = "Does not stream"
    elif stream is None or stream.state in ("idle", ""):
        streaming = "Off"
    elif stream.state == "streaming":
        streaming = f"{stream.subscribed} listings"
    else:
        streaming = meridian.Figure(
            "", stream.state.capitalize(), state="warn", why=stream.last_error[:200]
        )
    last = max((s.last_recorded for s in served), default="")
    used = state.tradier.usage if state.tradier is not None else Usage()
    now = state.tradier.clock_ns() if state.tradier is not None else 0
    spent = used.last_minute(now) if now else 0
    return data.figures(
        connection=connection,
        entitled_at_vendor=entitled,
        stream=streaming,
        last_recorded=dt.datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None,
        rate_use=meridian.Figure(
            "",
            f"{spent} of {LIMIT_PER_MINUTE} a minute",
            state="warn" if spent * 5 >= LIMIT_PER_MINUTE * 4 else None,
            why=f"{used.rate_limited} answered 429 and waited out" if used.rate_limited else "",
        ),
    )


def environment() -> str:
    """The environment as Connection's Trading says it: Paper (the developer
    sandbox, simulated money) or Live, or sample data."""
    config = current().config
    if config.sample_data:
        return "Sample data: a simulated brokerage, nothing sent to Tradier"
    return SAID[config.environment]


async def connection_record(request: meridian.Request) -> ConnectionRead:
    """Connection's record, the data role's with Tradier's fields; the SDK
    adds connectivity's Trading."""
    return connection_read(_state)


pages.environment.globals["connection_status"] = lambda read: status(read)

connectivity.connection_pages(
    pages,
    current,
    connection_record,
    venue=TITLE,
    credentials=lambda: [data.Credential("Access token", current().config.token_set)],
    environment=environment,
    environment_setting=lambda: current().config.environment_setting,
    updates=lambda: current().polled,
    latency=lambda: current().latency,
    template="connection.html",
)


@pages.page(
    DATASETS,
    "Datasets",
    levels="admin",
    roles="data",
    answers=DatasetsRead,
    name="read_datasets",
    description=(
        "The datasets the plugin serves the lake, as every data plugin's Datasets answers "
        "them: each one as its catalogue declares it, whether a deployment admin has "
        "licensed it, whether Tradier serves the token it, and what it recorded and "
        "declined since the plugin started; the standing wants it keeps current; whether "
        "it may read an instrument's record. Then Tradier's own: the feed and host each "
        "dataset reads, the listings known and streamed, and that a restart's gap is not "
        "backfilled. No prices, trades or quotes."
    ),
)
async def datasets(request: meridian.Request) -> meridian.Response:
    read = datasets_read(_state)
    # A tool answers every want; a browser draws the latest few, and says
    # how many there are.
    drawn = read if request.tool_name else replace(read, wants=read.wants[:SHOWN_WANTS])
    return pages.answer("datasets.html", drawn, wants=len(read.wants))


# Custody's pages, then Raw records, for custody and connectivity (the SDK's,
# 0.32.0).
from . import custody_pages  # noqa: E402,F401,I001

connectivity.raw_records_page(
    pages,
    current,
    kinds=KINDS,
    why=(
        "Tradier's answers as received, any JSON it sent, which no typed record holds; an "
        "agent reads what they came to with read_statements and read_account_activities, "
        "and in the book's placements and executions, each naming its raw record"
    ),
)


def serve(plugin: meridian.Plugin, state: State, port: int) -> Any:
    """Serve the pages on loopback beside the sidecar, reading `state`."""
    use(state)
    return pages.serve(plugin, port)
