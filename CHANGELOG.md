# Changelog

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
