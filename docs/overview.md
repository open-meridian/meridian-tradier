# Overview

The Tradier plugin reads Tradier's US equity and ETF market data and records
it in your deployment's lake, where a plugin that values your book, or shows
prices, reads it under the licence and entitlements you set.

It serves three datasets:

- **Daily** (`tradier:daily`): each listing's close and daily bar for a
  business date, from Tradier's daily history, consolidated across
  exchanges. A date is New York's trading day, final at the 16:00 close;
  until then the day is still forming, and is updated in place as it fills.
  Daily prices are read when a plugin asks for them, and each evening the
  closes of every listing already served are recorded unasked.
- **Live** (`tradier:live`): the last trade's price and the best bid and
  ask, consolidated from every exchange and real time for a Tradier
  Brokerage account holder. Kept current once a minute while something is
  reading them; the best bid and offer, with its sizes in shares, streamed as
  it changes, at most once a second.
- **Trades** (`tradier:trades`): each of Tradier's time and sales, streamed
  while something is reading the listing, with what it may count for in a
  day's high, low, open, close and volume where Tradier says. Kept two days
  by default, so a plugin that missed some catches up. If the stream drops,
  the plugin reconnects; what printed in between is not filled in.

Every price is exact, as Tradier stated it. Every response Tradier sent is
kept in the plugin's own storage, without your token, so any price can be
traced to what Tradier said.

It does not serve options or mutual funds, and it does not connect your
Tradier brokerage account: that is a different role, for a later version.
Tradier does not say which side of a trade took liquidity, so the plugin
does not either.

An instrument your deployment knows only from another source, such as a
custodian, is priced under its symbol.
