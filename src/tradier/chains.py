"""Tradier's option chains in the lake (from 0.13.0; contract v28: meridian-design
spec/the-options-and-event-contracts-sample-plugin T1, rulings 145 to 152,
561, 567 and 660).

**Two datasets, one per timeliness** (ruling 660, after 551): `options`,
real time for an account holder, and `options_delayed`, Tradier's developer
sandbox, delayed 15 minutes; each holds a chain's series
(`meridian.v1.ListedSeries`), its quotes and its statistics
(`meridian.v1.Statistic`), licensed and entitled apart from the equity
datasets (OPRA's data, not the equity SIPs'). The chain is recorded into
whichever the environment provides, as the live kind is (lake.py); a want
of the other is declined, not covered (0.13.1: DeclineWant takes no
`not_entitled`, lake.py).

**Never minted, never resolved** (ruling 561, W10.4): every row names the
underlying's record as its subject and the series by its OCC OSI symbol
(`occ_osi`, W1.26) as its series key, through the SDK's helpers
(`meridian.roles.chains`): each series' terms as the platform's
listed-option template's fields (`TPL-listed-option`, version 1; ruling
617), its best bid and offer as a quote, its open interest and volume as
statistics. A series gets an `INS-` record only when a reader asks for one
(RequestSeriesRecords, W6.37), which is never this plugin's.

**What Tradier states, and what it does not:**
- The series: `/markets/options/chains`, one expiration a call, no greeks
  (the engine computes its own, ruling 565); the expirations from
  `/markets/options/expirations`, every root's. An option on a stock or an
  ETF is American and physically settled; Tradier's chain says neither, so
  an index's chain (European, cash-settled: its quote's `type` is `index`)
  is declined, not covered, rather than recorded with terms it does not
  state. A standard contract delivers 100 shares of its underlying; an
  adjusted one (a root other than its underlying's) states no deliverable
  in the chain, so none is recorded. No settlement time is stated.
- A quote's sizes are in contracts, as Tradier states an option's; a side
  with no price is empty.
- Open interest is the clearing house's count at the previous session's
  end, so it is dated the market day before the day it is read, by
  Tradier's own market calendar (`/markets/calendar`); volume is the
  session's, dated today once today's session has opened, and not recorded
  before (Tradier's chain then still states the last session's). A value
  Tradier leaves `null` records no row, never a zero (W10.4).
- OCC's own files are not read (ruling 150: OCC's terms).

**Bounded by what readers ask** (ruling 152; contract v28's wants): a want
of the chain's series, quotes or statistics names an underlying, never an
expiration, so every expiration Tradier lists for it is read: a want's
whole chain once, a standing want's kept current, each expiration at most
once a minute. Chains spend at most `CALLS_PER_MINUTE` of the client's 60
calls a minute, the expirations a reader waits for first, then the longest
unread, nearest expiration first; past that, a chain is read less often,
never past Tradier's limit. Only what changed is sent again.

**An unchanged quote is not recorded again** (0.13.2, ruling 770): a
series' quote is sent when its bid, offer or either size changed, never for
Tradier's quote time alone moving, so the lake keeps one row for each
change -- under the row key of the time it changed, which an unchanged
quote never moves -- and a busy underlying's chain is not a new row a
series a minute. Freshness is the dataset's liveness instead (contract
v27, W10.4; ruling 418): each pass that read a chain records it once, for
the dataset's consolidated view, which confirms every quote in force.

**The edge** (contract v28): a quote recorded for a standing want is judged
by the SDK's quality checks and has its feed delay recorded (lake.py), each
series judged apart, since the checks remember a subject's last row and
every series of a chain names its underlying.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from meridian.errors import MeridianError
from meridian.operations import Money, Quote, SourceTime
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import chains as helpers
from meridian.roles.data.listings import Counts

from .convert import NEW_YORK, ChainOption, new_york_date

log = logging.getLogger("tradier.chains")

#: The chain's datasets (ruling 660): real time, and the sandbox's.
OPTIONS = "options"
OPTIONS_DELAYED = "options_delayed"
SERIES = "meridian.v1.ListedSeries"
STATISTIC = "meridian.v1.Statistic"
QUOTE = "meridian.v1.Quote"
#: What the chain's datasets hold.
DATA_TYPES = (SERIES, STATISTIC, QUOTE)
#: How often a standing want's expiration is read again, at most (152).
CADENCE_SECONDS = 60
#: The chain calls a minute, at most: half the client's 60.
CALLS_PER_MINUTE = 30
#: The platform's listed-option template (ruling 617) and its version.
TEMPLATE_ID = "TPL-listed-option"
TEMPLATE_VERSION = "1"
CURRENCY = "USD"
AMERICAN = "EXERCISE_STYLE_AMERICAN"
PHYSICAL = "SETTLEMENT_METHOD_PHYSICAL"
#: What one standard contract delivers: 100 shares of its underlying.
STANDARD_SHARES = 100
#: Tradier's listing types whose options are American and physically settled.
UNDERLYING_KINDS = frozenset({"stock", "etf"})
#: When a session opens, New York: volume is today's from then.
SESSION_OPENS = dt.time(9, 30)
#: How far back a market day is looked for.
LOOK_BACK_DAYS = 14
#: How many rows' last sendings are remembered, to send only what changed.
REMEMBERED = 200_000
BATCH = 500
NS = 1_000_000_000
MINUTE_NS = 60 * NS


@dataclass
class Underlying:
    """One underlying whose chain is wanted: its listing, the expirations
    Tradier lists for it today, when each was last read, the wants still
    waiting on an expiration, and the standing wants keeping it current."""

    subject: str
    symbol: str
    expirations: list[dt.date] = field(default_factory=list)
    listed_on: dt.date | None = None
    read_at: dict[dt.date, int] = field(default_factory=dict)
    pending: dict[str, set[dt.date]] = field(default_factory=dict)
    standing: set[str] = field(default_factory=set)

    @property
    def wanted(self) -> bool:
        return bool(self.pending or self.standing)


class Chains:
    """The chains wanted of `lake` (lake.Lake), read from its source and
    recorded."""

    def __init__(self, lake: Any) -> None:
        self.lake = lake
        self.underlyings: dict[str, Underlying] = {}
        #: Tradier's type of each listing asked about (`stock`, `etf`, ...).
        self.kinds: dict[str, str] = {}
        #: Each month's market days, as Tradier's calendar states them.
        self.days: dict[tuple[int, int], dict[dt.date, bool]] = {}
        #: When each chain call of the last minute was made.
        self.calls: deque[int] = deque()
        #: Each row's last sending, by (data type, dataset, row key).
        self.sent: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        #: Chains read since start, and the series in the last.
        self.read_count = 0
        #: When a chain was last read from Tradier, and the liveness last
        #: recorded for it (0.13.2).
        self.alive_ns = 0
        self.liveness_ns = 0

    @property
    def counts(self) -> Counts:
        counts: Counts = self.lake.counts[OPTIONS]
        return counts

    # ── Names ────────────────────────────────────────────────────────────

    def key(self) -> str:
        """The chain's dataset the environment provides now."""
        return OPTIONS_DELAYED if self.lake.delayed else OPTIONS

    def dataset(self) -> str:
        return str(self.lake.named(self.key()))

    def now(self) -> int:
        return int(self.lake.clock_ns())

    # ── Wants (W10.7) ────────────────────────────────────────────────────

    async def on_want(self, want: Any) -> None:
        """A want of a chain's series, quotes or statistics: each subject an
        underlying, its whole chain read (and kept current, standing), or
        declined with why."""
        subjects = [s.entity_id for s in want.subjects]
        self.counts.wants += 1
        if want.dataset != self.dataset():
            await self.decline(want.want_id, subjects, "not_covered", settled=False)
            return
        if want.data_type not in DATA_TYPES:
            await self.decline(want.want_id, subjects, "not_covered", settled=False)
            return
        if self.lake.source is None:
            await self.decline(want.want_id, subjects, "source_silent", settled=False)
            return
        if want.data_type == STATISTIC and want.business_date:
            stated = await self.dates()
            if want.business_date not in stated:
                # Tradier's chain states today's figures alone.
                await self.decline(want.want_id, subjects, "beyond_history", day=want.business_date)
                return
        declined: dict[str, list[str]] = {}
        for subject in subjects:
            held = await self.underlying(subject)
            if isinstance(held, str):
                declined.setdefault(held, []).append(subject)
                continue
            held.pending[want.want_id] = set(held.expirations)
            if want.standing:
                held.standing.add(want.want_id)
        for reason, refused in sorted(declined.items()):
            await self.decline(want.want_id, refused, reason, settled=reason != "source_silent")
        await self.refresh()

    def withdraw(self, want_id: str) -> None:
        """A standing want withdrawn: its chains no longer kept current for it."""
        for held in list(self.underlyings.values()):
            held.standing.discard(want_id)
            held.pending.pop(want_id, None)
            self._forget(held)

    def reset(self) -> None:
        """The environment changed: every chain was wanted of the other
        dataset, and the lake asks again of this one."""
        self.underlyings.clear()

    async def decline(
        self,
        want_id: str,
        subjects: Sequence[str],
        reason: str,
        *,
        day: str = "",
        settled: bool = True,
    ) -> None:
        await self.lake._decline(OPTIONS, want_id, subjects, reason, day=day, settled=settled)

    async def underlying(self, subject: str) -> Underlying | str:
        """The underlying a subject is, its expirations listed today; or why
        its chain is not read: no listing (`not_covered`), not a stock or an
        ETF (`not_covered`), no option listed, or Tradier not answering
        (`source_silent`)."""
        lake = self.lake
        source = lake.source
        symbol = await lake.symbol_of(subject)
        if symbol is None or source is None:
            return "not_covered" if symbol is None else "source_silent"
        kind = self.kinds.get(symbol)
        if kind is None:
            said = await lake._fetch(lambda: source.kind(symbol))
            if said is None:
                return "source_silent"
            kind = self.kinds[symbol] = str(said)
        if kind not in UNDERLYING_KINDS:
            return "not_covered"
        held = self.underlyings.get(subject) or Underlying(subject, symbol)
        today = new_york_date(self.now())
        if held.listed_on != today:
            listed = await lake._fetch(lambda: source.expirations(symbol))
            if listed is None:
                return "source_silent"
            held.expirations = [day for day in listed if day >= today]
            held.listed_on = today
            for day in list(held.read_at):
                if day not in held.expirations:
                    del held.read_at[day]
            for left in held.pending.values():
                left.intersection_update(held.expirations)
        if not held.expirations:
            return "not_covered"
        self.underlyings[subject] = held
        return held

    def _forget(self, held: Underlying) -> None:
        for want_id in [w for w, left in held.pending.items() if not left]:
            del held.pending[want_id]
        if not held.wanted:
            self.underlyings.pop(held.subject, None)

    # ── The timetable ────────────────────────────────────────────────────

    def budget(self) -> int:
        """The chain calls still allowed this minute."""
        now = self.now()
        while self.calls and self.calls[0] <= now - MINUTE_NS:
            self.calls.popleft()
        return CALLS_PER_MINUTE - len(self.calls)

    async def refresh(self) -> int:
        """Read what is due within the minute's budget: the expirations a
        want waits for first, then a standing want's unread longest, nearest
        expiration first. How many chains were read."""
        if self.lake.source is None:
            return 0
        today = new_york_date(self.now())
        for held in list(self.underlyings.values()):
            if held.standing and held.listed_on != today:
                found = await self.underlying(held.subject)
                if isinstance(found, str):
                    log.warning("%s's expirations not listed today: %s", held.symbol, found)
        now = self.now()
        due: list[tuple[int, int, dt.date, str]] = []
        for held in self.underlyings.values():
            for expiry in held.expirations:
                waiting = any(expiry in left for left in held.pending.values())
                last = held.read_at.get(expiry, 0)
                stale = bool(held.standing) and now - last >= CADENCE_SECONDS * NS
                if waiting or stale:
                    due.append((0 if waiting else 1, last, expiry, held.subject))
        read = 0
        for _, _, expiry, subject in sorted(due)[: max(self.budget(), 0)]:
            wanted = self.underlyings.get(subject)
            if wanted is not None:
                await self.read(wanted, expiry)
                read += 1
        await self.alive()
        return read

    async def alive(self) -> bool:
        """The chain's sign of life since the last (0.13.2; contract v27,
        W10.4, ruling 418): the chain dataset's liveness, recorded once a
        pass for its consolidated view (no venue), which confirms every quote
        in force, an unchanged one never sent again. Whether it was
        recorded; a refusal is said, never raised."""
        if self.alive_ns <= self.liveness_ns:
            return False
        self.liveness_ns = self.alive_ns
        try:
            await self.lake.plugin.record_liveness(
                liveness=[
                    ops.DatasetLiveness(
                        dataset=self.dataset(), venue_id="", alive_at_ns=self.alive_ns
                    )
                ]
            )
        except (MeridianError, ValueError) as refused:
            log.warning("the chain's liveness not recorded: %s", refused)
            return False
        return True

    async def read(self, held: Underlying, expiry: dt.date) -> None:
        """One expiration's chain read and recorded, against the want waiting
        for it, else the standing want keeping it current."""
        source = self.lake.source
        self.calls.append(self.now())
        listed = await self.lake._fetch(lambda: source.chain(held.symbol, expiry))
        waiting = sorted(w for w, left in held.pending.items() if expiry in left)
        held.read_at[expiry] = self.now()
        for want_id in waiting:
            held.pending[want_id].discard(expiry)
        if listed is None:
            for want_id in waiting:
                await self.decline(want_id, [held.subject], "source_silent", settled=False)
        else:
            self.read_count += 1
            self.alive_ns = held.read_at[expiry]
            want_id = waiting[0] if waiting else min(held.standing, default="")
            await self.record(held, listed, want_id)
        self._forget(held)

    # ── Dates ────────────────────────────────────────────────────────────

    async def is_open(self, day: dt.date) -> bool | None:
        """Whether a day is a market day, by Tradier's calendar; None where
        the calendar was not read."""
        month = self.days.get((day.year, day.month))
        if month is None:
            source = self.lake.source
            read = await self.lake._fetch(lambda: source.market_days(day.year, day.month))
            if read is None:
                return None
            month = self.days[(day.year, day.month)] = dict(read)
        return month.get(day)

    async def dates(self) -> dict[str, str]:
        """The trading date each statistic read now is for, by kind: open
        interest the market day before today's, volume today's once its
        session has opened; a kind with no date is not recorded."""
        now = self.now()
        moment = dt.datetime.fromtimestamp(now / NS, NEW_YORK)
        today = moment.date()
        out: dict[str, str] = {}
        for back in range(1, LOOK_BACK_DAYS + 1):
            day = today - dt.timedelta(days=back)
            held = await self.is_open(day)
            if held is None:
                break
            if held:
                out["open_interest"] = day.isoformat()
                break
        if moment.time() >= SESSION_OPENS and await self.is_open(today):
            out["volume"] = today.isoformat()
        return out

    # ── Recording (W10.4) ────────────────────────────────────────────────

    def _changed(self, data_type: str, dataset: str, row_key: str, said: str) -> bool:
        """Whether a row says something other than its last sending."""
        mark = (data_type, dataset, row_key)
        if self.sent.get(mark) == said:
            return False
        self.sent[mark] = said
        self.sent.move_to_end(mark)
        while len(self.sent) > REMEMBERED:
            self.sent.popitem(last=False)
        return True

    async def record(self, held: Underlying, listed: Sequence[ChainOption], want_id: str) -> None:
        """A chain's series, quotes and statistics, each sent only where it
        changed: its series' terms, its quotes judged at the edge."""
        dataset = self.dataset()
        now = self.now()
        dates = await self.dates()
        series: list[Any] = []
        quotes: list[Any] = []
        statistics: list[Any] = []
        for option in listed:
            self.counts.unconverted += len(option.unconverted)
            if not option.osi or option.contract_size is None:
                continue
            raw = self.lake.plugin.raw_record(option.raw_key[:256])
            key = helpers.osi_key(option.osi)
            try:
                row = helpers.option_series(
                    held.subject,
                    option.osi,
                    template_id=TEMPLATE_ID,
                    template_version=TEMPLATE_VERSION,
                    dataset=dataset,
                    currency=CURRENCY,
                    exercise_style=AMERICAN,
                    settlement_method=PHYSICAL,
                    contract_multiplier=option.contract_size,
                    deliverable=[(held.subject, STANDARD_SHARES)] if option.standard else (),
                    valid_from_ns=now,
                    raw=raw,
                )
            except ValueError:
                self.counts.unconverted += 1
                continue
            terms = repr([(f.path, f.value) for f in row.fields])
            if self._changed(SERIES, dataset, option.osi, terms):
                series.append(row)
            quote = self.quote(held.subject, option, key, dataset, raw)
            if quote is not None:
                assert quote.meta is not None
                # Its prices and sizes, never Tradier's quote time alone
                # (ruling 770): unchanged, it is not recorded again.
                said = repr((quote.bid, quote.ask, quote.bid_quantity, quote.ask_quantity))
                if self._changed(QUOTE, dataset, option.osi, said):
                    quotes.append(quote)
            for kind, value in (("open_interest", option.open_interest), ("volume", option.volume)):
                day = dates.get(kind)
                if value is None or not day:
                    continue
                stat = helpers.statistic(
                    held.subject, key, kind, value, day, dataset=dataset, valid_from_ns=now, raw=raw
                )
                assert stat.meta is not None
                if self._changed(STATISTIC, dataset, stat.meta.row_key, str(value)):
                    statistics.append(stat)
        if series:
            await self.send("series", series, want_id)
        if quotes:
            await self.send("quotes", self.lake.at_the_edge(self.key(), quotes, want_id), want_id)
        if statistics:
            await self.send("statistics", statistics, want_id)

    def quote(
        self, subject: str, option: ChainOption, key: Any, dataset: str, raw: Any
    ) -> Quote | None:
        """A series' best bid and offer under the underlying, keyed by the
        series; none where Tradier states no side or no time."""
        if option.at_ns is None or (option.bid is None and option.ask is None):
            return None
        return Quote(
            meta=helpers.series_meta(
                subject,
                key,
                row_key=f"{option.osi}:q:{option.at_ns}",
                dataset=dataset,
                valid_from_ns=option.at_ns,
                raw=raw,
                source_times=[SourceTime(kind="event", at_ns=option.at_ns)],
            ),
            bid=None if option.bid is None else Money(option.bid, CURRENCY),
            ask=None if option.ask is None else Money(option.ask, CURRENCY),
            bid_quantity=option.bid_size if option.bid is not None else None,
            ask_quantity=option.ask_size if option.ask is not None else None,
        )

    async def send(self, kind: str, rows: Sequence[Any], want_id: str) -> None:
        """Rows in the lake's batches, against the want, counted."""
        call = getattr(self.lake.plugin, f"record_{kind}")
        counts = self.counts
        for start in range(0, len(rows), BATCH):
            done = await call(**{kind: list(rows[start : start + BATCH])}, want_id=want_id)
            counts.recorded += int(getattr(done, "recorded", 0))
            counts.restated += int(getattr(done, "restated", 0))
            counts.unchanged += int(getattr(done, "unchanged", 0))
            counts.last_recorded_at_ns = self.now()
            if want_id:
                held = self.lake.by_want.setdefault(want_id, [0, 0])
                held[0] += int(getattr(done, "recorded", 0)) + int(getattr(done, "restated", 0))
