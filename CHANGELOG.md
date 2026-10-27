# Changelog

## 0.13.2

- **The option chains' datasets name their calendar** (ruling 768):
  `options` and `options_delayed` declare `calendar_id`
  `CAL-01M4VF0F4XGP3RATCCSKDPZSBP`, the platform's US equity and options
  holiday calendar `daily` already declares. Their rows' closed days are
  known to the lake, and the analytics engine places a series whose quote
  names no venue by the dataset's declaration (core's ruling 767).
- **An unchanged chain quote is not recorded again** (ruling 770). A
  series' quote was sent whenever Tradier's quote time moved, each a new row
  keyed by that time, though its bid, offer and sizes were the same: about
  82,000 rows of one underlying's chain in two hours on a development
  deployment, every one of which the lake's latest read then had to pass.
  It is now sent only when its prices or sizes change, so an unchanged quote
  keeps the row and row key it was first recorded under.
- **The chain's datasets record their liveness** (contract v27, W10.4;
  ruling 418): once a pass that read a chain, for the dataset's
  consolidated view, so a reader still knows the quotes in force are
  current when none changed.

## 0.13.1

- **A decline names a reason the lake takes.** A want of the other
  timeliness -- `live` on the sandbox or `live_delayed` on Live, and
  likewise `options` / `options_delayed` -- is declined `not_covered`
  (the environment does not serve it), where 0.12.0 and 0.13.0 declined it
  `not_entitled`. DeclineWant takes `not_covered`, `source_silent` or
  `beyond_history` alone, so the lake refused every such decline; the
  refusal, raised in the want's handler, ended the SDK's delivery stream
  (logged as "a read to catch up failed ... trying again"), and the wants
  delivered behind it in that stream were never heard. On a deployment
  where a reader is entitled to `live` while Tradier runs on its sandbox,
  that happened at every read.
- The tests' `Recorder` refuses a decline the lake refuses
  (tests/conftest.py), since the SDK's answers any reason.

## 0.13.0

On open-meridian 0.33.1, contract v28 (meridian-design `plans/the-v28-build.md`;
spec/the-options-and-event-contracts-sample-plugin T1), on core v28's
harness.

- **Option chains** (rulings 145 to 152, 561, 567; datasets ruled 660):
  two new datasets, `options` (Live's, real time) and `options_delayed`
  (the sandbox's, a declared 15-minute delay), one per timeliness as the
  live kind, licensed and entitled apart from `live` (OPRA's data, not the
  equity SIPs'), served and not kept by default as `live` is. Each holds an
  underlying's series (`meridian.v1.ListedSeries`, the platform's
  `TPL-listed-option` template, version 1), its quotes and its statistics
  (`meridian.v1.Statistic`), every row under the underlying's record and
  keyed by the series' OCC OSI symbol (`occ_osi`), never resolved or
  minted (`meridian.roles.chains`; chains.py).
  - Read from Tradier's `/markets/options/expirations` (every root) and
    `/markets/options/chains` (one expiration a call, no greeks: the engine
    computes its own); quotes' sizes in contracts; open interest dated the
    previous market day by `/markets/calendar`, volume today's once the
    session opens; a value Tradier leaves `null` records no row. A standard
    contract delivers 100 shares; an adjusted root states no deliverable.
    An index's chain (European, cash-settled, which Tradier does not state)
    is declined, not covered. OCC's files are not read (150).
  - Bounded by wants (152): a want of an underlying's series, quotes or
    statistics reads every expiration Tradier lists; a standing want keeps
    each at most once a minute, within 30 chain calls a minute (half the
    client's 60), only changes sent again.
  - Datasets lists the chains' standing wants.
- **The edge** (contract v28, rulings 424 and 518): each live price, quote
  and trade, and each chain quote, recorded unasked or for a standing want
  has its feed delay recorded and is judged by the SDK's quality checks;
  the plugin's `roles.Latency` -- the brokerage session's round trip too --
  is reported every 10 seconds (`ReportLatency`). **Temporary**: the SDK's
  listings feed does neither in 0.33.1, so `Lake.at_the_edge` does it with
  the SDK's own `Latency.aged` and `quality.EdgeChecks` until the SDK's
  listings feed takes it over (queued as SDK 0.33.2). A chain's quotes are
  judged series by series, since the checks remember a subject's last row
  and every series names its underlying.
- **The suites' v28 cases:** data -- the three option-chain cases,
  `reports-its-feed-delay` and `a-crossed-quote-is-recorded-invalid`
  presented; the filings slice's not (Tradier publishes none), nor the
  duplicate and gap cases (Tradier numbers no quote). Connectivity --
  `reports-a-sessions-round-trip` presented; `reports-an-expiry` and
  `reports-a-package-fill` not (it places single-leg equity orders).
  Custody -- `reports-an-assignment` not (Tradier's history names no
  option event).
- **`meridian plugin migrate`** (to_0_33_0): e2e/reader.py's SubjectRefs
  are `meridian.SubjectRef` (ruling 599).
- **The pins:** open-meridian 0.33.1 and plugin-python:0.33.1 by tag and
  digest; core v28's runtime and harness at `8def82a` (chart 0.1.313) by
  digest; `meridian` stays 0.1.52 in check.yaml.
- The README's "Not released" line is gone (549).

## 0.12.0

On open-meridian 0.32.3, contract 27.

- **One Connection for market data and orders** (ruling 457): Connection is
  the SDK's `connectivity.connection_pages`, connectivity's sections
  (Environment, Accounts, Placements, and Sessions once measured) drawn
  after the data role's; "Enable trading" is made on it (`/enable-trading`).
  `read_connection` answers them as `trading`. **The Trading page and
  `read_trading` are gone**; `enable_trading` and `check_enable_trading`
  keep their names. No tab code of the plugin's own.
- **No copied code between plugins** (rulings 202 and 457): `trading_page.py`
  and the plugin's own `trading.html`, `account_links.html` and
  `raw_records.html` are deleted. Raw records is the SDK's
  `raw_records_page`, and Account links the role's own template. The
  plugin's `TradingRead` is gone: the SDK's carries the badge.
- **Placement types** (contract v27, W11.20): the adapter declares DMA alone
  (`placement_types`); Tradier takes no request for quote, so an RFQ
  placement is rejected `unsupported` with nothing sent, and the catalogue
  lists DMA.
- **The trader's fixes from SDK 0.32.0:** a rejected replace's raw record
  names the venue account (tested); an order placed in Tradier's own app is
  resolved by every identifier Tradier states -- its symbol, and no
  currency, which Tradier never states -- its fills priced in its
  instrument's currency (tested). Tradier's durations take no expiry, so a
  good-till-date order stays `unsupported` (tested).
- **Latency:** the Trader records the brokerage API session's round trip,
  order acknowledgement and fill delay (`roles.Latency`), shown under
  Sessions; not reported until contract v28 (ruling 515). The suites' two
  `latency` cases are not presented, "core receives ReportLatency from
  contract v28, ruling 515" (ruling 518). The stream's liveness is
  presented (`records-a-datasets-liveness`): open-meridian 0.32.3's
  listings feed records it for any message heard, no code of the plugin's.
- **One dataset per timeliness** (ruling 551, after 382): a new dataset,
  `live_delayed`, the live kind from the developer sandbox, declaring its
  15-minute delay (`declared_delay_ns`); `live` is Live's, real time. The
  live kind is recorded into whichever the environment provides, and a want
  of the other is declined not entitled; on a change of environment the
  live kind's standing wants are let go, for the lake to ask again. Daily
  closes are end of day in both, and the sandbox streams no trades, so
  `daily` and `trades` stay one each. **On upgrading:** license and entitle
  `live_delayed` on Data sources; rows the sandbox recorded under `live`
  before 0.12.0 stay as they were (`live` is served, not kept), and none
  is recorded there again while Environment is Sandbox.
- **The suites' v27 cases:** the seven rates cases (Tradier publishes no
  rates) and an RFQ dealer's quote (it takes no RFQ), not presented with why.
- **Datasets** fits 1280x800: its line on the terms shortened.
- **The pins**: open-meridian 0.32.3 and plugin-python:0.32.3 by digest;
  the core runtime and harness a5da59a by digest (chart 0.1.310); `meridian`
  0.1.52. The licence's new attribution fields are not set: core v27 refuses
  a catalogue carrying them.

## 0.11.1

- **Custody's pages on the SDK** (ruling 213): Account links, Statements and
  History are `meridian.roles.custody.account_pages(...)`, declared by the
  SDK; `custody_pages.py` keeps only what Tradier's sync holds (its
  `Source`: the accounts the credential reaches, each one's statement and
  activities, its custodian and account type). Their paths, tools, records
  and words are as they were; the tools' descriptions are the SDK's. The
  plugin's own `LinkAsked` and its unchanged Statements and History
  templates are gone (the role's own are drawn); Account links keeps its
  template, for its notice and its plain form per account.
- **The pins**: `meridian` 0.1.50, which reads the pages the SDK declares in
  `role-pages`; open-meridian 0.31.1 and plugin-python:0.31.1 by digest
  (`sha256:67781f14...a3535b39`): a saved value no longer a choice arrives
  unset in `Settings.refused`, never raised.

## 0.11.0

On open-meridian 0.31.0, contract 26.

- **Environment** is declared with the SDK's `meridian.environment()`: its
  name, label, values (`live`, `sandbox`) and default (Sandbox) as before,
  so a saved value carries over. Its description says agents may place
  orders only on Sandbox.
- **The listings in the lake on the SDK** (ruling 213): `lake.py`, about 980
  lines kept nearly line for line with Alpaca's, is now a subclass of
  open-meridian 0.31.0's `meridian.roles.data.listings.Feed` keeping only
  what is Tradier's: its source's name, how far its history reaches, its
  time and sales prints' attributes and sequence numbers. Wants, standing
  wants, recording, the restart watermark and the counts are the SDK's; what
  is recorded is unchanged, and the data suite passes as before.
- **The custody slice waits for meridian 0.1.50.** The Account links,
  Statements and History pages stay in `custody_pages.py`: the SDK's
  `custody.account_pages` declares them inside the SDK, which meridian
  0.1.49's `role-pages` rule does not recognise yet, so `plugin check
  --verified` would fail. They move once 0.1.50 recognises it.
- **The session's reported environment** (contract v26, the agents'
  demo-only guard, spec/the-contract-gaps-v26-and-v27-close G1): the venue
  adapter reads the environment its session reached from the host it calls,
  `sandbox.tradier.com` `sandbox` and `api.tradier.com` `live`
  (`meridian.reached_environment`), and the SDK's Trader publishes it on the
  venue catalogue. The simulated brokerage reports `sandbox`. **Trading**
  shows the connection's badge, Demo, Live or Live (environment not
  confirmed) (`meridian.connection_badge`), and `read_trading` answers
  `reached_environment` and `badge` beside the role's fields.
- **The data suite's v26 cases.** `queries-the-lake-within-bounds` passes on
  the SDK's producer (`lake_query`); `reports-an-event-group` and
  `reports-a-flag-the-venue-does-not-state` are not presented, with why
  (Tradier's stock data lists no event contract). The event group heard and
  read is the SDK's.
- **The pins**: open-meridian 0.31.0, as released on PyPI, and
  plugin-python:0.31.0 by tag and digest (`sha256:e041f83c...24cf5d2`); core
  v26's runtime and harness (17a13a2, merged as 648e25f, chart 0.1.308), by
  tag and digest; `meridian` 0.1.49, the first CLI holding contract v26's
  suites.
- **Tests**: the catalogue's environment, the environment read from each
  host, the badge on Trading and in its tool, and the data suite's new
  cases, on the simulated brokerage and recorded exchanges; nothing reaches
  Tradier.

## 0.10.0 (2026-10-19)

On open-meridian 0.30.0, contract 25 unchanged: the connectivity role's work
is the SDK's (sdk-contract/the-sdk-carries-each-roles-common-logic, ruled
2026-10-13; ruling 206).

- **Trading on the SDK's Trader** (`meridian.roles.connectivity`): the
  plugin's `trading.py` (about 1,800 lines, kept nearly line for line with
  Alpaca's) is gone. Placements heard and sent once, outcomes, fills
  into the book, busts, cancels and replaces, pauses and stops, the catalogue
  and venue-originated fills are the SDK's `Trader`, handed this plugin's
  adapter (`venue.py`) and the listing market's zone (`custody.MARKET_ZONE`,
  America/New_York). Tradier's client (`broker.py`) and its conversion stay
  the plugin's, as transport.
- **The Trading page** answers the SDK's `trading_read`, drawn by
  `meridian/roles/connectivity/trading.html`; its records and
  `templates/trading.html` are gone. Its tools and rows are as they were;
  the token's row and its next step say the role's words, "Key" and "No
  key yet: Enter it in Settings".
- **Its tests** run the plugin's adapter over the simulated brokerage on the
  SDK's rig (`meridian.roles.connectivity.testing.Rig`); simulated only,
  nothing reaches Tradier.
- **The pins**: open-meridian 0.30.0, as released on PyPI, and
  plugin-python:0.30.0 by tag and digest
  (`sha256:a238c6d9...3473ed6`) in the Dockerfile, which `make image` now
  builds on as an upload does; core v25's runtime and harness (abf028f) and
  `meridian` 0.1.46 as before.

## 0.9.0 (unreleased)

On open-meridian 0.29.0, contract 25 (sdk-contract/plugins-are-shared-and-
documented-contract), the v25 build's step 8; past contract 24, which this
plugin skipped on the v23 pins.

- **The whole declaration** (`declaration.py`): its settings, its interface
  -- Connection, Datasets, Account links, Statements, History, Trading and
  Raw records, with the tools their routes make -- on a port fixed at 8000,
  that it reads external accounts, its catalogue and storage, and its
  documentation. `__main__` connects with the declaration alone; so do the
  e2e's desk and reader. The parts the pages import moved to `declared.py`.
- **The daily dataset names its calendar** (contract 24's `calendar_id`,
  the v24 plan's O10): the platform's US equity venues calendar,
  `CAL-01M4VF0F4XGP3RATCCSKDPZSBP`, so the lake flags a close dated on a
  closed day.
- **Its documentation** (`docs/`): the drafts revised for all three roles --
  the account at Tradier, its orders, Account links, Statements, History,
  Trading and Raw records added; the data and custody roles' pages linked;
  "a later version" for the account removed.
- **The suites**: custody's v24 case, a holding named by its symbol alone,
  recorded unresolved; connectivity's give-up case not presented (no trade
  is given up at Tradier); the two cases every suite holds answered by the SDK.
- **The pins**: open-meridian 0.29.0 and plugin-python:0.29.0, core v25's
  runtime and harness, and `meridian` 0.1.46 in `check.yaml`, each as released
  (core abf028f, chart 0.1.306, by tag and digest).
- **`make e2e`** takes the harness down with `--profile runner`.

## 0.8.0 (unreleased)

0.7.1 was never released: its fix ships as 0.8.0 (the v24 plan's O5), on
the v23 pins (open-meridian 0.27.0, core 50d6f0a's runtime and harness),
since nothing here needs contract 24 (the product owner, 2026-10-14). The
daily dataset's calendar waits for v25: open-meridian 0.28.0 is the first SDK
whose DatasetDeclaration carries `calendar_id`.

- **Live is a person's choice.** `environment` defaults to `sandbox`, not
  `live`: an upgrade, or an Environment never saved, no longer turns the
  plugin Live. 0.7.0 came up on Live over a deployment that had saved
  0.2.1's `sandbox` switch and sent its sandbox token to api.tradier.com,
  which refused it (401). Its description says Live is chosen by a person
  (the product owner, 2026-10-14).
- 0.2.1's `sandbox` is declared again, as a developer's setting, "Sandbox
  (the old way)", described as replaced by Environment and read only while
  Environment is unset: on, Sandbox; off, Live. A value saved under it now
  reaches the plugin, which reads it as SnapTrade reads its 0.1.0
  `snaptrade_personal_key`; once Environment is saved it is not read. The
  plugin has no storage of settings to backfill: settings are core's, and a
  plugin sets none.
- Nothing else changes. Tests: an unset environment is the sandbox, Live
  only once chosen, and the old switch honoured while Environment is unset
  and ignored once it is saved; `make e2e` reads the default, Sandbox, on
  `read_connection`.

## 0.7.0 (unreleased)

- On open-meridian 0.27.0 (contract 23): the pins moved as the SDK's
  0.26.0 to 0.27.0 step moves them; meridian 0.1.43's checks.
- The `custody` role, beside `data` and `connectivity`, in SnapTrade
  0.16.0's shape: each account the token reaches (`/user/profile`), its
  balances, positions, history and this session's orders, and the quotes
  naming a holding's kind, read every **Read every** and reported in the
  contract's words: each account's kind (retirement by its IRA
  classification, else cash or margin by its type, another kept as
  reported); its sync state; a statement as of the day in New York, a row
  per position (its average cost derived from the cost basis) and the
  cash, settled and pending derived from its unsettled fills and the
  deployment's settlement dates, withheld while one has none; every history
  event converted to its kind or kept as reported, each given a derived ID.
- **Account currency** (the SDK's `account_currency`, contract v23):
  Tradier states no currency, so the plugin's admin supplies each linked
  account's; every amount carries it, supplied by that person, and nothing
  needing it is reported until it is set (the product owner, 2026-10-13).
- Custody's pages: **Account links** (`read_account_links`, `link_account`,
  checked by `check_link_account`), **Statements** (`read_statements`) and
  **History** (`read_account_activities`); **Raw records** serves custody
  too. Settings: custody's **Read every**, **Stale after** and **Account
  currency**. A third kind of raw record, `activity` (2555 days).
- Connectivity, contract 23: an order placed in Tradier's own web app has
  its fills reported on no placement, held unmatched until the desk's `ems`
  accepts or answers them DK; the accept's placement takes the order's
  later fills. Only fills after the plugin first watched the account are
  reported (`trading/originated.json`). The catalogue's
  `execution_acknowledgement` is none: Tradier takes none, so a DK tells it
  nothing. Every fill names Tradier's order ID.
- The suites: custody passes every case but 12 Tradier never presents, each
  with why, `currency-not-stated` and
  `resolve-gives-the-currency-with-its-provenance` on the supplied currency,
  each resolve carrying its entry (`ResolveIdentifierRequest.provenance`);
  connectivity passes every case but 11 not presented, among them
  `reports-a-bust` (Tradier states no bust or correction) and
  `reports-a-charge`; data marks v23's outcome cases not presented.
- `make e2e`: the Account currency set, Tradier's account linked to the
  e2e's account, its opening balance recorded from Tradier's statement by
  the desk (now holding `operations` too); an order placed in Tradier's web
  app reported on no placement and accepted to a new order; and after every
  fill, the book reconciled against Tradier's statement with no break.

## 0.6.0 (unreleased)

- The `connectivity` role (contract 22), beside `data`, in SnapTrade
  0.16.0's shape: the plugin places the placements naming its instance at
  Tradier as equity orders, in the account its `ems` mapped
  (`AccountScope.venue_account_map`), with the placement's ID as the
  order's tag, and reports acknowledgements, rejections (`unsupported` with
  nothing sent, or `venue rejected` with Tradier's words), replaces,
  cancels, expiries, fills and busts, each with its raw record. A status
  the mapping does not know is outcome unknown and resolved by reading; a
  send never answered is asked about by its tag, never sent again, across
  a restart (`trading/sent.json`).
- Fills: read from each account's orders every 5 seconds (Tradier streams
  no account's orders on its sandbox), at the last fill's price as Tradier
  states it where the growth is that fill, inferred from the averages
  otherwise, each derived to one ID; every fill's settlement date is the
  deployment's (ComputeDate, with its basis), since Tradier states none.
- Cancel and replace read from `Placement.change_requests`; a replace is
  Tradier's `PUT` of the order, which keeps its ID and never changes its
  quantity (a replace asking one is refused `unsupported`). Pauses and
  stops honoured, a stop's cancels reported naming its entry.
- The venue catalogue per venue account code: none on a read-only account;
  once trading is enabled on it by the connectivity role's admin
  (**Trading**, `enable_trading`, at `/admin/connections/enable-trading`),
  Tradier's order types and durations.
- Settings: `environment` and the token now serve both roles (on `sandbox`
  the developer sandbox's paper trading); sample data trades with a
  simulated brokerage. Nothing to re-enter.
- Two kinds of raw record, each with its window an admin sets: `responses`
  (30 days) and `trading` (2555 days), archivable; **Raw records** follows
  a fact's reference.
- The connectivity suite: 19 cases pass; 7 are not presented, each with
  why (calendars, locates, a fill's place of execution, compliance waits);
  `reports-a-charge` is not produced, Tradier stating no fee on a placement
  that filled nothing (for the product owner to rule on).
- `make e2e` runs the order path after the data steps (e2e/orders.py),
  with a stand-in desk (e2e/desk.py), against a simulated brokerage
  (src/tradier/synthetic_broker.py). Nothing reaches Tradier's brokerage
  API.

## 0.5.0 (unreleased)

- On open-meridian 0.26.0 (contract 22): the pins moved as the SDK's
  0.25.0 to 0.26.0 step (`meridian plugin migrate --to 0.26.0`) moves them,
  rewriting nothing. Contract 22 is the order path and settlement
  calendars; this plugin places no order and works out no date, so nothing
  else changes.
- The data suite's two calendar cases (`reads-a-calendar`,
  `asks-for-a-settlement-date`) are not presented, each with why: Tradier's
  bars are dated as Tradier states them, and nothing here needs a
  settlement calendar or a settlement date.
- AGENTS.md says to name a declared algorithm on autonomous work, and to
  work out a date in core (`compute_date`, `read_calendar`), never by hand.

## 0.4.0 (unreleased)

- On open-meridian 0.25.0 (contract 21): the pins moved as the SDK's
  0.24.0 to 0.25.0 step (`meridian plugin migrate --to 0.25.0`) moves them,
  rewriting nothing. Contract 21 lets a plugin's
  autonomous work act as its role's service account; this plugin acts on
  nothing of the deployment's by itself, so nothing else changes.
- AGENTS.md says how a plugin acts on its own: only as its role's service
  account, through `meridian.runs_as(role)`.

## 0.3.0 (unreleased)

- On open-meridian 0.24.0 (contract 20): the role is `data` (a data
  plugin), `dgm` until now.
- `environment`, the data role's setting, replaces `sandbox`: a required
  choice shown first, Live or Sandbox. One token, `tradier_access_token`,
  serves either, its value carried over, labelled "Access token" on the
  Settings form; the plugin's pages name it by the
  environment ("API access token" or "Sandbox access token") and say which
  environment the data comes from.
- Connection and Datasets are the data role's pages
  (spec/plugin-pages-follow-their-role): Connection's "Key", "Limits and
  use" and "Stream" ("Does not stream" on the sandbox), Datasets' "Served",
  "Wants" and "Subjects", in the role's order and words, with Tradier's
  environment, host, stream session, feed column and "Kept current" at the
  role's extension points; the "not set up yet" states; and
  `read_connection` and `read_datasets` answering the role's common fields
  with Tradier's beside. The data role's figures on the Summary.
- Datasets says whether a deployment admin has licensed each dataset,
  read from the deployment on start and every minute.
- A restart's gap is not backfilled, and Datasets says so: Tradier's time
  and sales history names no print by its sequence number.
- The setting `synthetic` is `sample_data` (Sample data), the SDK's.
- The data suite's v20 cases: a trade recorded and its datasets' licences
  read, presented; the taker's side, the maker's side inverted, an odd lot
  and a restart's gap not presented, each with why.

## 0.2.1 (unreleased)

- `sandbox`, a setting off by default, "Tradier's developer sandbox": for
  testing with a developer sandbox token, the plugin asks
  `sandbox.tradier.com` with it. Its data is delayed 15 minutes, so quotes
  are marked delayed, not real time; it does not stream, so no stream is
  opened and live prices are kept current once a minute as without one.
  Connection says "Tradier's developer sandbox: delayed 15 minutes, no
  streaming"; Datasets names the host asked in each dataset's feed. A live
  brokerage token leaves it off, and nothing changes.

## 0.2.0 (unreleased)

- On open-meridian 0.23.0 (contract 19): the lake's trades and quotes.
- `trades`, a new dataset: each of Tradier's time and sales with the
  platform's trade attributes (the session converted; a flag or a
  correction kept as reported, Tradier documenting none), its sequence
  number, and no aggressor, which Tradier never states; a cancel the
  trade's next version. Streamed for the listings under a standing want;
  kept two days by default.
- `live` gains quotes: the consolidated best bid and offer, sizes in shares
  from Tradier's hundreds, one side empty where Tradier sends none, streamed
  at most once a second a listing, or read for a reader's want.
- Tradier's stream over WebSocket (the standard library's own client), a
  session made with the token and kept out of every raw record, with
  reconnect and subscriptions made again from the standing wants.
- Fixed, as in meridian-alpaca: a second record of one listing is recorded
  under its own row key (the key names the record), not under the first's,
  which the lake versioned as a restatement; a day read again unchanged
  keeps its raw record. Rows recorded by 0.1.0 keep their keys.
- The SDK's suite with its 1b cases: five not presented, each with why.
- Connection shows the stream; Datasets searches and pages the standing
  wants (kit 0.11.0). `make live` listens to the stream for twenty seconds.

## 0.1.0 (unreleased)

- A `dgm` on open-meridian 0.22.0 (contract 18): the catalogue's `daily`
  (closes and daily bars from Tradier's daily history, consolidated, New
  York's day to the 16:00 close, pulled and pushed) and `live` (last, bid and
  ask from Tradier's quotes, consolidated and real time for an account
  holder; pulled and kept current while a standing want stands), each with
  Tradier's personal-use terms as its default licence.
- Wants answered or declined per subject; a forming day restated under one
  row key until final; listings resolved by their one spelling (`BRK.B`,
  asked of Tradier as `BRK/B`), a last price's exchange by Tradier's code,
  misses reported.
- An instrument the book holds from another source, known only by that
  source's identifiers (a custodian's symbol and CUSIP), read from its
  record and priced under the listing's one spelling.
- Connection and Datasets under Manage, each a read tool
  (`read_connection`, `read_datasets`).
- The SDK's `dgm` suite, unchanged; an e2e on core's plugin harness with the
  synthetic exchange, and `make e2e-recorded` with a developer's recording;
  `make live`, the account holder's live check, against Tradier or its
  sandbox.