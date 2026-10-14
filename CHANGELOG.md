# Changelog

## 0.7.1 (unreleased)

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
