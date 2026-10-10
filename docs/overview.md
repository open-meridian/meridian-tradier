# Overview

The Tradier plugin reads Tradier's US equity and ETF market data and records
it in your deployment's lake, where a plugin that values your book, or shows
prices, reads it under the licence and entitlements you set.

It serves two datasets:

- **Daily** (`tradier:daily`): each listing's close and daily bar for a
  business date, from Tradier's daily history, consolidated across
  exchanges. A date is New York's trading day, final at the 16:00 close;
  until then the day is still forming, and is updated in place as it fills.
  Daily prices are read when a plugin asks for them, and each evening the
  closes of every listing already served are recorded unasked.
- **Live** (`tradier:live`): the last trade's price and the best bid and
  ask, consolidated from every exchange and real time for a Tradier
  Brokerage account holder. Kept current once a minute while something is
  reading them.

Every price is exact, as Tradier stated it. Every response Tradier sent is
kept in the plugin's own storage, without your token, so any price can be
traced to what Tradier said.

It does not serve options or mutual funds, trades or quotes with sizes, and
it does not connect your Tradier brokerage account: that is a different
role, for a later version.

**A limit today:** the plugin can price only the listings it has resolved by
their symbol. An instrument your deployment knows only from another source,
such as a custodian, is not yet one it can ask Tradier about; its Datasets
page says so when it happens.
