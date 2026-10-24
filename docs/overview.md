# Overview

The Tradier plugin reads Tradier's US equity and ETF market data and records
it in your deployment's lake, where a plugin that values your book, or shows
prices, reads it under the licence and entitlements you set.

It holds three roles, `data`, `custody` and `connectivity`: the first-use path, the common pages and the Summary figures of each are described once, on [Using a data plugin](https://open-meridian.dev/how-to/using-a-data-plugin/) and [Using a custody plugin](https://open-meridian.dev/how-to/using-a-custody-plugin/). These sections cover what is Tradier's own.

## Its datasets

It serves four datasets, live data one per timeliness:

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
  it changes, at most once a second. Recorded while Environment is Live.
- **Live, delayed** (`tradier:live_delayed`): the same from Tradier's
  developer sandbox, delayed 15 minutes, as it declares; recorded while
  Environment is Sandbox, kept current by reading, never streamed.

## Its trades

- **Trades** (`tradier:trades`): each of Tradier's time and sales, streamed
  while something is reading the listing, with what it may count for in a
  day's high, low, open, close and volume where Tradier says. Kept two days
  by default, so a plugin that missed some catches up. If the stream drops,
  the plugin reconnects; what printed in between is not filled in.

## How it records

Every price is exact, as Tradier stated it. Every response Tradier sent is
kept in the plugin's own storage, without your token, so any price can be
traced to what Tradier said.

It does not serve options or mutual funds, and it does not trade options.
Tradier does not say which side of a trade took liquidity, so the plugin
does not either.

An instrument your deployment knows only from another source, such as a
custodian, is priced under its symbol.

## The account at Tradier

As a custody plugin it reads the account at Tradier every **Read every** as the
custodian's view: its sync state, a statement as of the day in New York (a
row per position, and the cash), and its activity -- fills, dividends,
interest, fees, taxes, transfers, deposits, withdrawals and journals, any
other type kept as reported. Tradier states no currency for any holding or amount, so the plugin's admin supplies each linked account's on **Account currency**; until a row covers an account, its statements and activity are not reported. Tradier states no settled quantity: each fill not yet settled is pending on the deployment's settlement date for it. Its developer sandbox serves no account history. Nothing is reported for an account
nothing links.

## Orders at Tradier

As a connectivity plugin it places the orders your execution plugin (an
`ems`) sends it at Tradier, in the account its code names, and reports what
Tradier did with each: acknowledged, rejected, replaced, cancelled, filled.
Tradier streams no account's orders on its sandbox, so the plugin reads each account's orders every 5 seconds: a fill is the growth in the order's executed quantity. Every fill carries the deployment's settlement date for it, and
waits for it rather than go with a guess. An order placed in Tradier's own web app is
never recorded as an order: its fills are reported on no order, for your
execution plugin to accept or answer DK; Tradier states its symbol and no
currency, so the fills are priced in its instrument's currency. A new
account is read-only until the connectivity role's admin enables trading on
it.

Every order is placed directly at Tradier: it takes no request for quote,
so an RFQ placement is rejected as unsupported, as is a good-till-date
order, nothing sent. The time each call to Tradier takes, an order's
acknowledgement and a fill's delay are shown on Connection.
