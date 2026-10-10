# Changelog

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
