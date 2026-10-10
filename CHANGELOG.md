# Changelog

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
